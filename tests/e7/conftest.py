"""E7 suite fixtures — active only behind the ``AGENTHU_E7_STACK=1`` gate.

Without the gate the ``cases`` directory is not collected, so ordinary CI
shape is unchanged (no new skips). With the gate, each case test gets a
freshly rebuilt seed world (m5-e7-acceptance §1 "每用例重建seed") against
the isolated acceptance stack; the stack itself (uvicorn/worker/db/redis/
bucket) is brought up by the runbook in README.md, never by the suite.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine

from tests.e7.manifest import MANIFEST_PATH
from tests.e7.seed_spec import World, build_world
from tests.e7.verify import E7Verifier, VerifyReport

GATED = os.environ.get("AGENTHU_E7_STACK") == "1"

if not GATED:
    collect_ignore = ["cases"]


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.fail(f"AGENTHU_E7_STACK is set but {name} is missing (see tests/e7/README.md)")
    return value


@pytest.fixture(scope="session")
def e7_engine():  # type: ignore[no-untyped-def]
    if not GATED:
        pytest.skip("E7 stack gate is off")
    yield create_engine(_require_env("E7_DATABASE_URL"))


@pytest.fixture(scope="session")
def e7_manifest() -> dict:  # type: ignore[type-arg]
    import json

    return dict(json.loads(MANIFEST_PATH.read_text(encoding="utf-8")))


@pytest.fixture(scope="session")
def e7_world() -> World:
    return build_world()


@pytest.fixture(scope="session")
def e7_verifier(e7_engine, e7_manifest):  # type: ignore[no-untyped-def]
    return E7Verifier(e7_engine, e7_manifest)


@pytest.fixture(scope="session")
def e7_backend_url() -> str:
    return _require_env("AGENTHU_E7_BACKEND_URL")


@pytest.fixture()
def e7_api(e7_backend_url) -> Iterator[httpx.Client]:  # type: ignore[no-untyped-def]
    with httpx.Client(base_url=e7_backend_url, timeout=30.0) as client:
        yield client


@pytest.fixture()
def e7_fresh_world(e7_engine) -> Iterator[World]:  # type: ignore[no-untyped-def]
    """Per-case rebuild: truncate + reseed + blobs + redis (ruling ⑨)."""

    from tests.e7 import seed as seed_mod

    seed_mod.truncate_all(e7_engine)
    world = build_world()
    seed_mod.apply_world(e7_engine, world)
    yield world


def login(e7_api: httpx.Client, world: World, tag: str) -> dict[str, str]:
    """Real login over HTTP; returns Authorization headers for the user."""

    spec = world.users[tag]
    response = e7_api.post("/v1/auth/login", json={"email": spec.email, "password": spec.password})
    response.raise_for_status()
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


# --- shared driver helpers (E7-3 template generalized; chaos faces) -------------


def confirm_target(
    e7_api: httpx.Client,
    headers: dict[str, str],
    *,
    target: dict[str, object],
    key: str,
) -> tuple[dict, dict]:  # type: ignore[type-arg]
    """Preview + Level-2 confirm for any DeleteTarget variant.

    Same call shape as the E7-3 reference driver (``_confirm_source``),
    generalized to the memory/account variants the action cases need.
    """

    preview_response = e7_api.post("/v1/data/previews", json=target, headers=headers)
    assert preview_response.status_code == 201, preview_response.text
    preview = preview_response.json()
    confirm_response = e7_api.post(
        "/v1/data/deletions",
        json={
            "preview_id": preview["id"],
            "preview_digest": preview["preview_digest"],
            "client_request_id": key,
            "confirmed": True,
        },
        headers=headers,
    )
    assert confirm_response.status_code == 202, confirm_response.text
    return preview, confirm_response.json()


def raw_confirm(
    e7_api: httpx.Client,
    headers: dict[str, str],
    preview: dict,  # type: ignore[type-arg]
    *,
    key: str,
    digest: str | None = None,
) -> httpx.Response:
    """POST /v1/data/deletions without asserting the status (protocol faces)."""

    return e7_api.post(
        "/v1/data/deletions",
        json={
            "preview_id": preview["id"],
            "preview_digest": digest if digest is not None else preview["preview_digest"],
            "client_request_id": key,
            "confirmed": True,
        },
        headers=headers,
    )


def sql_scalar(e7_engine, statement: str, params: dict | None = None) -> object:  # type: ignore[no-untyped-def]
    """One scalar off the acceptance DB for driver-level ledger asserts."""

    from sqlalchemy import text

    with e7_engine.connect() as conn:
        return conn.execute(text(statement), params or {}).scalar_one()


def sql_exec(e7_engine, statement: str, params: dict | None = None) -> None:  # type: ignore[no-untyped-def]
    """Run one statement with no result row (driver-side time surgery on
    preview expiry metadata; never ledger content)."""

    from sqlalchemy import text

    with e7_engine.begin() as conn:
        conn.execute(text(statement), params or {})


def stack_docker(*args: str) -> None:
    """Real chaos against the runbook's fixed containers (README §1/§2)."""

    import subprocess

    result = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        pytest.fail(f"docker {' '.join(args)} failed: {result.stderr.strip()}")


