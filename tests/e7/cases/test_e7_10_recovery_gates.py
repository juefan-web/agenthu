"""E7-10 driver: recovery, key-rotation and license gates (mechanism face).

The four frozen mechanism assertions (m5-e7-acceptance §2 E7-10; execution
task doc §3 split 1) run on dedicated stacks the single-stack verifier
cannot reach, so they ride DRIVER_INVARIANTS (the E7-9 precedent):

- ``license_cleared`` — 分项 2 引用对账 only: the committed license-inventory
  terminal state (§7 cargo / §8 npm zero-red-flag censuses, §9 user rulings,
  阻断规则), the README temporary-public seal and the per-file notices are
  referenced, never re-surveyed (task doc §3: execution only cites the
  reconciliation). The real key-rotation evidence slot stays 「未提供」
  (分项 3, acceptance §2 tail note — replay never substitutes it).
- ``old_key_rejected_new_key_works`` — 假件轮换语义: a scratch stack's
  SECRET_KEY is rotated K_old → K_new via config switch + process restart
  (the ops-contract §6 sequence 新key验证→切配置→撤旧key→旧拒绝/新最低额度
  验证). The K_old JWT is then 401 on every business face; a K_new login
  reads through.
- ``restore_replays_suppression`` (+ the no-resurrect faces) — the drill:
  pg_dump the freshly seeded world (backup, pre-deletion) → delete the
  anchored event e1 through the real preview/confirm path → export the
  value-keyed suppression ledger + data_generation independently → restore
  the dump into an ISOLATED database → replay the ledger BEFORE any stack
  comes up (suppression-first ordering) → re-run the deletion through the
  real closure executor as the recovery-window maintenance action → only
  then declare traffic open. The net is then proven live: the same upstream
  anchor under a fresh client_event_id AND semantic_version is 409
  ``source_deleted`` (a different semantic_version means a different dedupe
  key, so only the suppression net can produce this 409).
- ``rpo_rto_measured`` — wall-clock around the drill (backup → failure →
  restore start → replay → traffic). Alpha targets (RPO<=24h / RTO<=4h)
  are proposals in the ops contract; no SLO claim is made here.

Redis is NEVER restored (fresh db index): the restored stack starts with a
queued-job count of zero, and the only operation rows on it are the
maintenance re-deletion — old-queue resurrection would surface as phantom
operations. The restored stack MUST run the same SECRET_KEY as the source
stack: suppression anchors are HMAC'd under the server secret
(write_guards.upstream_hmac), which is also why rotation needs a digest
migration plan (driver-level finding, recorded in the task doc §7).
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import redis as redis_lib
from sqlalchemy import create_engine, text

from tests.e7.conftest import confirm_target, login, verify_report, wait_operation, write_evidence
from tests.e7.seed_spec import World
from tests.e7.verify import FAMILY_OWNER_SQL

_REPO = Path(__file__).resolve().parents[3]

RESTORE_DB = "agenthu_e7_10_restore"
ROTATE_DB = "agenthu_e7_10_rotate"
RESTORE_API = "http://127.0.0.1:8013"
ROTATE_API_A = "http://127.0.0.1:8112"  # runs SECRET_KEY = K_OLD
ROTATE_API_B = "http://127.0.0.1:8113"  # runs SECRET_KEY = K_NEW
RESTORE_REDIS_DB = 5  # fresh ledger on the E7 redis container (:6380)
ROTATE_REDIS_DB = 6

# Synthetic, >= 32 chars, none of the weak-key denylist values.
K_OLD = "e7-10-rotation-old-key-synthetic-0000000001"
K_NEW = "e7-10-rotation-new-key-synthetic-0000000002"

ROTATE_USER = {
    "email": "e7-10-rotate@test.invalid",
    "password": "e7-10-rotate-password-0001",
    "display_name": "E7-10 轮换探针",
}

# Fresh ids on purpose: a new client_event_id AND a new semantic_version give
# a dedupe key no seeded/deleted row can match — only the suppression net
# can answer this envelope (E7-7 proved the no-net shape is a 201).
REIMPORT_PAYLOAD = {
    "type": "study.assignment.created",
    "timestamp": "2026-10-13T06:00:00+00:00",
    "source": "onethu",
    "data": {
        "title": "重采探测（E7-10 驱动）",
        "course": "线性代数",
        "due_at": "2026-10-22T00:00:00+00:00",
    },
    "provenance": {
        "connector": "onethu",
        "connector_version": "1",
        "upstream_id": "E7-U-asg-1",
        "semantic_version": "2",
        "fetched_at": "2026-10-13T06:00:00+00:00",
    },
    "client_event_id": "e7-10-reimport-1",
}

_PROCS: list[subprocess.Popen[bytes]] = []  # keep subprocess handles alive


def _evidence_dir() -> Path:
    round_id = os.environ.get("AGENTHU_E7_ROUND", "smoke")
    directory = Path("output/e7") / round_id / "E7-10"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _docker(*args: str, timeout: float = 300.0) -> None:
    result = subprocess.run(["docker", *args], capture_output=True, timeout=timeout)
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace")[:600]
        pytest.fail(f"docker {' '.join(args)} failed: {stderr}")


def _psql_admin(sql: str) -> None:
    _docker(
        "exec",
        "agenthu-db-1",
        "psql",
        "-U",
        "agenthu",
        "-d",
        "postgres",
        "-v",
        "ON_ERROR_STOP=1",
        "-c",
        sql,
    )


def _db_url(dbname: str) -> str:
    head, _, _ = os.environ["E7_DATABASE_URL"].rpartition("/")
    return f"{head}/{dbname}"


def _redis_url(db: int) -> str:
    head, _, _ = os.environ["E7_REDIS_URL"].rpartition("/")
    return f"{head}/{db}"


def _stack_env(**overrides: str) -> dict[str, str]:
    env = os.environ.copy()
    env.update(overrides)
    return env


def _spawn(label: str, args: list[str], **overrides: str) -> subprocess.Popen[bytes]:
    handle = (_evidence_dir() / f"{label}.log").open("wb")
    process = subprocess.Popen(
        args,
        stdout=handle,
        stderr=subprocess.STDOUT,
        env=_stack_env(**overrides),
        cwd=str(_REPO),
    )
    _PROCS.append(process)
    return process


def _spawn_api(
    port: int, label: str, *, secret_key: str, database_url: str
) -> subprocess.Popen[bytes]:
    return _spawn(
        label,
        [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        SECRET_KEY=secret_key,
        DATABASE_URL=database_url,
        REDIS_URL=_redis_url(ROTATE_REDIS_DB if label.startswith("rotate") else RESTORE_REDIS_DB),
    )


def _spawn_restore_worker() -> None:
    _spawn(
        "restore-worker",
        [sys.executable, "-m", "arq", "backend.worker.settings.WorkerSettings"],
        DATABASE_URL=_db_url(RESTORE_DB),
        REDIS_URL=_redis_url(RESTORE_REDIS_DB),
    )


def _stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=15)


def _wait_health(base_url: str, process: subprocess.Popen[bytes], timeout_s: float = 90.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if process.poll() is not None:
            pytest.fail(f"api at {base_url} exited early with {process.returncode}")
        try:
            if httpx.get(f"{base_url}/health", timeout=2.0).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    pytest.fail(f"api at {base_url} never became healthy within {timeout_s}s")


def _require_ports_free(*ports: int) -> None:
    for port in ports:
        with socket.socket() as probe:
            probe.settimeout(0.5)
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                pytest.fail(f"port {port} is occupied; the E7-10 stacks need it free")


def _alembic_upgrade(dbname: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        capture_output=True,
        cwd=str(_REPO),
        env=_stack_env(DATABASE_URL=_db_url(dbname)),
        timeout=180,
    )
    if result.returncode != 0:
        pytest.fail(
            "alembic upgrade on the scratch db failed: "
            + result.stderr.decode("utf-8", errors="replace")[:600]
        )


def _scan_token_anywhere(engine: Any, token: str) -> list[str]:
    """Whole-row text scan across every family (verify.py's anywhere-scan,
    against a driver-owned engine — the restored database)."""

    hits: list[str] = []
    with engine.connect() as conn:
        for table in sorted(FAMILY_OWNER_SQL):
            count = int(
                conn.execute(
                    text(f"SELECT count(*) FROM {table} WHERE {table}::text ILIKE :p"),
                    {"p": f"%{token}%"},
                ).scalar_one()
            )
            if count:
                hits.append(f"{table}:{count}")
    return hits


def _license_reference_face() -> dict[str, Any]:
    """分项 2: reference the committed license-gate terminal state."""

    inventory = (_REPO / "AGENT_CONTEXT/TASKS/m5-p0-6-license-inventory.md").read_text(
        encoding="utf-8"
    )
    readme = (_REPO / "README.md").read_text(encoding="utf-8")
    notices_path = _REPO / "THIRD_PARTY_NOTICES.md"
    notices = notices_path.read_text(encoding="utf-8") if notices_path.exists() else ""

    faces = {
        # Status line: §7/§8 双普查零红旗 + 二进制封印维持 + 阻断规则.
        "inventory_census_zero_red_flags": "零红旗" in inventory,
        "inventory_seal_maintained": "封印" in inventory,
        "inventory_publish_block_rule": ("未澄清" in inventory) and ("不发布" in inventory),
        "inventory_user_rulings": "用户裁定" in inventory,
        "readme_temporary_public_seal": "temporarily public" in readme
        and "No license is" in readme,
        "readme_in_tree_licenses": "in-tree LICENSE files" in readme,
        "notices_present": bool(notices.strip()),
        "notices_per_file_conclusions": ("OneTHU core" in notices) and ("Pinned commit" in notices),
    }
    for name, ok in faces.items():
        assert ok, f"license-gate reference face failed: {name}"
    return {
        "faces": faces,
        "form": "分项 2 引用对账（不重新普查，任务书 §3）",
        "real_key_rotation_evidence": "未提供（分项 3：操作者级证据位，replay 不充数）",
    }


def _flush_scratch_redis(db: int) -> None:
    """Wipe the case-owned redis ledger. "Fresh" here means wiped-on-purpose:
    redis is never restored from any dump — a previous round's leftover
    result keys must not leak into the next run's emptiness assertions."""

    redis_lib.Redis.from_url(_redis_url(db), decode_responses=True, socket_timeout=5).flushdb()


