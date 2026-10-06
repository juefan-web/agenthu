"""OpenAPI <-> client Zod contract drift tests.

These guard the frozen client contract (``packages/contracts``, see DECISIONS.md
D-009) so a Backend change cannot silently break the desktop client and a stale
``openapi.json`` cannot be merged.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from backend.main import app
from backend.scripts.check_contract_drift import (
    ZOD_TO_OPENAPI,
    check_client_alignment,
    compare_artifact,
    parse_zod_schemas,
    run,
    validate_client_value,
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
        "source",
    }
    assert schemas["TaskSchema"]["source"].types == frozenset({"string"})
    assert schemas["TaskSchema"]["due_at"].types == frozenset({"string", "null"})
    assert schemas["TaskSchema"]["estimate_minutes"].types == frozenset({"integer", "null"})
    assert schemas["TaskSchema"]["status"].types == frozenset({"string"})
    assert schemas["PlanSchema"]["items"].items is not None
    assert schemas["PlanSchema"]["items"].items.ref == "PlanItemSchema"


def test_zod_parser_extracts_enum_datetime_and_bound_metadata() -> None:
    schemas = parse_zod_schemas(_fixture_source())
    assert schemas["TaskSchema"]["status"].enum == (
        "todo",
        "in_progress",
        "done",
        "cancelled",
    )
    assert schemas["TaskSchema"]["due_at"].is_datetime is True
    assert schemas["TaskSchema"]["estimate_minutes"].minimum == 0
    assert schemas["PlanSchema"]["status"].enum == (
        "draft",
        "confirmed",
        "active",
        "completed",
        "superseded",
    )


def test_runtime_validator_accepts_client_shaped_payload() -> None:
    payload = {
        "id": "t1",
        "title": "HW",
        "due_at": "2026-09-28T10:00:00+08:00",
        "estimate_minutes": 60,
        "status": "todo",
        "source_event_ids": [],
    }
    assert validate_client_value(payload, _fixture_source(), "TaskSchema") == []


def test_runtime_validator_allows_nullable_fields() -> None:
    payload = {
        "id": "t1",
        "title": "HW",
        "due_at": None,
        "estimate_minutes": None,
        "status": "in_progress",
        "source_event_ids": [],
    }
    assert validate_client_value(payload, _fixture_source(), "TaskSchema") == []


def test_runtime_validator_allows_defaulted_field_to_be_omitted() -> None:
    # EventEnvelopeSchema.context has `.default({})`, so it may be absent.
    payload = {
        "client_event_id": "c-1",
        "type": "study.assignment.discovered",
        "occurred_at": "2026-09-26T10:00:00+08:00",
        "source": "onethu",
        "data": {},
        "provenance": {
            "connector": "onethu",
            "connector_version": "v1",
            "upstream_id": "u-1",
            "semantic_version": "v1",
            "fetched_at": "2026-09-26T10:00:01+08:00",
        },
    }
    assert validate_client_value(payload, _fixture_source(), "EventEnvelopeSchema") == []


def test_runtime_validator_rejects_bad_enum_datetime_and_bound() -> None:
    payload = {
        "id": "t1",
        "title": "HW",
        "due_at": "yesterday",
        "estimate_minutes": -1,
        "status": "doing",
        "source_event_ids": [],
    }
    errors = validate_client_value(payload, _fixture_source(), "TaskSchema")
    assert any("TaskSchema.status" in error for error in errors)
    assert any("TaskSchema.due_at" in error for error in errors)
    assert any("TaskSchema.estimate_minutes" in error for error in errors)


def test_runtime_validator_rejects_missing_field_and_non_nullable_null() -> None:
    missing = validate_client_value(
        {"id": "t1", "title": "HW", "status": "todo", "source_event_ids": []},
        _fixture_source(),
        "TaskSchema",
    )
    assert any("TaskSchema.due_at: missing" in error for error in missing)

    bad_null = validate_client_value(
        {
            "id": "t1",
            "title": None,
            "due_at": None,
            "estimate_minutes": None,
            "status": "todo",
            "source_event_ids": [],
        },
        _fixture_source(),
        "TaskSchema",
    )
    assert any("TaskSchema.title: null is not allowed" in error for error in bad_null)


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


def test_zod_parser_expands_const_array_enum_references() -> None:
    """PR #75 review, blind spot #4 (D-035 note): a multi-line const array was
    never captured and ``z.enum(CONST)`` arguments were never expanded, so
    every const-referenced enum parsed as an EMPTY set and member checks
    silently passed for both TS copies."""

    source = """
