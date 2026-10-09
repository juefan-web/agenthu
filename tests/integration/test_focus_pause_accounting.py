"""Pause-aware focus duration accounting (live-mine-2 §0, acceptance ①–⑦).

Wall-clock time is simulated by rewinding the session row's timestamps
through the shared db_session — the client fixture rides the same session,
so the service sees the shifted clock without sleeping.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from backend.models.focus_session import FocusSession
from tests.fixtures.payloads import task_payload

pytestmark = pytest.mark.integration


def _start(client, headers) -> tuple[dict, dict]:
    task = client.post(
        "/v1/tasks", json=task_payload(title="pause accounting"), headers=headers
    ).json()
    session = client.post(
        "/v1/focus-sessions", json={"task_id": task["id"]}, headers=headers
    ).json()
    return task, session


def _rewind(
    db_session,
    session_id: str,
    *,
    started_minutes_ago: float | None = None,
    paused_minutes_ago: float | None = None,
) -> None:
    row = db_session.get(FocusSession, uuid.UUID(session_id))
    now = datetime.now(UTC)
    if started_minutes_ago is not None:
        row.started_at = now - timedelta(minutes=started_minutes_ago)
    if paused_minutes_ago is not None:
        row.paused_at = now - timedelta(minutes=paused_minutes_ago)
    db_session.flush()


def _events(client, headers, event_type: str) -> list[dict]:
    """Round order, not the API's newest-first listing order."""

    items = client.get("/v1/events", params={"type": event_type}, headers=headers).json()["items"]
    return sorted(items, key=lambda event: int(event["dedupe_key"].rsplit(":", 1)[-1]))


def _row(db_session, session_id: str) -> FocusSession:
    return db_session.get(FocusSession, uuid.UUID(session_id))


def test_overnight_pause_excluded_from_default_actual_minutes(
    client, auth_headers, db_session
) -> None:
    """①: a 9h overnight pause contributes 0 minutes; only the worked hour
    counts. ⑦: paused/resumed/completed snapshots are each self-explanatory."""

    task, session = _start(client, auth_headers)
    assert (
        client.patch(
            f"/v1/focus-sessions/{session['id']}", json={"status": "paused"}, headers=auth_headers
        ).status_code
        == 200
    )

    # Ran 60 min, then paused 540 min ago (overnight).
    _rewind(db_session, session["id"], started_minutes_ago=600, paused_minutes_ago=540)
    assert (
        client.patch(
            f"/v1/focus-sessions/{session['id']}", json={"status": "running"}, headers=auth_headers
        ).status_code
        == 200
    )
    completed = client.patch(
        f"/v1/focus-sessions/{session['id']}", json={"status": "completed"}, headers=auth_headers
    ).json()

    assert completed["actual_minutes"] == 60
    task_after = client.get(f"/v1/tasks/{task['id']}", headers=auth_headers).json()
    assert task_after["actual_duration_minutes"] == 60

    paused = _events(client, auth_headers, "focus.paused")
    resumed = _events(client, auth_headers, "focus.resumed")
    done = _events(client, auth_headers, "focus.completed")
    assert len(paused) == len(resumed) == len(done) == 1
    # ⑦ snapshots: pause-time accumulated (0 — nothing closed yet), the
    # just-closed segment, and the completion-time total.
    assert paused[0]["data"]["accumulated_pause_seconds"] == 0
    assert resumed[0]["data"]["pause_seconds"] == 540 * 60
    assert resumed[0]["data"]["accumulated_pause_seconds"] == 540 * 60
    assert done[0]["data"]["actual_minutes"] == 60
    assert done[0]["data"]["accumulated_pause_seconds"] == 540 * 60


def test_multiple_pause_rounds_all_counted_with_independent_events(
    client, auth_headers, db_session
) -> None:
    """②+④+⑦: two pause rounds — both excluded from the default, both
    emitting their own events with per-round readable segment durations."""

    _task, session = _start(client, auth_headers)
    sid = session["id"]

    client.patch(f"/v1/focus-sessions/{sid}", json={"status": "paused"}, headers=auth_headers)
    _rewind(db_session, sid, started_minutes_ago=480, paused_minutes_ago=240)
    client.patch(f"/v1/focus-sessions/{sid}", json={"status": "running"}, headers=auth_headers)

    client.patch(f"/v1/focus-sessions/{sid}", json={"status": "paused"}, headers=auth_headers)
    _rewind(db_session, sid, paused_minutes_ago=120)
    client.patch(f"/v1/focus-sessions/{sid}", json={"status": "running"}, headers=auth_headers)

    completed = client.patch(
        f"/v1/focus-sessions/{sid}", json={"status": "completed"}, headers=auth_headers
    ).json()
    # Wall 480 - pauses 240+120 = 120 worked minutes.
    assert completed["actual_minutes"] == 120

    paused = _events(client, auth_headers, "focus.paused")
    resumed = _events(client, auth_headers, "focus.resumed")
    # ④: the fixed per-session dedupe key would have swallowed round 2.
    assert len(paused) == 2
    assert len(resumed) == 2
    assert {event["dedupe_key"] for event in paused} == {
        f"focus-session:{sid}:paused:0",
        f"focus-session:{sid}:paused:1",
    }
    # ⑦: each round's segment is independently readable, in order.
    assert [event["data"]["accumulated_pause_seconds"] for event in paused] == [0, 240 * 60]
    assert [event["data"]["pause_seconds"] for event in resumed] == [240 * 60, 120 * 60]
    assert [event["data"]["accumulated_pause_seconds"] for event in resumed] == [
        240 * 60,
        360 * 60,
    ]
    done = _events(client, auth_headers, "focus.completed")
    assert done[0]["data"]["accumulated_pause_seconds"] == 360 * 60