def _rotation_face() -> dict[str, Any]:
    """假件轮换: same scratch db, K_old process then K_new process."""

    _require_ports_free(8112, 8113)
    _psql_admin(f"DROP DATABASE IF EXISTS {ROTATE_DB} WITH (FORCE)")
    _psql_admin(f"CREATE DATABASE {ROTATE_DB} OWNER agenthu")
    _alembic_upgrade(ROTATE_DB)
    _flush_scratch_redis(ROTATE_REDIS_DB)
    rotate_db_url = _db_url(ROTATE_DB)

    api_a = _spawn_api(8112, "rotate-a", secret_key=K_OLD, database_url=rotate_db_url)
    _wait_health(ROTATE_API_A, api_a)
    with httpx.Client(base_url=ROTATE_API_A, timeout=30.0) as client:
        registered = client.post("/v1/auth/register", json=ROTATE_USER)
        assert registered.status_code == 201, registered.text
        token_old = client.post("/v1/auth/login", json=ROTATE_USER).json()["access_token"]
        headers_old = {"Authorization": f"Bearer {token_old}"}
        assert client.get("/v1/auth/me", headers=headers_old).status_code == 200
    _stop(api_a)  # the operator withdraws K_old (切配置 → 撤旧 key)

    api_b = _spawn_api(8113, "rotate-b", secret_key=K_NEW, database_url=rotate_db_url)
    _wait_health(ROTATE_API_B, api_b)
    faces: dict[str, Any] = {}
    with httpx.Client(base_url=ROTATE_API_B, timeout=30.0) as client:
        me = client.get("/v1/auth/me", headers=headers_old)
        assert me.status_code == 401, me.text
        assert me.json()["error"]["code"] == "unauthenticated", me.text
        events = client.get("/v1/events", headers=headers_old)
        assert events.status_code == 401, events.text
        faces["old_key_rejected"] = {"auth_me": 401, "events_list": 401}

        token_new = client.post("/v1/auth/login", json=ROTATE_USER).json()["access_token"]
        headers_new = {"Authorization": f"Bearer {token_new}"}
        assert client.get("/v1/auth/me", headers=headers_new).status_code == 200
        listed = client.get("/v1/events", headers=headers_new)
        assert listed.status_code == 200, listed.text
        faces["new_key_works"] = {
            "auth_me": 200,
            "events_list": 200,
            "events_count": len(listed.json().get("items", [])),
        }
    _stop(api_b)
    _psql_admin(f"DROP DATABASE {ROTATE_DB} WITH (FORCE)")
    return faces


