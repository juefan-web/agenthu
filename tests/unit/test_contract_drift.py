"""OpenAPI <-> client Zod contract drift tests.

These guard the frozen client contract (``packages/contracts``, see DECISIONS.md
D-009) so a Backend change cannot silently break the desktop client and a stale
``openapi.json`` cannot be merged.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from backend.main import app
from backend.scripts.check_contract_drift import (
    ZOD_TO_OPENAPI,
    check_client_alignment,
    compare_artifact,
    parse_zod_schemas,
    run,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "client_contract.ts"
OPENAPI = REPO_ROOT / "openapi.json"


def _fixture_source() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def test_committed_openapi_is_current() -> None:
    committed = json.loads(OPENAPI.read_text(encoding="utf-8"))
    assert compare_artifact(committed, app.openapi()) == []


def test_zod_parser_extracts_client_fields() -> None:
    schemas = parse_zod_schemas(_fixture_source())
    assert set(ZOD_TO_OPENAPI) <= set(schemas)
    assert set(schemas["TaskSchema"]) == {
        "id",
        "title",
        "due_at",
        "estimate_minutes",
        "status",
        "source_event_ids",
    }
    assert schemas["TaskSchema"]["due_at"].types == frozenset({"string", "null"})
    assert schemas["TaskSchema"]["estimate_minutes"].types == frozenset({"integer", "null"})
    assert schemas["TaskSchema"]["status"].types == frozenset({"string"})
    assert schemas["PlanSchema"]["items"].items is not None
    assert schemas["PlanSchema"]["items"].items.ref == "PlanItemSchema"


def test_openapi_matches_client_zod_contract() -> None:
    assert check_client_alignment(_fixture_source(), app.openapi()) == []


def test_drift_check_passes_end_to_end() -> None:
    report = run(
        openapi_path=OPENAPI,
        zod_sources=[FIXTURE],
        write=False,
        require_zod=True,
    )
    assert not report.has_drift, "\n".join(report.artifact + report.client)
    assert report.zod_sources == [str(FIXTURE)]


def test_alignment_detects_missing_client_field() -> None:
    broken = copy.deepcopy(app.openapi())
    del broken["components"]["schemas"]["ClientTask"]["properties"]["source_event_ids"]

    errors = check_client_alignment(_fixture_source(), broken)
    assert any("ClientTask.source_event_ids: missing from OpenAPI" in error for error in errors)


def test_alignment_detects_retyped_client_field() -> None:
    broken = copy.deepcopy(app.openapi())
    broken["components"]["schemas"]["ClientTask"]["properties"]["title"] = {"type": "integer"}

    errors = check_client_alignment(_fixture_source(), broken)
    assert any("ClientTask.title" in error for error in errors)


def test_alignment_detects_nested_client_field_drift() -> None:
    broken = copy.deepcopy(app.openapi())
    del broken["components"]["schemas"]["EventProvenance"]["properties"]["upstream_id"]

    errors = check_client_alignment(_fixture_source(), broken)
    assert any("EventEnvelope.provenance.upstream_id" in error for error in errors)


def test_artifact_comparison_detects_stale_openapi() -> None:
    stale = copy.deepcopy(app.openapi())
    del stale["paths"]["/v1/tasks"]

    messages = compare_artifact(stale, app.openapi())
    assert messages
    assert any("/v1/tasks" in message for message in messages)


def test_write_refreshes_artifact(tmp_path: Path) -> None:
    target = tmp_path / "openapi.json"
    report = run(
        openapi_path=target,
        zod_sources=[FIXTURE],
        write=True,
        require_zod=True,
    )
    assert not report.has_drift
    assert target.is_file()
    assert json.loads(target.read_text(encoding="utf-8")) == app.openapi()
