"""E7 verification pack: registry-driven counts, marker scans and probes.

Every check compares **actual** stack state against the committed manifest
(``tests/e7/manifest.json``). Expectations are never re-derived at run
time: a registry family without a mapping here is a hard failure, so the
pack must grow with the registry (m5-e7-acceptance §3 "owner限制先于内容
查找" and the fail-closed registry discipline).

Usage::

    python -m tests.e7.verify --baseline
    python -m tests.e7.verify --case E7-3a --report output/e7/r1/E7-3a/verify.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import redis as redis_lib
from sqlalchemy import create_engine, text

from backend.services.data_registry import REGISTRY, Store
from tests.e7.manifest import MANIFEST_PATH
from tests.e7.seed_spec import (
    EXPORT_STAGING_PREFIX,
    CaseExpectation,
    ObjectExpectation,
    build_world,
    stable_id,
    synthetic_vector,
)

# Owner predicate per registry POSTGRES family. ``:uid``/``:handle`` are
# bound per user; ``TRUE`` marks owner-less OPS rows (counted globally,
# owner-resolvable through file_objects per the registry note).
FAMILY_OWNER_SQL: dict[str, str] = {
    "users": "id = :uid",
    "events": "user_id = :uid",
    "tasks": "user_id = :uid",
    "task_events": "task_id IN (SELECT id FROM tasks WHERE user_id = :uid)",
    "goals": "user_id = :uid",
    "focus_sessions": "user_id = :uid",
    "plans": "user_id = :uid",
    "plan_items": "plan_id IN (SELECT id FROM plans WHERE user_id = :uid)",
    "current_states": "user_id = :uid",
    "memories": "user_id = :uid",
    "file_objects": "user_id = :uid",
    "material_chunks": "user_id = :uid",
    "material_answers": "user_id = :uid",
    "grounding_consents": "user_id = :uid",
    "model_context_consents": "user_id = :uid",
    "permission_grants": "user_id = :uid",
    "notification_preferences": "user_id = :uid",
    "chat_sessions": "user_id = :uid",
    "chat_messages": "user_id = :uid",
    "agent_runs": "user_id = :uid",
    "pending_actions": "user_id = :uid",
    "pending_action_mutations": "user_id = :uid",
    "audit_logs": "user_id = :uid",
    "data_operations": "owner_handle = :handle",
    "data_cleanup_items": "owner_handle = :handle",
    "data_barriers": "owner_handle = :handle",
    "data_previews": "user_id = :uid",
    "data_receipts": "owner_handle = :handle",
    "data_suppressions": "owner_handle = :handle",
    "storage_orphan_keys": "TRUE",
}

# Invariants the case drivers assert over HTTP (operation semantics, not
# end-state rows) — named here so the pre-registration lists them all.
DRIVER_INVARIANTS = frozenset(
    {
        "receipt_issued_once",
        "single_effective_worker_claim",
        "retry_ladder_bounded",
        "suppressed_reimport_rejected",
        "release_reopens_anchor",
        "grant_revocation_blocks_send",
        "invalid_basis_no_original_text",
        "export_manifest_counts_match_seed",
    }
)

# Invariants that need a P0-5/P0-6 surface; never silently green.
BLOCKED_INVARIANTS = frozenset(
    {
        "shared_rate_limit_not_doubled",
        "trace_linkage",
        "no_markers_in_telemetry",
        "restore_replays_suppression",
        "rpo_rto_measured",
        "old_key_rejected_new_key_works",
        "license_cleared",
    }
)

_LIVE_MEMORY_PREDICATE = (
    "supersedes_id IS NULL AND valid_to IS NULL AND (valid_from IS NULL OR valid_from <= now())"
)

_DIRTY_SET = "agenthu:trigger:dirty"


@dataclass
class CheckResult:
    name: str
    expected: Any
    actual: Any
    passed: bool
    note: str = ""


@dataclass
class VerifyReport:
    mode: str
    case_id: str | None
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(check.passed for check in self.checks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "case_id": self.case_id,
            "ok": self.ok,
            "checks": [
                {
                    "name": check.name,
                    "expected": check.expected,
                    "actual": check.actual,
                    "passed": check.passed,
                    "note": check.note,
                }
                for check in self.checks
            ],
        }


class _ObjectClient:
    """Minimal boto3 wrapper for head/list (independent of the adapter —
    evidence tooling must not share the code path it is auditing)."""

    def __init__(self) -> None:
        import boto3

        self.bucket = os.environ["S3_BUCKET"]
        self.client = boto3.client(
            "s3",
            endpoint_url=os.environ["S3_ENDPOINT_URL"],
            aws_access_key_id=os.environ["S3_ACCESS_KEY"],
            aws_secret_access_key=os.environ["S3_SECRET_KEY"],
            region_name=os.environ.get("S3_REGION", "us-east-1"),
        )

    def head_ok(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
        except Exception:
            return False
        return True

    def list_prefix(self, prefix: str) -> list[str]:
        response = self.client.list_objects_v2(Bucket=self.bucket, Prefix=prefix)
        return [str(item["Key"]) for item in response.get("Contents", [])]


_OBJECT_CLIENT: _ObjectClient | None = None


def _object_client() -> _ObjectClient:
    global _OBJECT_CLIENT
    if _OBJECT_CLIENT is None:
        _OBJECT_CLIENT = _ObjectClient()
    return _OBJECT_CLIENT


class E7Verifier:
    def __init__(self, engine: Any, manifest: dict[str, Any]) -> None:
        self.engine = engine
        self.manifest = manifest
        registered = {
            entry.key
            for entry in REGISTRY
            if entry.store == Store.POSTGRES and entry.table is not None
        }
        unmapped = sorted(registered - set(FAMILY_OWNER_SQL))
        if unmapped:
            raise RuntimeError(
                "registry families without a verify mapping (the pack must "
                f"cover every registered family): {unmapped}"
            )
        self._world = build_world()

    # -- primitives --------------------------------------------------------

    def _uid(self, tag: str) -> str:
        users = self.manifest["users"]
        assert isinstance(users, dict)
        return str(users[tag]["user_id"])

    def _handle(self, tag: str) -> str:
        return self._world.users[tag].owner_handle

    def _count(self, table: str, owner_pred: str, params: dict[str, Any]) -> int:
        stmt = text(f"SELECT count(*) FROM {table} WHERE {owner_pred}")
        with self.engine.connect() as conn:
            value = conn.execute(stmt, params).scalar_one()
        return int(value)

    def _scan_token_anywhere(self, token: str) -> list[str]:
        """Whole-row text scan for a content token across every family,
        with NO owner predicate — content must be gone everywhere."""

        hits: list[str] = []
        with self.engine.connect() as conn:
            for table in sorted(FAMILY_OWNER_SQL):
                stmt = text(f"SELECT count(*) FROM {table} WHERE {table}::text ILIKE :pattern")
                count = int(conn.execute(stmt, {"pattern": f"%{token}%"}).scalar_one())
                if count:
                    hits.append(f"{table}:{count}")
        return hits

    def _scan_token_outside(self, tag: str, prefix: str) -> list[str]:
        """Rows containing ``prefix`` (e.g. U markers) in tables NOT owned
        by ``tag`` — baseline owner isolation."""

        hits: list[str] = []
        uid, handle = self._uid(tag), self._handle(tag)
        with self.engine.connect() as conn:
            for table, pred in sorted(FAMILY_OWNER_SQL.items()):
                if pred == "TRUE":
                    continue  # owner-less OPS rows have no "outside"
                stmt = text(
                    f"SELECT count(*) FROM {table} WHERE NOT ({pred}) "
                    f"AND {table}::text ILIKE :pattern"
                )
                params: dict[str, Any] = {"uid": uid, "handle": handle, "pattern": f"%{prefix}%"}
                count = int(conn.execute(stmt, params).scalar_one())
                if count:
                    hits.append(f"{table}:{count}")
        return hits

    def _vector_topk_ids(self, name: str, limit: int = 10) -> list[str]:
        """Top-``limit`` nearest ids in the probe's OWN family (the probe
        name prefix picks the table: m* -> memories, c* -> chunks)."""

        tag, row_name = name.split(":", 1)
        table = "material_chunks" if row_name.startswith("c") else "memories"
        stmt = text(
            f"SELECT id FROM {table} WHERE user_id = :uid "
            "AND embedding IS NOT NULL ORDER BY embedding <=> CAST(:q AS vector) LIMIT :k"
        )
        with self.engine.connect() as conn:
            rows = conn.execute(
                stmt, {"uid": self._uid(tag), "q": json.dumps(synthetic_vector(name)), "k": limit}
            ).fetchall()
        return [str(row_id) for (row_id,) in rows]

    def _probe_is_nearest(self, name: str) -> bool:
        """Baseline sanity: the probe vector's nearest row is itself."""

        tag, row_name = name.split(":", 1)
        target = str(stable_id("row", tag, row_name))
        top = self._vector_topk_ids(name, limit=1)
        return bool(top) and top[0] == target

    def _probe_recallable(self, name: str, limit: int = 10) -> bool:
        """Absence check: the probe id must never appear among the top-K
        nearest rows (m5-e7-acceptance §3 vector query check)."""

        tag, row_name = name.split(":", 1)
        target = str(stable_id("row", tag, row_name))
        return target in self._vector_topk_ids(name, limit=limit)

    def _live_key_count(self, tag: str, subject_key: str) -> int:
        stmt = text(
            "SELECT count(*) FROM memories WHERE user_id = :uid "
            "AND subject_key = :key AND " + _LIVE_MEMORY_PREDICATE
        )
        with self.engine.connect() as conn:
            return int(conn.execute(stmt, {"uid": self._uid(tag), "key": subject_key}).scalar_one())

    def _dirty_member(self, tag: str) -> bool:
        client = redis_lib.Redis.from_url(
            os.environ["E7_REDIS_URL"], decode_responses=True, socket_timeout=5
        )
        return bool(client.sismember(_DIRTY_SET, self._uid(tag)))

    # -- baseline ----------------------------------------------------------

    def baseline(self) -> VerifyReport:
        report = VerifyReport(mode="baseline", case_id=None)
        before = self.manifest["before_counts"]
        assert isinstance(before, dict)
        for tag in ("U", "V"):
            uid, handle = self._uid(tag), self._handle(tag)
            for table, expected in sorted(before[tag].items()):
                actual = self._count(table, FAMILY_OWNER_SQL[table], {"uid": uid, "handle": handle})
                report.checks.append(
                    CheckResult(
                        name=f"before:{tag}:{table}",
                        expected=expected,
                        actual=actual,
                        passed=actual == expected,
                    )
                )
        for tag in ("U", "V"):
            hits = self._scan_token_outside(tag, f"E7MARK-{tag}-")
            report.checks.append(
                CheckResult(
                    name=f"baseline:E7MARK-{tag}-* outside {tag}",
                    expected=[],
                    actual=hits,
                    passed=not hits,
                )
            )
        for name in sorted(self._world.vector_names):
            nearest = self._probe_is_nearest(name)
            report.checks.append(
                CheckResult(
                    name=f"baseline:vector:{name}",
                    expected="probe row is its own nearest",
                    actual="nearest" if nearest else "not nearest",
                    passed=nearest,
                )
            )
        for name, key in sorted(self._world.blob_names.items()):
            exists = _object_client().head_ok(key)
            report.checks.append(
                CheckResult(
                    name=f"baseline:blob:{name}",
                    expected=key,
                    actual="present" if exists else "missing",
                    passed=exists,
                )
            )
        for tag in ("U", "V"):
            member = self._dirty_member(tag)
            report.checks.append(
                CheckResult(
                    name=f"baseline:redis:dirty:{tag}",
                    # The seed deliberately does not mark users dirty: a
                    # member here means the worker cron created work on its
                    # own, which would make counts non-deterministic.
                    expected=False,
                    actual=member,
                    passed=not member,
                )
            )
        return report

    # -- per-case ----------------------------------------------------------

    def case(self, case_id: str) -> VerifyReport:
        expectations = self.manifest["case_expectations"]
        assert isinstance(expectations, dict)
        if case_id not in expectations:
            raise RuntimeError(f"case {case_id} is not pre-registered in the manifest")
        raw = expectations[case_id]
        assert isinstance(raw, dict)
        if raw.get("blocked_by"):
            raise RuntimeError(f"case {case_id} is blocked by {raw['blocked_by']}")
        expectation = CaseExpectation(
            object_expectations=tuple(
                ObjectExpectation(**obj) for obj in raw.pop("object_expectations")
            ),
            **raw,
        )
        report = VerifyReport(mode="case", case_id=case_id)
        before = self.manifest["before_counts"]
        assert isinstance(before, dict)

        for tag in ("U", "V"):
            uid, handle = self._uid(tag), self._handle(tag)
            deltas = expectation.count_deltas.get(tag, {})
            minimums = expectation.count_minimums.get(tag, {})
            exact_tables = set(before[tag]) | set(deltas)
            # Lifecycle families under minimum semantics are excluded from
            # the exact sweep: their row counts track executor phase fan-out
            # (see CaseExpectation.count_minimums).
            lifecycle = {
                "data_operations",
                "data_previews",
                "data_barriers",
                "data_suppressions",
                "data_cleanup_items",
                "data_receipts",
            }
            for table in sorted(exact_tables - (lifecycle if minimums else set())):
                expected = before[tag][table] + deltas.get(table, 0)
                actual = self._count(table, FAMILY_OWNER_SQL[table], {"uid": uid, "handle": handle})
                report.checks.append(
                    CheckResult(
                        name=f"count:{tag}:{table}",
                        expected=expected,
                        actual=actual,
                        passed=actual == expected,
                    )
                )
            for table, minimum in sorted(minimums.items()):
                actual = self._count(table, FAMILY_OWNER_SQL[table], {"uid": uid, "handle": handle})
                report.checks.append(
                    CheckResult(
                        name=f"count_min:{tag}:{table}",
                        expected=f">= {minimum}",
                        actual=actual,
                        passed=actual >= minimum,
                        note="lifecycle ledger presence (durable, not lost)",
                    )
                )

        absent_tokens = [self._world.marker_names["U"][name] for name in expectation.marker_absence]
        for tag in expectation.all_markers_absent_for:
            absent_tokens.extend(self._world.marker_names[tag].values())
        for token in absent_tokens:
            hits = self._scan_token_anywhere(token)
            report.checks.append(
                CheckResult(
                    name=f"marker_absence:{token}",
                    expected=[],
                    actual=hits,
                    passed=not hits,
                )
            )

        for name in expectation.vector_absence:
            recallable = self._probe_recallable(name)
            report.checks.append(
                CheckResult(
                    name=f"vector_absence:{name}",
                    expected="probe row not recallable",
                    actual="recallable" if recallable else "not recallable",
                    passed=not recallable,
                )
            )
        for name in expectation.live_key_absence:
            tag, key = name.split(":", 1)
            actual = self._live_key_count(tag, key)
            report.checks.append(
                CheckResult(
                    name=f"live_key_absence:{name}",
                    expected=0,
                    actual=actual,
                    passed=actual == 0,
                )
            )

        for obj in expectation.object_expectations:
            for blob_name in obj.absent_seeded:
                key = self._world.blob_names[blob_name]
                exists = _object_client().head_ok(key)
                report.checks.append(
                    CheckResult(
                        name=f"object_absent:{blob_name}",
                        expected=False,
                        actual=exists,
                        passed=not exists,
                    )
                )
            if obj.exports_exact is not None or obj.exports_min:
                keys = _object_client().list_prefix(
                    f"{EXPORT_STAGING_PREFIX}{self._handle(obj.user)}/"
                )
                if obj.exports_exact is not None:
                    report.checks.append(
                        CheckResult(
                            name=f"exports_exact:{obj.user}",
                            expected=obj.exports_exact,
                            actual=len(keys),
                            passed=len(keys) == obj.exports_exact,
                        )
                    )
                else:
                    report.checks.append(
                        CheckResult(
                            name=f"exports_min:{obj.user}",
                            expected=f">= {obj.exports_min}",
                            actual=len(keys),
                            passed=len(keys) >= obj.exports_min,
                        )
                    )

        for name in expectation.redis_absence:
            tag, _kind = name.split(":", 1)
            member = self._dirty_member(tag)
            report.checks.append(
                CheckResult(
                    name=f"redis_absence:{name}",
                    expected=False,
                    actual=member,
                    passed=not member,
                )
            )

        for invariant in expectation.invariants:
            report.checks.extend(self._invariant(invariant))

        return report

    def _invariant(self, name: str) -> list[CheckResult]:
        if name == "cleanup_ledger_drained":
            outstanding = 0
            with self.engine.connect() as conn:
                for tag in ("U", "V"):
                    row = conn.execute(
                        text(
                            "SELECT count(*) FROM data_cleanup_items "
                            "WHERE owner_handle = :handle AND state IN ('PENDING','CLAIMED')"
                        ),
                        {"handle": self._handle(tag)},
                    ).scalar_one()
                    outstanding += int(row)
            return [
                CheckResult(
                    name="invariant:cleanup_ledger_drained",
                    expected=0,
                    actual=outstanding,
                    passed=outstanding == 0,
                )
            ]
        if name == "account_audit_scrubbed":
            # Content scrubbing is proven by the all-markers-absent scan;
            # retention is at-least-before (other users' rows also live here).
            with self.engine.connect() as conn:
                total = int(conn.execute(text("SELECT count(*) FROM audit_logs")).scalar_one())
            before = self.manifest["before_counts"]
            assert isinstance(before, dict)
            expected_min = int(before["U"]["audit_logs"]) + int(before["V"]["audit_logs"])
            return [
                CheckResult(
                    name="invariant:account_audit_scrubbed",
                    expected=f">= {expected_min}",
                    actual=total,
                    passed=total >= expected_min,
                )
            ]
        if name in DRIVER_INVARIANTS:
            return [
                CheckResult(
                    name=f"invariant:{name}",
                    expected="driver-asserted",
                    actual="driver-asserted",
                    passed=True,
                    note="protocol invariant asserted by the case driver over HTTP",
                )
            ]
        if name in BLOCKED_INVARIANTS:
            return [
                CheckResult(
                    name=f"invariant:{name}",
                    expected="blocked",
                    actual="blocked",
                    passed=False,
                    note="requires a P0-5/P0-6 surface; never green in prep",
                )
            ]
        raise RuntimeError(f"unknown invariant {name!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--baseline", action="store_true")
    group.add_argument("--case", metavar="CASE_ID")
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args(argv)

    for env in (
        "E7_DATABASE_URL",
        "E7_REDIS_URL",
        "S3_ENDPOINT_URL",
        "S3_ACCESS_KEY",
        "S3_SECRET_KEY",
        "S3_BUCKET",
    ):
        if not os.environ.get(env):
            print(f"missing required env {env} (see tests/e7/README.md)", file=sys.stderr)
            return 2

    engine = create_engine(os.environ["E7_DATABASE_URL"])
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    verifier = E7Verifier(engine, manifest)
    report = verifier.baseline() if args.baseline else verifier.case(args.case)  # type: ignore[arg-type]

    rendered = json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + "\n", encoding="utf-8")
    for check in report.checks:
        flag = "PASS" if check.passed else "FAIL"
        print(f"[{flag}] {check.name}: expected={check.expected!r} actual={check.actual!r}")
    print(f"{'OK' if report.ok else 'FAILED'}: {report.mode} {report.case_id or ''}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