def test_e7_10_recovery_rotation_and_restore_gates(
    e7_api, e7_fresh_world, e7_verifier, e7_engine
) -> None:  # type: ignore[no-untyped-def]
    world: World = e7_fresh_world
    user = world.users["U"]
    event_id = str(world.rid("U", "e1"))
    headers = login(e7_api, world, "U")
    outdir = _evidence_dir()
    evidence: dict[str, Any] = {"faces": {}}

    evidence["faces"]["license-gate"] = _license_reference_face()
    evidence["faces"]["key-rotation"] = _rotation_face()

    # -- backup (pre-deletion world) --------------------------------------
    t_backup_start = time.monotonic()
    _docker(
        "exec",
        "agenthu-db-1",
        "pg_dump",
        "-U",
        "agenthu",
        "-d",
        "agenthu_e7",
        "-f",
        "/tmp/e7-10-backup.sql",
    )
    _docker("cp", "agenthu-db-1:/tmp/e7-10-backup.sql", str(outdir / "backup.sql"))
    t_backup_end = time.monotonic()
    wall_backup_end = datetime.now(UTC)
    assert (outdir / "backup.sql").stat().st_size > 0

    # -- the deletion whose loss the restore must not undo ----------------
    _preview, operation = confirm_target(
        e7_api,
        headers,
        target={"kind": "source", "source_kind": "event", "ids": [event_id]},
        key="e7-10-confirm",
    )
    settled = wait_operation(e7_api, headers, operation["id"])
    assert settled["status"] == "COMPLETED", settled
    t_failure = time.monotonic()

    # -- source-stack face: invalid bases must not serve the deleted
    # originals (invalid_basis_no_original_text). The anchored e1 delete is
    # the same action E7-3a freezes, so the same survivor faces apply here:
    # p1/pi1/r1 keep serving the dead ids (the dangling references) while
    # e1/t1 original text stays absent from every response body.
    plan_face = e7_api.get(f"/v1/plans/{world.rid('U', 'p1')}", headers=headers)
    assert plan_face.status_code == 200, plan_face.text
    run_face = e7_api.get(f"/v1/agent/runs/{world.rid('U', 'r1')}", headers=headers)
    assert run_face.status_code == 200, run_face.text
    task_id = str(world.rid("U", "t1"))
    plan_body = plan_face.json()
    served_refs = {ref["id"] for ref in plan_body["basis"]["references"]}
    assert served_refs == {event_id, task_id}, served_refs
    pi1_face = next(item for item in plan_body["items"] if item["id"] == str(world.rid("U", "pi1")))
    assert pi1_face["task_id"] is None  # FK SET NULL marks the basis invalid
    assert set(pi1_face["basis"].values()) == {event_id, task_id}
    assert event_id in run_face.text  # the run face still serves the dead id
    leaked = [
        name
        for name in ("e1.title", "t1.title")
        if world.marker_names["U"][name] in plan_face.text + run_face.text
    ]
    assert not leaked, leaked
    evidence["faces"]["source-stack-invalid-basis"] = {
        "plan_references_served": sorted(served_refs),
        "pi1_task_link": None,
        "run_face_serves_deleted_event_id": True,
        "original_text_leaked_markers": leaked,
    }

    # -- independent ledger export (value-keyed rows alone; no users FK) ---
    with e7_engine.connect() as conn:
        sup_rows = [
            dict(row._mapping)
            for row in conn.execute(
                text(
                    "SELECT id, owner_handle, source_kind, upstream_hmac, "
                    "raised_generation, created_at, updated_at "
                    "FROM data_suppressions WHERE released_at IS NULL"
                )
            )
        ]
        generations = {
            str(row[0]): int(row[1])
            for row in conn.execute(text("SELECT id, data_generation FROM users"))
        }
        window_changes = {
            table: int(
                conn.execute(
                    text(f"SELECT count(*) FROM {table} WHERE created_at > :t"),
                    {"t": wall_backup_end},
                ).scalar_one()
            )
            for table in (
                "data_operations",
                "data_previews",
                "data_cleanup_items",
                "data_barriers",
                "data_suppressions",
            )
        }
    assert len(sup_rows) == 1, f"expected exactly one active suppression, got {len(sup_rows)}"
    assert sup_rows[0]["owner_handle"] == user.owner_handle
    ledger = {
        "suppressions": sup_rows,
        "data_generations": generations,
        "exported_at": datetime.now(UTC).isoformat(),
    }
    (outdir / "ledger.json").write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    # -- isolated restore ---------------------------------------------------
    t_restore_start = time.monotonic()
    wall_restore_start = datetime.now(UTC)
    _psql_admin(f"DROP DATABASE IF EXISTS {RESTORE_DB} WITH (FORCE)")
    _psql_admin(f"CREATE DATABASE {RESTORE_DB} OWNER agenthu")
    _docker("cp", str(outdir / "backup.sql"), "agenthu-db-1:/tmp/e7-10-restore.sql")
    _docker(
        "exec",
        "agenthu-db-1",
        "psql",
        "-U",
        "agenthu",
        "-d",
        RESTORE_DB,
        "-v",
        "ON_ERROR_STOP=1",
        "-f",
        "/tmp/e7-10-restore.sql",
    )
    t_import_done = time.monotonic()
    restore_engine = create_engine(_db_url(RESTORE_DB))

    # schema validation: the restored db must sit at the same migration head.
    with restore_engine.connect() as conn:
        restored_head = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    with e7_engine.connect() as conn:
        source_head = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert restored_head == source_head

    # checksum validation: backup == freshly seeded world == manifest before_counts.
    before = e7_verifier.manifest["before_counts"]
    assert isinstance(before, dict)
    checksum: dict[str, int] = {}
    with restore_engine.connect() as conn:
        for tag in ("U", "V"):
            uid, handle = str(world.users[tag].user_id), world.users[tag].owner_handle
            for table, expected in sorted(before[tag].items()):
                actual = int(
                    conn.execute(
                        text(f"SELECT count(*) FROM {table} WHERE {FAMILY_OWNER_SQL[table]}"),
                        {"uid": uid, "handle": handle},
                    ).scalar_one()
                )
                assert actual == expected, (
                    f"restored checksum {tag}:{table}: {actual} != {expected}"
                )
                checksum[f"{tag}:{table}"] = actual

    # the hazard, honestly shown: naive restore DOES contain the deleted content.
    with restore_engine.connect() as conn:
        present = int(
            conn.execute(
                text("SELECT count(*) FROM events WHERE id = CAST(:i AS uuid)"), {"i": event_id}
            ).scalar_one()
        )
    hazard_marker = world.marker_names["U"]["e1.title"]
    hazard_hits = _scan_token_anywhere(restore_engine, hazard_marker)
    assert present == 1 and hazard_hits, "pre-replay restore must still contain e1"

    # -- suppression-first replay, before any stack comes up ----------------
    t_replay_start = time.monotonic()
    with restore_engine.begin() as conn:
        for row in sup_rows:
            inserted = conn.execute(
                text(
                    "INSERT INTO data_suppressions (id, owner_handle, source_kind, "
                    "upstream_hmac, raised_generation, created_at, updated_at) VALUES ("
                    "CAST(:id AS uuid), :owner_handle, :source_kind, :upstream_hmac, "
                    ":raised_generation, CAST(:created_at AS timestamptz), "
                    "CAST(:updated_at AS timestamptz)) "
                    "ON CONFLICT (owner_handle, source_kind, upstream_hmac) DO NOTHING"
                ),
                {key: str(value) for key, value in row.items()},
            ).rowcount
            assert inserted == 1, "the replayed suppression row must land"
        for uid, generation in generations.items():
            conn.execute(
                text("UPDATE users SET data_generation = :g WHERE id = CAST(:uid AS uuid)"),
                {"g": generation, "uid": uid},
            )
    t_replay_done = time.monotonic()

    # redis is never restored: the ledger is wiped, then proven empty — no
    # arq keys (no old queue), no rate-limit carryover.
    _flush_scratch_redis(RESTORE_REDIS_DB)
    fresh_redis = redis_lib.Redis.from_url(
        _redis_url(RESTORE_REDIS_DB), decode_responses=True, socket_timeout=5
    )
    assert sorted(fresh_redis.scan_iter()) == [], "restored-stack redis must start empty"

    # -- isolated stack (same SECRET_KEY: suppression anchors are HMAC-bound)
    _require_ports_free(8013)
    api = _spawn_api(
        8013, "restore-api", secret_key=os.environ["SECRET_KEY"], database_url=_db_url(RESTORE_DB)
    )
    _wait_health(RESTORE_API, api)
    _spawn_restore_worker()

    # -- maintenance re-deletion through the REAL closure executor ----------
    with httpx.Client(base_url=RESTORE_API, timeout=30.0) as client:
        token = client.post(
            "/v1/auth/login",
            json={"email": user.email, "password": user.password},
        ).json()["access_token"]
        mheaders = {"Authorization": f"Bearer {token}"}
        _m_preview, m_operation = confirm_target(
            client,
            mheaders,
            target={"kind": "source", "source_kind": "event", "ids": [event_id]},
            key="e7-10-restore-maintenance",
        )
        m_settled = wait_operation(client, mheaders, m_operation["id"])
        assert m_settled["status"] == "COMPLETED", m_settled
        t_traffic_allowed = time.monotonic()

        # first user business traffic after the declaration
        first = client.get("/v1/events", headers=mheaders)
        assert first.status_code == 200, first.text

        # no-resurrect through the live net (fresh ids — see REIMPORT_PAYLOAD)
        reimported = client.post("/v1/events", json=REIMPORT_PAYLOAD, headers=mheaders)
        assert reimported.status_code == 409, reimported.text
        assert reimported.json()["error"]["code"] == "source_deleted", reimported.text

    # end state on the restored db: content gone, net active, no phantom work.
    with restore_engine.connect() as conn:
        gone = int(
            conn.execute(
                text("SELECT count(*) FROM events WHERE id = CAST(:i AS uuid)"), {"i": event_id}
            ).scalar_one()
        )
        active = int(
            conn.execute(
                text(
                    "SELECT count(*) FROM data_suppressions "
                    "WHERE released_at IS NULL AND owner_handle = :h"
                ),
                {"h": user.owner_handle},
            ).scalar_one()
        )
        runtime_ops = int(
            conn.execute(
                text("SELECT count(*) FROM data_operations WHERE created_at > :t"),
                {"t": wall_restore_start},
            ).scalar_one()
        )
    assert gone == 0, "the maintenance re-deletion must remove e1 on the restored db"
    assert active == 1, "exactly one active suppression (replayed row; confirm skips duplicates)"
    assert runtime_ops == 1, "only the maintenance operation — no old-queue resurrection"
    for name in ("e1.title", "t1.title", "fs1.deviation"):
        assert _scan_token_anywhere(restore_engine, world.marker_names["U"][name]) == []
    assert fresh_redis.llen("arq:queue:queue") == 0

    # -- RPO / RTO (drill-measured wall clock; no SLO claim) ----------------
    rpo = t_failure - t_backup_end
    rto = t_traffic_allowed - t_restore_start
    assert rpo > 0 and rto > 0
    assert t_backup_end < t_failure < t_restore_start < t_replay_done < t_traffic_allowed
    evidence["rpo_rto"] = {
        "rpo_seconds": round(rpo, 3),
        "rto_seconds": round(rto, 3),
        "phases_seconds": {
            "backup": round(t_backup_end - t_backup_start, 3),
            "import": round(t_import_done - t_restore_start, 3),
            "ledger_replay": round(t_replay_done - t_replay_start, 3),
            "maintenance_redelete": round(t_traffic_allowed - t_replay_done, 3),
        },
        "window_changes_on_source": window_changes,
        "suppression_replayed_before_traffic": True,
        "note": (
            "drill-measured wall clock on the local acceptance stack; Alpha "
            "targets (RPO<=24h/RTO<=4h) are ops-contract proposals, not claims"
        ),
    }
    evidence["restore"] = {
        "checksum_families": len(checksum),
        "hazard_pre_replay": {"events_e1": present, "marker_hits": hazard_hits},
        "restored_operation_id": m_operation["id"],
        "reimport": {"status": 409, "code": "source_deleted"},
        "restored_runtime_operations": runtime_ops,
    }

    write_evidence("E7-10", "recovery.json", evidence)
    write_evidence("E7-10", "operation.json", settled)
    write_evidence("E7-10", "restore-operation.json", m_settled)

    report = verify_report(e7_verifier, "E7-10")
    write_evidence("E7-10", "verify.json", report.to_dict())

    # teardown: the isolated stack goes away; evidence files stay local.
    for process in list(_PROCS):
        _stop(process)
    _PROCS.clear()
    restore_engine.dispose()
    _psql_admin(f"DROP DATABASE IF EXISTS {RESTORE_DB} WITH (FORCE)")
