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
    set is an honest failure, never a silent pass."""

    import time

    deadline = time.monotonic() + timeout_s
    terminal = {"COMPLETED", "READY", "FAILED", "EXPIRED", "CANCELLED"}
    payload: dict = {}
    while time.monotonic() < deadline:
        response = e7_api.get(f"/v1/data/operations/{operation_id}", headers=headers)
        response.raise_for_status()
        payload = response.json()
        if payload["status"] in terminal:
            if payload["status"] not in success_states:
                pytest.fail(f"operation {operation_id} settled as {payload['status']}: {payload}")
            return payload
        time.sleep(0.5)
    pytest.fail(f"operation {operation_id} did not settle within {timeout_s}s")
    raise AssertionError("unreachable")


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
