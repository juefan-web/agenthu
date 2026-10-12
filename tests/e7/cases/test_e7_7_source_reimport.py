"""E7-7 driver: deleted-source reimport stays suppressed until explicit
re-authorization reopens the anchor (server faces).

Delete the anchored event e1 (upstream ``E7-U-asg-1``) through the real
preview/confirm path; the suppression row is HMAC-keyed and durable.

- suppressed_reimport_rejected: a fresh ingest carrying the SAME upstream
  id (not a dedupe replay — no dedupe key) is ``409 source_deleted`` at
  the create_event entry guard.
- release_reopens_anchor: ``release_source_suppressions`` has NO HTTP
  route by frozen design (§4 route matrix; the P0-6 connector flow owns
  the trigger surface), so the driver calls the service in-process
  against the same acceptance DB — the choice the manifest op note
  pre-registered for the driver to make. The release is an UPDATE
  (``released_at``), so the durable row survives (终态 ≥1, not 0).
- After the release the same ingest is 201 with a brand-new event row:
  net ``events`` delta zero, no seeded marker may be asserted absent.

The release writes its own audit row (``data.suppression_released``,
kind+count only, upstream stays HMAC'd) — audit_logs +1 is registered
with the driver in the manifest (E7-4b-precedent pre-run reconciliation).
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.services.write_guards import release_source_suppressions
from tests.e7.conftest import (
    confirm_target,
    login,
    verify_report,
    wait_operation,
    write_evidence,
)

UPSTREAM_ID = "E7-U-asg-1"

REIMPORT_PAYLOAD = {
    "type": "study.assignment.created",
    "timestamp": "2026-10-12T02:00:00+00:00",
    "source": "onethu",
    "data": {
        "title": "重采的作业一（E7-7 驱动）",
        "course": "线性代数",
        "due_at": "2026-10-20T00:00:00+00:00",
    },
    "provenance": {
        "connector": "onethu",
        "connector_version": "1",
        "upstream_id": UPSTREAM_ID,
        "semantic_version": "1",
        "fetched_at": "2026-10-12T02:00:00+00:00",
    },
}


def test_e7_7_suppressed_reimport_until_release(
    e7_api, e7_fresh_world, e7_verifier, e7_engine
) -> None:  # type: ignore[no-untyped-def]
    headers = login(e7_api, e7_fresh_world, "U")
    user = e7_fresh_world.users["U"]
    event_id = str(e7_fresh_world.rid("U", "e1"))

    _preview, operation = confirm_target(
        e7_api,
        headers,
        target={"kind": "source", "source_kind": "event", "ids": [event_id]},
        key="e7-7-confirm",
    )
    settled = wait_operation(e7_api, headers, operation["id"])
    assert settled["status"] == "COMPLETED", settled

    evidence: dict = {"operation_id": operation["id"], "faces": []}

    # suppressed_reimport_rejected — same upstream anchor, fresh ingest.
    rejected = e7_api.post("/v1/events", json=REIMPORT_PAYLOAD, headers=headers)
    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["error"]["code"] == "source_deleted", rejected.text
    evidence["faces"].append({"face": "reimport-rejected", "status": 409, "code": "source_deleted"})

    # release_reopens_anchor — no HTTP route by design; in-process call
    # against the acceptance DB (the manifest op note's recorded choice).
    with Session(e7_engine) as session:
        released = release_source_suppressions(
            session,
            user_id=user.user_id,
            source_kind="event",
            upstream_ids=[UPSTREAM_ID],
        )
        session.commit()
    assert released >= 1, "the suppression row must exist and be releasable"
    with e7_engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT count(*) FROM data_suppressions "
                "WHERE owner_handle = :h AND source_kind = 'event' "
                "AND released_at IS NOT NULL"
            ),
            {"h": user.owner_handle},
        ).scalar_one()
    assert row >= 1, "durable ledger row survives the release as an UPDATE"
    evidence["released"] = released

    # The anchor is open again: the same ingest is a brand-new row.
    reimported = e7_api.post("/v1/events", json=REIMPORT_PAYLOAD, headers=headers)
    assert reimported.status_code == 201, reimported.text
    assert reimported.headers.get("X-Deduplicated") == "false", reimported.headers
    evidence["faces"].append({"face": "reimport-after-release", "status": 201})

    write_evidence("E7-7", "protocol.json", evidence)
    write_evidence("E7-7", "operation.json", settled)
    report = verify_report(e7_verifier, "E7-7")
    write_evidence("E7-7", "verify.json", report.to_dict())