const STATUSES = [
  "QUEUED",
  "READY",
] as const;
export const ProbeSchema = z.object({
  status: z.enum(STATUSES).nullable(),
  inline: z.enum(["A", "B"]),
});
"""
    schemas = parse_zod_schemas(source)
    assert schemas["ProbeSchema"]["status"].enum == ("QUEUED", "READY")
    assert schemas["ProbeSchema"]["status"].types == frozenset({"string", "null"})
    assert schemas["ProbeSchema"]["inline"].enum == ("A", "B")


def test_zod_parser_rejects_unresolved_enum_const_reference() -> None:
    """An unresolvable bare identifier in z.enum() is a parse failure, not an
    empty enum — otherwise the blind spot would come back silently."""

    source = """
export const ProbeSchema = z.object({
  status: z.enum(UNKNOWN_STATUSES),
});
"""
    with pytest.raises(ValueError, match="UNKNOWN_STATUSES"):
        parse_zod_schemas(source)


def test_fixture_data_enums_parse_non_empty() -> None:
    schemas = parse_zod_schemas(_fixture_source())
    assert schemas["DataOperationOutSchema"]["status"].enum == (
        "QUEUED",
        "RUNNING",
        "RETRY_WAIT",
        "READY",
        "COMPLETED",
        "EXPIRED",
        "FAILED",
    )
    assert schemas["DataOperationOutSchema"]["kind"].enum == ("EXPORT", "DELETION")
    assert schemas["DataOperationOutSchema"]["phase"].enum == (
        "EXPORT_COLLECT",
        "EXPORT_PACKAGE",
        "EXPORT_VERIFY",
        "DELETE_FENCE",
        "DELETE_RELATIONAL",
        "DELETE_OBJECTS",
        "DELETE_VERIFY",
    )
    assert schemas["DataReceiptOutSchema"]["completion_scope"].enum == ("controlled_live",)


def test_alignment_detects_enum_member_drift() -> None:
    """Mutation pin (PR #75 review, mutation A): renaming one enum member in
    the client contract used to stay green because member sets were never
    compared — the very drift this check exists to catch."""

    mutated = _fixture_source().replace('"RETRY_WAIT",', '"RETRY_WAIT_MUTATED",')
    assert '"RETRY_WAIT_MUTATED",' in mutated  # the mutation actually landed

    errors = check_client_alignment(mutated, app.openapi())
    assert any("DataOperationOut.status: enum members differ" in error for error in errors)


def test_alignment_detects_client_null_rejection() -> None:
    """Mutation pin (PR #75 review, mutation B): dropping ``.nullable()`` from
    a field the Backend serializes as an explicit null used to stay green —
    null was excluded from the comparison on both sides and only runtime
    samples could catch it, which /v1/data did not have."""

    mutated = _fixture_source().replace(
        "next_retry_at: IsoDateTime.nullable(),", "next_retry_at: IsoDateTime,"
    )
    assert "next_retry_at: IsoDateTime," in mutated

    errors = check_client_alignment(mutated, app.openapi())
    assert any(
        "DataOperationOut.next_retry_at: OpenAPI may serialize null" in error for error in errors
    )


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


def test_zod_parser_ignores_comments_inside_schema_bodies() -> None:
    """Comments with commas inside object bodies must not become fields.

    Regression for the convention formerly documented in PR #10's review:
    an inline comment containing a comma used to be comma-split into a bogus
    field name. The parser now strips line comments (string-aware) first, so
    comment placement is a style choice, not a load-bearing rule.
    """

    source = """
export const ProbeSchema = z.object({
  id: z.string(),
  // inline comment, with commas, and more: // nested-looking
  url: z.string().default("https://example.com/a//b"),
  count: z.number().int(),
});
const sensitiveKey = /^(?:password|cookie|token)$/i;
"""
    schemas = parse_zod_schemas(source)
    assert set(schemas["ProbeSchema"]) == {"id", "url", "count"}
    assert schemas["ProbeSchema"]["url"].types == frozenset({"string"})
    # The "//" inside the quoted default survived stripping (string-aware),
    # and the sensitiveKey regex literal (no "//" run) is untouched.
    from backend.scripts.check_contract_drift import _collect_consts, _strip_line_comments

    consts = _collect_consts(_strip_line_comments(source))
    assert consts["sensitiveKey"].startswith("/")
