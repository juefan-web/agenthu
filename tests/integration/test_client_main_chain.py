"""Repeatable API fixtures for the client's Event -> Task -> Plan -> Focus chain.

This is the contract-level dry run of the Study + Time loop using the exact
payloads the desktop client sends: a batch of normalized Events (``events/batch``),
a Task, the ``current-state`` projection, the ``plans/today`` proposal, its
confirmation, and a Focus session. All payloads are deterministic (see
``tests/fixtures/payloads.py``).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from backend.config import get_settings
from tests.fixtures.payloads import assignment_envelope, task_payload

pytestmark = pytest.mark.integration

_LOCAL_TZ = ZoneInfo(get_settings().default_timezone)


def _skip_late_night(minutes_needed: int) -> None:
    """Planner v2 caps placement by the day's remaining minutes (D-027
    formula), so near local midnight an honest plan may place only part of
    the fixture's tasks. Same guard as test_plans (hotfix e70f01d) — this
    test asserts BOTH tasks land in today's plan (60 + 60 minutes)."""

    now = datetime.now(_LOCAL_TZ)
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    if (midnight - now).total_seconds() // 60 < minutes_needed:
        pytest.skip(f"late-night window: less than {minutes_needed} minutes left today")


def test_event_batch_to_focus_main_chain(client, auth_headers, db_session) -> None:
    _skip_late_night(130)
    upstream_id = f"hw-{uuid.uuid4().hex[:10]}"
    client_event_id = f"client-{upstream_id}"
    batch_request = {
        "events": [
            assignment_envelope(client_event_id=client_event_id, upstream_id=upstream_id),
        ],
        "client_cursor": "cursor-1",
    }

    # 1. Event ingestion: accepted, then idempotent on replay.
    batch = client.post("/v1/events/batch", json=batch_request, headers=auth_headers)
    assert batch.status_code == 200, batch.text
    assert batch.json() == {
        "accepted_event_ids": [client_event_id],
        "duplicate_event_ids": [],
        "rejected": [],
        "next_cursor": "cursor-1",
    }
    replay = client.post("/v1/events/batch", json=batch_request, headers=auth_headers).json()
    assert replay["accepted_event_ids"] == []
    assert replay["duplicate_event_ids"] == [client_event_id]

    # 2. Task linked to the ingested Event.
    task = client.post(
        "/v1/tasks",
        json=task_payload(
            title="Linear Algebra HW2",
            deadline=datetime.now(UTC) + timedelta(days=1),
            estimated_minutes=60,
        ),
        headers=auth_headers,
    ).json()
    assert task["status"] == "todo"
    assert task["estimate_minutes"] == 60
    assert task["source"] == "manual"

    # 3. Current state surfaces the pending task with the client shape.
    # The ingested assignment event now also derives its own task (M1-1,
    # D-028); filter to the manually created one for the shape comparison and
    # assert the derived task exists alongside it.
    state = client.get("/v1/current-state", headers=auth_headers).json()
    assert [t for t in state["tasks"] if t["id"] == task["id"]] == [task]
    derived = [t for t in state["tasks"] if t["id"] != task["id"]]
    assert len(derived) == 1 and derived[0]["title"] == "Linear Algebra HW2"
    assert derived[0]["source"] == "onethu"
    # The derived task carries its upstream identity in the persistence layer
    # (stripped from the client contract shape above).
    from backend.models.task import Task as TaskModel

    derived_row = db_session.scalar(
        select(TaskModel).where(TaskModel.id == uuid.UUID(derived[0]["id"]))
    )
    assert derived_row is not None
    assert derived_row.source_upstream_id == upstream_id
    assert derived_row.source == "onethu"

    # 4. Today's plan proposes the task and needs confirmation.
    plan = client.get("/v1/plans/today", headers=auth_headers).json()
    assert plan["status"] == "draft"
    assert plan["confirmation_required"] is True
    # Both the manual task and the derived assignment task are schedulable.
    assert {item["task_id"] for item in plan["items"]} == {
        task["id"],
        derived[0]["id"],
    }

    # 5. Confirmation makes it the current plan (current_plan = confirmed only).
    confirmed = client.post(f"/v1/plans/{plan['id']}/confirm", headers=auth_headers).json()
    assert confirmed["status"] == "confirmed"
    assert confirmed["confirmation_required"] is False
    state = client.get("/v1/current-state", headers=auth_headers).json()
    assert state["current_plan"]["id"] == plan["id"]

    # 6. Focus session: start -> running, complete -> actual minutes and task done.
    started = client.post("/v1/focus-sessions", json={"task_id": task["id"]}, headers=auth_headers)
    assert started.status_code == 201, started.text
    session = started.json()
    assert session["status"] == "running"
    assert session["ended_at"] is None

    completed = client.patch(
        f"/v1/focus-sessions/{session['id']}",
        json={"status": "completed", "actual_minutes": 45, "deviation_note": "Faster"},
        headers=auth_headers,
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "completed"
    assert completed.json()["actual_minutes"] == 45
    assert completed.json()["ended_at"] is not None

    task_after = client.get(f"/v1/tasks/{task['id']}", headers=auth_headers).json()
    assert task_after["status"] == "done"
    state_after = client.get("/v1/current-state", headers=auth_headers).json()
    # Only the derived (still pending) assignment task remains.
    assert [t["id"] for t in state_after["tasks"]] == [derived[0]["id"]]


def test_main_chain_requires_authentication(client, expired_token_headers) -> None:
    for method, path in (
        ("post", "/v1/events/batch"),
        ("get", "/v1/tasks"),
        ("get", "/v1/current-state"),
        ("get", "/v1/plans/today"),
    ):
        response = getattr(client, method)(path, headers=expired_token_headers)
        assert response.status_code == 401, (method, path, response.text)
        assert response.json()["error"]["code"] == "unauthenticated"
