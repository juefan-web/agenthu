"""E7-9 driver: the multi-process evidence stack — shared rate-limit ledger,
cross-process trace linkage, telemetry leak scan (m5-e7-acceptance §2 E7-9).

Stack shape (``docker-compose.multi.yml``, project ``agenthu-multi``): two
API processes on 127.0.0.1:8100/8101, two arq workers, one OTel Collector
(debug exporter, detailed — span name/trace id readable straight from
``docker logs``), all against one shared db/redis/s3mock with no host port
bindings. The port face is the frozen resolution of the 8000 conflict: the
developer's llm_gateway holds 8000 inside WSL (red line, never touched), so
the compose override publishes the evidence APIs on 8100-8101 — the
port-override path, not a gateway change.

The case brings the stack up itself (idempotent compose reconcile with
``AUTH_RATE_LIMIT_MAX=6`` in the interpolation env) and seeds the SAME E7
world into the multi db from inside the network — the evidence image bakes
``tests/`` and the worker's dev bind-mount is overridden away, so the stack
runs committed code. If the stack cannot come up the case FAILS loudly:
after two rounds of hunting silent skips, a third one here is not an option.

Deterministic ordering: every traffic face runs while the stack is healthy;
the redis-outage face runs last (it stops the shared redis, taking the
workers' queue with it). The rate-limit hammer alternates the two API ports
after resetting the ``rl:*`` ledger — a per-process bucket would have
allowed ~2xMAX across the two ports; only the shared Redis ledger produces
the exact single-MAX boundary asserted here. The leak scan re-reads ALL
container logs at the end (including the outage phase's error output) and
the audit table; evidence files carry counts only, never the scanned
values (E6/E7 desensitization discipline).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from tests.e7.conftest import login, write_evidence
from tests.e7.markers import marker_prefix
from tests.e7.seed_spec import World

PROJECT = "agenthu-multi"
API_A = "http://127.0.0.1:8100"
API_B = "http://127.0.0.1:8101"
AUTH_MAX = "6"  # interpolated into the api env at bring-up; read back live later
COMPOSE_FILES = ("-f", "docker-compose.yml", "-f", "docker-compose.multi.yml")

_SEED_ENV = {
    "E7_DATABASE_URL": "postgresql+psycopg://agenthu:agenthu@db:5432/agenthu",
    "E7_REDIS_URL": "redis://redis:6379/0",
    "S3_ENDPOINT_URL": "http://s3mock:9090",
    "S3_ACCESS_KEY": "agenthu",
    "S3_SECRET_KEY": "agenthu123",
    "S3_BUCKET": "agenthu-e7",
    "S3_REGION": "us-east-1",
}


def _fail_output(proc: subprocess.CompletedProcess[str], action: str) -> None:
    pytest.fail(
        f"multi-stack {action} failed (rc={proc.returncode}):\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )


def _cli_env() -> dict[str, str]:
    """Interpolation env for the docker CLI: host E7_* / S3_* values (the
    single-stack conventions, e.g. S3_ENDPOINT_URL=127.0.0.1:9090) must NOT
    leak into compose interpolation — inside the multi network those
    endpoints resolve differently and readiness fails on them."""

    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("E7_", "S3_", "AGENTHU_"))
    }
    env["AUTH_RATE_LIMIT_MAX"] = AUTH_MAX
    return env


def _compose(*args: str, timeout: float = 900.0) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["docker", "compose", "-p", PROJECT, *COMPOSE_FILES, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=_cli_env(),
    )
    return proc


def _exec(service: str, env: dict[str, str], *cmd: str) -> subprocess.CompletedProcess[str]:
    argv = ["docker", "compose", "-p", PROJECT, *COMPOSE_FILES, "exec", "-T"]
    for key, value in env.items():
        argv += ["-e", f"{key}={value}"]
    argv += [service, *cmd]
    return subprocess.run(argv, capture_output=True, text=True, timeout=300.0, env=_cli_env())


def _container_logs(container: str, since: str) -> str:
    proc = subprocess.run(
        ["docker", "logs", container, "--since", since],
        capture_output=True,
        text=True,
        timeout=60.0,
    )
    return proc.stdout + proc.stderr


def _ps_states() -> dict[str, list[str]]:
    proc = _compose("ps", "--all", "--format", "json", timeout=60.0)
    if proc.returncode != 0:
        _fail_output(proc, "ps")
    raw = proc.stdout.strip()
    entries: list[dict[str, Any]] = []
    if raw.startswith("["):
        entries = json.loads(raw)
    else:  # older compose emits line-delimited objects
        entries = [json.loads(line) for line in raw.splitlines() if line.strip()]
    states: dict[str, list[str]] = {}
    for entry in entries:
        states.setdefault(str(entry.get("Service", "?")), []).append(str(entry.get("State", "?")))
    return states


def _effective_auth_max() -> int:
    proc = _exec(
        "api",
        {},
        "python",
        "-c",
        "from backend.config import get_settings; print(get_settings().auth_rate_limit_max)",
    )
    if proc.returncode != 0:
        _fail_output(proc, "read auth_rate_limit_max")
    return int(proc.stdout.strip())


def _reset_rate_ledger() -> None:
    proc = _exec("redis", {}, "redis-cli", "--scan", "--pattern", "rl:*")
    if proc.returncode != 0:
        _fail_output(proc, "scan rl:*")
    keys = proc.stdout.split()
    if keys:
        proc = _exec("redis", {}, "redis-cli", "DEL", *keys)
        if proc.returncode != 0:
            _fail_output(proc, "del rl:*")


def _audit_counts(since: str, needles: tuple[str, ...]) -> dict[str, int]:
    """Runtime-written audit rows only (created_at > bring-up): the seeded
    audit fixtures carry markers BY DESIGN (they are the deletion cases'
    content rows — E7-5 counts them), so the leak face for E7-9 is the rows
    THIS case's traffic wrote. The non-needle total proves the scan is not
    vacuously green."""

    counts: dict[str, int] = {}
    statements = {
        "runtime_rows_total": f"SELECT count(*) FROM audit_logs WHERE created_at > '{since}'",
    }
    for needle in needles:
        assert "'" not in needle and "%" not in needle and "_" not in needle, "unsafe scan needle"
        statements[needle_alias(needle)] = (
            "SELECT count(*) FROM audit_logs "
            f"WHERE created_at > '{since}' "
            f"AND row_to_json(audit_logs.*)::text LIKE '%{needle}%'"
        )
    for name, statement in statements.items():
        proc = _exec(
            "db", {}, "psql", "-U", "agenthu", "-d", "agenthu", "-t", "-A", "-c", statement
        )
        if proc.returncode != 0:
            _fail_output(proc, "audit scan")
        counts[name] = int(proc.stdout.strip() or 0)
    return counts


def needle_alias(needle: str) -> str:
    """Stable alias so evidence names never carry the scanned value."""

    if needle.startswith("E7MARK-"):
        return f"marker:{needle[:9]}"  # e.g. marker:E7MARK-U-
    return "credential:<redacted>"


@dataclass(frozen=True)
class _Span:
    trace_id: str
    span_id: str
    parent_id: str
    name: str


def _parse_spans(text: str) -> list[_Span]:
    """Parse the collector's debug-exporter blocks (detailed verbosity).

    Anchor each field at line start so ``ID`` never matches ``Parent ID``.
    """

    spans: list[_Span] = []
    for chunk in text.split("Span #")[1:]:
        trace = re.search(r"(?m)^\s*Trace ID\s*:\s*(.+)$", chunk)
        parent = re.search(r"(?m)^\s*Parent ID\s*:\s*(.*)$", chunk)
        span_id = re.search(r"(?m)^\s*ID\s*:\s*(.+)$", chunk)
        name = re.search(r"(?m)^\s*Name\s*:\s*(.*)$", chunk)
        if not (trace and span_id and name):
            continue
        spans.append(
            _Span(
                trace_id=trace.group(1).strip().replace(" ", ""),
                span_id=span_id.group(1).strip().replace(" ", ""),
                parent_id=(parent.group(1).strip().replace(" ", "") if parent else ""),
                name=name.group(1).strip(),
            )
        )
    return spans


def _wait_for_spans(since: str, predicate, budget_s: float = 45.0) -> list[_Span]:  # type: ignore[no-untyped-def]
    """Poll collector logs until the predicate holds (BatchSpanProcessor
    flushes on its own schedule — seconds, not immediate)."""

    deadline = time.monotonic() + budget_s
    spans: list[_Span] = []
    while time.monotonic() < deadline:
        spans = _parse_spans(_container_logs(f"{PROJECT}-otel-collector-1", since))
        if predicate(spans):
            return spans
        time.sleep(2.0)
    return spans  # caller asserts on the last read


@pytest.fixture()
def multi_stack(e7_world: World) -> str:
    """Bring the multi stack up, seed it, reset the rate ledger; yield the
    ``docker logs --since`` anchor (RFC3339) that bounds every later read."""

    proc = _compose(
        "up",
        "-d",
        "--build",  # bake the current tree (layer-cached when unchanged);
        # the worker/api bind mounts are gone, so a stale image would run
        # stale seed/drivers — the one case-bring-up where rebuild is free.
        "--wait",
        "--scale",
        "api=2",
        "--scale",
        "worker=2",
        "migrate",
        "db",
        "redis",
        "s3mock",
        "otel-collector",
        "api",
        "worker",
    )
    if proc.returncode != 0:
        _fail_output(proc, "up --wait")

    # The multi s3mock auto-creates bucket `agenthu` only; the E7 seed
    # purges/loads `agenthu-e7`, which must exist first (README §1 parity).
    proc = _exec(
        "api",
        {},
        "python",
        "-c",
        "import boto3\n"
        "from botocore.exceptions import ClientError\n"
        "c = boto3.client('s3', endpoint_url='http://s3mock:9090',"
        " aws_access_key_id='agenthu', aws_secret_access_key='agenthu123',"
        " region_name='us-east-1')\n"
        "try:\n"
        "    c.head_bucket(Bucket='agenthu-e7')\n"
        "except ClientError:\n"
        "    c.create_bucket(Bucket='agenthu-e7')\n",
    )
    if proc.returncode != 0:
        _fail_output(proc, "ensure bucket")

    proc = _exec("api", _SEED_ENV, "python", "-m", "tests.e7.seed")
    if proc.returncode != 0:
        _fail_output(proc, "seed")
    _reset_rate_ledger()
    return datetime.now(UTC).isoformat()


def test_e7_9_shared_multiprocess_observability(multi_stack: str, e7_world: World) -> None:
    since = multi_stack
    world = e7_world

    with (
        httpx.Client(base_url=API_A, timeout=30.0) as api_a,
        httpx.Client(base_url=API_B, timeout=30.0) as api_b,
    ):
        # --- topology: 2 API + 2 worker processes, both ports serving ------
        states = _ps_states()
        assert states.get("api", []).count("running") == 2, states
        assert states.get("worker", []).count("running") == 2, states
        assert states.get("otel-collector", []).count("running") == 1, states
        for client in (api_a, api_b):
            liveness = client.get("/health")
            assert liveness.status_code == 200, liveness.text
            readiness = client.get("/health/ready")
            assert readiness.status_code == 200, readiness.text
        write_evidence(
            "E7-9",
            "topology.json",
            {
                "project": PROJECT,
                "api_running": states.get("api", []).count("running"),
                "worker_running": states.get("worker", []).count("running"),
                "collector_running": states.get("otel-collector", []).count("running"),
                "api_ports": ["8100", "8101"],
                "health": {"A": 200, "B": 200},
                "ready": {"A": 200, "B": 200},
            },
        )

        # --- trace face 1: HTTP -> worker (ping liveness job) --------------
        headers_u = login(api_a, world, "U")
        accepted = api_a.post("/v1/jobs/ping", headers=headers_u)
        assert accepted.status_code == 202, accepted.text
        job_id = accepted.json()["job_id"]
        deadline = time.monotonic() + 60.0
        job_status = ""
        while time.monotonic() < deadline:
            job_status = api_a.get(f"/v1/jobs/{job_id}", headers=headers_u).json()["status"]
            if job_status == "complete":
                break
            time.sleep(0.5)
        assert job_status == "complete", f"ping job settled as {job_status!r}"

        # --- trace face 2: HTTP -> worker -> provider (chat full chain) ----
        # The message body carries a FRESH marker token: the seeded markers
        # prove stored content stays put, this one probes user-supplied
        # content in flight through api, worker and the provider call.
        probe_token = f"{marker_prefix('U')}901"
        session_id = world.ids["U:s1"]
        baseline = api_a.get(f"/v1/chat/sessions/{session_id}/messages", headers=headers_u)
        assert baseline.status_code == 200, baseline.text
        pre_count = len(baseline.json().get("items", []))

        sent = api_a.post(
            f"/v1/chat/sessions/{session_id}/messages",
            json={
                "content": f"泄漏探针 {probe_token}：请总结当前会话要点。",
                "client_message_id": "e7-9-probe-1",
            },
            headers=headers_u,
        )
        assert sent.status_code == 202, sent.text
        deadline = time.monotonic() + 90.0
        items: list[dict[str, Any]] = []
        while time.monotonic() < deadline:
            page = api_a.get(f"/v1/chat/sessions/{session_id}/messages", headers=headers_u)
            if page.status_code == 200:
                items = page.json().get("items", [])
                if len(items) >= pre_count + 2 and items[-1].get("role") == "assistant":
                    break
            time.sleep(1.0)
        assert len(items) >= pre_count + 2 and items[-1].get("role") == "assistant", (
            "assistant message never landed"
        )

        # --- trace linkage: one trace id across the hop chain --------------
        def spans_ready(spans: list[_Span]) -> bool:
            chat_traces = {s.trace_id for s in spans if s.name.endswith("/messages")}
            worker_traces = {s.trace_id for s in spans if s.name == "worker.execute_agent_run"}
            provider_traces = {s.trace_id for s in spans if s.name == "POST"}
            ping_traces = {s.trace_id for s in spans if s.name.endswith("/ping")}
            ping_worker = {s.trace_id for s in spans if s.name == "worker.ping"}
            return bool(chat_traces & worker_traces & provider_traces and ping_traces & ping_worker)

        spans = _wait_for_spans(since, spans_ready)
        chat_traces = {s.trace_id for s in spans if s.name.endswith("/messages")}
        worker_traces = {s.trace_id for s in spans if s.name == "worker.execute_agent_run"}
        # The provider client span is named exactly "POST" (method-only, the
        # current httpx instrumentation convention; URL never enters the span
        # name OR attributes — that is the allowlist doing its job). Within
        # the chat trace the worker's only outbound POST is the provider call.
        provider_traces = {s.trace_id for s in spans if s.name == "POST"}
        linked = chat_traces & worker_traces & provider_traces
        assert linked, "no trace id spans http server, worker job and provider call"
        chat_trace = sorted(linked)[0]
        trace_span_ids = {s.span_id for s in spans if s.trace_id == chat_trace}
        worker_span = next(
            s for s in spans if s.trace_id == chat_trace and s.name == "worker.execute_agent_run"
        )
        assert worker_span.parent_id in trace_span_ids, (
            "worker span parent does not resolve in-trace"
        )
        ping_traces = {s.trace_id for s in spans if s.name.endswith("/ping")}
        ping_worker = {s.trace_id for s in spans if s.name == "worker.ping"}
        assert ping_traces & ping_worker, "no trace id spans the ping http+worker pair"
        provider_names = sorted(
            {s.name for s in spans if s.trace_id == chat_trace and s.name == "POST"}
        )
        write_evidence(
            "E7-9",
            "traces.json",
            {
                "chat_trace_id": chat_trace,
                "chat_trace_spans": sorted(s.name for s in spans if s.trace_id == chat_trace),
                "worker_parent_resolves_in_trace": True,
                "ping_trace_linked": True,
                "provider_span_names": provider_names,
                "total_spans_since_bringup": len(spans),
            },
        )

        # --- rate limit: shared ledger, exact single-MAX boundary ----------
        # A fresh ledger reset removes the sliding-window uncertainty (the
        # earlier faces happened up to minutes ago): the budget below is
        # consumed by the hammer alone, inside a few seconds of window.
        _reset_rate_ledger()
        auth_max = _effective_auth_max()
        allowed = {"A": 0, "B": 0}
        rejected = {"A": 0, "B": 0}
        retry_after_ok = True
        for i in range(auth_max * 2):
            tag, client = ("A", api_a) if i % 2 == 0 else ("B", api_b)
            resp = client.post(
                "/v1/auth/login",
                json={"email": world.users["U"].email, "password": "wrong-password"},
            )
            if resp.status_code == 429:
                rejected[tag] += 1
                header = resp.headers.get("Retry-After")
                retry_after_ok = (
                    retry_after_ok and header is not None and header.isdigit() and int(header) >= 1
                )
            elif resp.status_code == 401:
                allowed[tag] += 1
            else:
                pytest.fail(f"unexpected login status {resp.status_code}: {resp.text}")
        assert allowed["A"] + allowed["B"] == auth_max, (
            f"shared budget not respected: allowed {allowed} vs max {auth_max}"
        )
        assert rejected["A"] >= 1 and rejected["B"] >= 1, rejected
        assert allowed["A"] >= 1 and allowed["B"] >= 1, allowed
        assert retry_after_ok
        write_evidence(
            "E7-9",
            "rate-limit.json",
            {
                "auth_rate_limit_max": auth_max,
                "allowed": allowed,
                "rejected": rejected,
                "retry_after_header_ok": True,
                "hammer_total": auth_max * 2,
            },
        )

        # --- redis outage face (frozen policy): fail closed, then recover --
        # Last traffic face by design: stopping the shared redis takes the
        # workers' queue with it (arq workers exit without a restart policy),
        # and nothing after this point needs a worker.
        stop = _compose("stop", "redis", timeout=60.0)
        if stop.returncode != 0:
            _fail_output(stop, "stop redis")
        outage: dict[str, dict[str, int]] = {}
        for tag, client in (("A", api_a), ("B", api_b)):
            liveness = client.get("/health")
            refused = client.post(
                "/v1/auth/login",
                json={"email": world.users["U"].email, "password": "wrong-password"},
            )
            assert liveness.status_code == 200, "api process died with redis"
            assert refused.status_code == 503, (
                f"expected fail-closed 503 during redis outage, got {refused.status_code}"
            )
            assert "rate_limit_unavailable" in refused.text, refused.text
            outage[tag] = {"health": liveness.status_code, "login": refused.status_code}
        # Restart the shared plane and reconcile the workers back to 2 (they
        # die with redis; the stack must end in its declared shape for the
        # B-side probe), then prove the limiter serves again.
        start = _compose("up", "-d", "--wait", "redis", "worker", timeout=180.0)
        if start.returncode != 0:
            _fail_output(start, "restart redis+worker")
        recovered: dict[str, int] = {}
        for tag, client in (("A", api_a), ("B", api_b)):
            resp = client.post(
                "/v1/auth/login",
                json={"email": world.users["U"].email, "password": "wrong-password"},
            )
            assert resp.status_code in (401, 429), (
                f"limiter not serving after redis restart: {resp.status_code}"
            )
            recovered[tag] = resp.status_code
        write_evidence(
            "E7-9",
            "redis-outage.json",
            {"during": outage, "restart_wait": "redis+worker healthy", "after": recovered},
        )

        # --- leak scan: telemetry faces + audit table, counts only --------
        faces = {
            "otel-collector": _container_logs(f"{PROJECT}-otel-collector-1", since),
            "api-1": _container_logs(f"{PROJECT}-api-1", since),
            "api-2": _container_logs(f"{PROJECT}-api-2", since),
            "worker-1": _container_logs(f"{PROJECT}-worker-1", since),
            "worker-2": _container_logs(f"{PROJECT}-worker-2", since),
        }
        needles = (
            marker_prefix("U"),
            marker_prefix("V"),
            world.users["U"].password,
            world.users["V"].password,
            probe_token,
        )
        scan: dict[str, dict[str, int]] = {}
        for face, text in faces.items():
            scan[face] = {needle_alias(n): text.count(n) for n in needles}
            hits = {k: v for k, v in scan[face].items() if v}
            assert not hits, f"leak scan hit in {face}: {list(hits)}"
        audit_counts = _audit_counts(
            since,
            (
                marker_prefix("U"),
                marker_prefix("V"),
                world.users["U"].password,
                world.users["V"].password,
            ),
        )
        runtime_rows = audit_counts.pop("runtime_rows_total")
        assert runtime_rows >= 1, "no runtime audit rows written — scan would be vacuous"
        assert not {k: v for k, v in audit_counts.items() if v}, audit_counts
        write_evidence(
            "E7-9",
            "leak-scan.json",
            {
                "faces_bytes": {face: len(text) for face, text in faces.items()},
                "faces_hits": scan,
                "audit_runtime_rows_total": runtime_rows,
                "audit_runtime_hits": audit_counts,
                "audit_seeded_rows_note": (
                    "seeded audit fixtures excluded by design (marker-bearing "
                    "content rows for the deletion cases); runtime face scanned "
                    "via created_at > bring-up"
                ),
                "needles": [needle_alias(n) for n in needles],
            },
        )

        # --- driver-side verify record (single-stack verifier has no
        # multi-stack surface; these three invariants are driver-asserted --
        # see verify.py DRIVER_INVARIANTS for the same-hunk registration) ---
        write_evidence(
            "E7-9",
            "verify.json",
            {
                "case_id": "E7-9",
                "checks": [
                    {
                        "name": "invariant:shared_rate_limit_not_doubled",
                        "expected": {"allowed_total": auth_max, "both_ports_429": True},
                        "actual": {
                            "allowed_total": allowed["A"] + allowed["B"],
                            "both_ports_429": rejected["A"] >= 1 and rejected["B"] >= 1,
                        },
                        "passed": True,
                    },
                    {
                        "name": "invariant:trace_linkage",
                        "expected": "one trace id over http+worker+provider, parent in-trace",
                        "actual": {"chat_trace_id": chat_trace, "spans": len(trace_span_ids)},
                        "passed": True,
                    },
                    {
                        "name": "invariant:no_markers_in_telemetry",
                        "expected": 0,
                        "actual": 0,
                        "passed": True,
                        "note": "collector+api+worker logs and audit table scanned; counts only",
                    },
                    {"name": "topology:api_processes", "expected": 2, "actual": 2, "passed": True},
                    {
                        "name": "topology:worker_processes",
                        "expected": 2,
                        "actual": 2,
                        "passed": True,
                    },
                    {
                        "name": "outage:fail_closed_503",
                        "expected": 503,
                        "actual": {tag: face["login"] for tag, face in outage.items()},
                        "passed": True,
                    },
                ],
            },
        )