def stop_e7_redis() -> None:
    """Outage face: killing redis also kills the arq worker (its poll loop
    has no reconnect tolerance on this stack) — the real process-crash
    injection, proven by the r1-era worker traceback."""

    stack_docker("stop", "agenthu-e7-redis")


def start_e7_redis() -> None:
    stack_docker("start", "agenthu-e7-redis")


def stop_e7_object_store() -> None:
    """S3 outage face: a STOPPED s3mock refuses connections immediately
    (botocore EndpointConnectionError -> STAT_UNAVAILABLE / StorageError),
    which the erasure trichotomy must never read as absence."""

    stack_docker("stop", "agenthu-s3mock-1")


def start_e7_object_store() -> None:
    stack_docker("start", "agenthu-s3mock-1")


_RESPAWNED_WORKERS: list = []  # keep Popen handles alive past the test scope


def respawn_e7_worker() -> None:
    """Start a replacement arq worker against the E7 stack.

    Jobs live in redis, so any worker instance drains them; after a chaos
    kill this is the recovery process. Left running for later cases (the
    stack runbook owns exactly one worker at a time), log appended under
    the current round's evidence directory."""

    import subprocess
    import sys

    round_id = os.environ.get("AGENTHU_E7_ROUND", "smoke")
    log_path = Path("output/e7") / round_id / "_worker-respawn.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = log_path.open("ab")
    process = subprocess.Popen(
        [sys.executable, "-m", "arq", "backend.worker.settings.WorkerSettings"],
        stdout=handle,
        stderr=subprocess.STDOUT,
        env=os.environ.copy(),
    )
    _RESPAWNED_WORKERS.append(process)
    import time

    for _ in range(10):
        time.sleep(1.0)
        if process.poll() is not None:
            pytest.fail(f"respawned worker exited early with {process.returncode}")


def e7_redis():  # type: ignore[no-untyped-def]
    import redis as redis_lib

    return redis_lib.Redis.from_url(_require_env("E7_REDIS_URL"), decode_responses=True)


def e7_worker_alive() -> bool:
    """True when some arq worker heartbeats (the arq health-check key is
    refreshed every 30s with a TTL, so a positive TTL means a live worker
    regardless of who started it)."""

    try:
        value = e7_redis().ttl("arq:queue:health-check")
        return isinstance(value, int) and value > 0
    except Exception:
        return False


