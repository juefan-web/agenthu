"""Batch-end state recompute + content-gated version (evaluation §4).

Handlers mark the user dirty instead of recomputing inline; ingestion exit
points flush once (single event) or once per batch (batch ingest), and
``version`` moves only when the projection content changes — never for
no-change reads or wall-clock drift.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy.orm import Session

from backend.services import current_state
from backend.services.current_state import recompute_current_state
from tests.fixtures.payloads import assignment_envelope

pytestmark = pytest.mark.integration


def _single_event_payload(title: str) -> dict[str, Any]:
    """A single-event (EventCreate) payload of a type WITH handlers, so the
    create path actually exercises mark-dirty -> immediate flush."""

    now = datetime.now(UTC).isoformat()
    return {
        "type": "study.assignment.discovered",
        "source": "onethu",
        "timestamp": now,
        "data": {
            "assignment_id": f"single-{uuid.uuid4().hex[:10]}",
            "course_id": "course-single",
            "course_name": "单事件课",
            "title": title,
            "content": "batching test",
            "publish_time": now,
            "deadline": "2026-10-03T23:59:00+08:00",
            "deadline_raw": "2026-10-03T23:59:00+08:00",
            "submitted": False,
            "graded": False,
            "url": "https://learn.example.com/single",
        },
        "context": {},
        # The derivation handler keys on provenance.upstream_id — without it
        # the handler returns early and never marks the user dirty.
        "provenance": {
            "fixture": "test_state_recompute_batching",
            "upstream_id": f"single-{uuid.uuid4().hex[:10]}",
        },
    }


def _envelope(client_event_id: str, title: str) -> dict[str, Any]:
    """An assignment-discovered envelope: a type WITH handlers, so the batch
    actually exercises the mark-dirty -> batch-end-flush path."""

    return assignment_envelope(
        client_event_id=client_event_id,
        upstream_id=f"hw:{uuid.uuid4().hex}",
        title=title,
    )


def _counting_recompute(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    calls = {"n": 0}
    real = current_state.recompute_current_state

    def counting(session: Session, user_id: uuid.UUID) -> object:
        calls["n"] += 1
        return real(session, user_id)

    monkeypatch.setattr(current_state, "recompute_current_state", counting)
    return calls


def test_batch_ingestion_recomputes_once(client, auth_headers, monkeypatch) -> None:
    calls = _counting_recompute(monkeypatch)

    response = client.post(
        "/v1/events/batch",
        json={
            "events": [_envelope(f"c-{i}", f"计数作业{i}") for i in range(5)],
            "client_cursor": None,
        },
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert len(response.json()["accepted_event_ids"]) == 5
    assert calls["n"] == 1, "one batch = one projection recompute"


def test_single_event_flushes_immediately(client, auth_headers, monkeypatch) -> None:
    calls = _counting_recompute(monkeypatch)

    response = client.post(
        "/v1/events",
        json=_single_event_payload("单事件作业"),
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    assert calls["n"] == 1


def test_duplicate_only_batch_skips_recompute(client, auth_headers, monkeypatch) -> None:
    calls = _counting_recompute(monkeypatch)
    payload = {
        "events": [_envelope("dup-1", "重复作业")],
        "client_cursor": None,
    }

    first = client.post("/v1/events/batch", json=payload, headers=auth_headers)
    assert first.status_code == 200
    assert calls["n"] == 1

    second = client.post("/v1/events/batch", json=payload, headers=auth_headers)
    assert second.status_code == 200
    assert second.json()["accepted_event_ids"] == []
    assert second.json()["duplicate_event_ids"] == ["dup-1"]
    assert calls["n"] == 1, "no handler ran for duplicates, so nothing to flush"


def test_recompute_version_tracks_content_not_reads(client, auth_headers, db_session) -> None:
    user_id = uuid.UUID(client.get("/v1/auth/me", headers=auth_headers).json()["id"])

    first = recompute_current_state(db_session, user_id)
    second = recompute_current_state(db_session, user_id)
    assert first.version >= 1
    assert second.version == first.version, "no-change recompute keeps the version"

    # A structural change (pending set) moves the version. Task creation
    # does not recompute inline, so the bump happens on the next recompute.
    client.post("/v1/tasks", json={"title": "版本测试任务"}, headers=auth_headers)
    third = recompute_current_state(db_session, user_id)
    assert third.version > second.version

    # A no-change read right after still keeps it.
    fourth = recompute_current_state(db_session, user_id)
    assert fourth.version == third.version


def test_event_batch_bumps_version_once(client, auth_headers, db_session) -> None:
    """A three-event batch costs exactly ONE version bump at batch end — not
    one per event — and a no-change read right after keeps the version."""

    user_id = uuid.UUID(client.get("/v1/auth/me", headers=auth_headers).json()["id"])
    before = recompute_current_state(db_session, user_id)

    response = client.post(
        "/v1/events/batch",
        json={
            "events": [_envelope(f"ev-{i}", f"纯事件-{i}") for i in range(3)],
            "client_cursor": None,
        },
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text

    after = recompute_current_state(db_session, user_id)
    assert after.version == before.version + 1
    assert after.recent_state["last_event_type"] == "study.assignment.discovered"
    assert len(after.pending_tasks) == 3

    again = recompute_current_state(db_session, user_id)
    assert again.version == after.version


def test_assignment_batch_end_to_end(client, auth_headers, db_session) -> None:
    """The E4-critical path: a 10-event assignment sync derives its tasks and
    leaves the projection consistent with exactly one batch-end recompute."""

    user_id = uuid.UUID(client.get("/v1/auth/me", headers=auth_headers).json()["id"])
    before = recompute_current_state(db_session, user_id)

    events = [_envelope(f"assign-{i}", f"批量作业{i}") for i in range(10)]
    response = client.post(
        "/v1/events/batch", json={"events": events, "client_cursor": None}, headers=auth_headers
    )
    assert response.status_code == 200, response.text
    assert len(response.json()["accepted_event_ids"]) == 10

    listing = client.get("/v1/tasks?limit=200", headers=auth_headers).json()
    assert len(listing) == 10

    after = recompute_current_state(db_session, user_id)
    assert after.version > before.version
    assert len(after.pending_tasks) == 10