def test_paused_direct_to_completed_closes_the_open_segment(
    client, auth_headers, db_session
) -> None:
    """③+⑦: PAUSED→COMPLETED closes the open segment first; the completed
    snapshot includes the just-closed segment."""

    _task, session = _start(client, auth_headers)
    sid = session["id"]
    client.patch(f"/v1/focus-sessions/{sid}", json={"status": "paused"}, headers=auth_headers)
    _rewind(db_session, sid, started_minutes_ago=200, paused_minutes_ago=150)

    completed = client.patch(
        f"/v1/focus-sessions/{sid}", json={"status": "completed"}, headers=auth_headers
    ).json()
    assert completed["actual_minutes"] == 50

    row = _row(db_session, sid)
    assert row.paused_at is None
    assert row.accumulated_pause_seconds == 150 * 60
    done = _events(client, auth_headers, "focus.completed")
    assert done[0]["data"]["accumulated_pause_seconds"] == 150 * 60


def test_paused_direct_to_abandoned_closes_the_open_segment(
    client, auth_headers, db_session
) -> None:
    """③: same closure treatment for ABANDONED — no actual_minutes, but the
    pause ledger ends consistent (open segment closed, paused_at cleared)."""

    _task, session = _start(client, auth_headers)
    sid = session["id"]
    client.patch(f"/v1/focus-sessions/{sid}", json={"status": "paused"}, headers=auth_headers)
    _rewind(db_session, sid, started_minutes_ago=90, paused_minutes_ago=30)

    abandoned = client.patch(
        f"/v1/focus-sessions/{sid}", json={"status": "abandoned"}, headers=auth_headers
    ).json()
    assert abandoned["status"] == "abandoned"

    row = _row(db_session, sid)
    assert row.paused_at is None
    assert row.accumulated_pause_seconds == 30 * 60
    assert row.actual_minutes is None


def test_explicit_actual_minutes_still_overrides_the_net_default(
    client, auth_headers, db_session
) -> None:
    """The user-correction face is unchanged: an explicit value wins over
    the computed net default."""

    task, session = _start(client, auth_headers)
    sid = session["id"]
    client.patch(f"/v1/focus-sessions/{sid}", json={"status": "paused"}, headers=auth_headers)
    _rewind(db_session, sid, started_minutes_ago=200, paused_minutes_ago=150)
    client.patch(f"/v1/focus-sessions/{sid}", json={"status": "running"}, headers=auth_headers)

    completed = client.patch(
        f"/v1/focus-sessions/{sid}",
        json={"status": "completed", "actual_minutes": 40},
        headers=auth_headers,
    ).json()
    assert completed["actual_minutes"] == 40
    task_after = client.get(f"/v1/tasks/{task['id']}", headers=auth_headers).json()
    assert task_after["actual_duration_minutes"] == 40


def test_resume_of_legacy_paused_row_without_timestamp_is_a_no_segment_close(
    client, auth_headers, db_session
) -> None:
    """A PAUSED row from before the pause columns (paused_at NULL) resumes
    with a zero-length segment: nothing was recorded open, nothing closes."""

    _task, session = _start(client, auth_headers)
    sid = session["id"]
    client.patch(f"/v1/focus-sessions/{sid}", json={"status": "paused"}, headers=auth_headers)
    # Simulate the legacy shape: status paused, no recorded timestamp.
    row = _row(db_session, sid)
    row.paused_at = None
    db_session.flush()

    resumed = client.patch(
        f"/v1/focus-sessions/{sid}", json={"status": "running"}, headers=auth_headers
    ).json()
    assert resumed["status"] == "running"
    after = _row(db_session, sid)
    assert after.accumulated_pause_seconds == 0
    resumed_events = _events(client, auth_headers, "focus.resumed")
    assert resumed_events[0]["data"]["pause_seconds"] == 0