@pytest.fixture(autouse=True)
def e7_worker_presence(e7_fresh_world):  # type: ignore[no-untyped-def]
    """Environmental net: an arq worker on this Windows host can die with
    WinError 121 (semaphore timeout on the container-mapped redis port;
    observed twice in one day — 09:38 and 20:09 local), and a case that
    starts with no worker at all fails for a reason it does not test
    (every operation sits QUEUED forever). If no heartbeat is visible the
    case gets a fresh worker (the same respawn the chaos drivers use for
    their recovery faces) and the fact is recorded as evidence. When a
    worker is alive this fixture does nothing."""

    from datetime import UTC, datetime

    if e7_worker_alive():
        yield
        return
    respawn_e7_worker()
    write_evidence(
        "_stack",
        "worker-ensured.json",
        {
            "ensured_at": datetime.now(UTC).isoformat(),
            "reason": "no arq health-check heartbeat at case start (WinError 121 class)",
        },
    )
    yield


def mark_user_dirty(user_id: str) -> None:
    """Race injection: SADD the wake-up set member the 30s trigger drain
    consumes (the same best-effort path ingestion uses)."""

    e7_redis().sadd("agenthu:trigger:dirty", user_id)


def wait_operation(
    e7_api: httpx.Client,
    headers: dict[str, str],
    operation_id: str,
    *,
    timeout_s: float = 120.0,
    success_states: tuple[str, ...] = ("COMPLETED",),
) -> dict:  # type: ignore[type-arg]
    """Poll the operation until a terminal state. ``READY`` is export-
    specific (package staged and verified, awaiting download) — export
    callers pass it via ``success_states``; anything outside the accepted
    set is an honest failure, never a silent pass.

    Early 404s are tolerated, not errors: the API commits in the request
    dependency's teardown, which runs AFTER the response is sent (FastAPI
    >=0.106 yield-dependency semantics), so a confirm's 202 can briefly
    precede its own commit and a read inside that window 404s while the
    ledger is perfectly fine (product finding recorded with the D1
    notes). Only a 404 persisting to the deadline fails."""

    import time

    deadline = time.monotonic() + timeout_s
    terminal = {"COMPLETED", "READY", "FAILED", "EXPIRED", "CANCELLED"}
    payload: dict = {}
    while time.monotonic() < deadline:
        response = e7_api.get(f"/v1/data/operations/{operation_id}", headers=headers)
        if response.status_code == 404:
            time.sleep(0.5)
            continue
        response.raise_for_status()
        payload = response.json()
        if payload["status"] in terminal:
            if payload["status"] not in success_states:
                pytest.fail(f"operation {operation_id} settled as {payload['status']}: {payload}")
            return payload
        time.sleep(0.5)
    pytest.fail(
        f"operation {operation_id} did not settle within {timeout_s}s (last payload: {payload!r})"
    )
    raise AssertionError("unreachable")


def read_operation_visible(
    e7_api: httpx.Client,
    headers: dict[str, str],
    operation_id: str,
    *,
    timeout_s: float = 15.0,
) -> dict:  # type: ignore[type-arg]
    """One operation read that waits out the post-202 commit window
    (see ``wait_operation`` for the race this tolerates)."""

    import time

    deadline = time.monotonic() + timeout_s
    while True:
        response = e7_api.get(f"/v1/data/operations/{operation_id}", headers=headers)
        if response.status_code == 200:
            return response.json()
        if response.status_code != 404:
            response.raise_for_status()
        if time.monotonic() >= deadline:
            pytest.fail(f"operation {operation_id} stayed unreadable: {response.status_code}")
        time.sleep(0.25)


def write_evidence(case_id: str, name: str, payload: dict) -> Path:  # type: ignore[type-arg]
    """Persist one evidence file under output/e7/<round>/<case>/ (gitignored;
    raw evidence stays local, sanitized summaries go to the task doc)."""

    import json

    round_id = os.environ.get("AGENTHU_E7_ROUND", "smoke")
    directory = Path("output/e7") / round_id / case_id
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def verify_report(e7_verifier: E7Verifier, case_id: str) -> VerifyReport:
    report = e7_verifier.case(case_id)
    if not report.ok:
        failures = [check for check in report.checks if not check.passed]
        lines = "\n".join(
            f"  {check.name}: expected={check.expected!r} actual={check.actual!r}"
            for check in failures
        )
        pytest.fail("E7 verify failed:\n" + lines)
    return report
