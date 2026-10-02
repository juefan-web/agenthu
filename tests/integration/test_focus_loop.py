"""End-to-end Study + Time loop through the client-facing contract.

assignment event -> task + deadline -> /plans/today -> confirm ->
POST /focus-sessions -> PATCH complete -> actual duration -> current state -> re-plan
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tests.conftest import skip_late_night
from tests.fixtures.payloads import assignment_event, goal_payload, task_payload

pytestmark = pytest.mark.integration


def test_full_study_time_loop(client, auth_headers) -> None:
    # Planner v2 caps today's placement by the day's remaining minutes; near
    # local midnight a 60-minute task honestly no longer fits (shared guard).
    skip_late_night(65)

    goal = client.post("/v1/goals", json=goal_payload(), headers=auth_headers).json()

    event = client.post("/v1/events", json=assignment_event(), headers=auth_headers).json()
    task = client.post(
        "/v1/tasks",
        json=task_payload(
            title="Linear Algebra HW2",
            deadline=datetime.now(UTC) + timedelta(days=1),
            estimated_minutes=60,
            goal_id=goal["id"],
            related_event_ids=[event["id"]],
        ),
        headers=auth_headers,
    ).json()
    assert task["status"] == "todo"

    # Today plan is generated and requires confirmation.
    plan = client.get("/v1/plans/today", headers=auth_headers).json()
    assert plan["status"] == "draft"
    assert plan["confirmation_required"] is True
    assert len(plan["items"]) == 1

    state_before = client.get("/v1/current-state", headers=auth_headers).json()
    assert state_before["current_plan"] is None

    confirmed = client.post(f"/v1/plans/{plan['id']}/confirm", headers=auth_headers)
    assert confirmed.json()["status"] == "confirmed"

    state_confirmed = client.get("/v1/current-state", headers=auth_headers).json()
    assert state_confirmed["current_plan"]["id"] == plan["id"]

    # Focus session: start -> task in progress.
    started = client.post("/v1/focus-sessions", json={"task_id": task["id"]}, headers=auth_headers)
    assert started.status_code == 201, started.text
    session = started.json()
    assert session["status"] == "running"
    assert session["ended_at"] is None
    assert client.get(f"/v1/tasks/{task['id']}", headers=auth_headers).json()["status"] == (
        "in_progress"
    )

    # Complete -> actual duration recorded -> task done.
    completed = client.patch(
        f"/v1/focus-sessions/{session['id']}",
        json={"status": "completed", "actual_minutes": 75, "deviation_note": "Took longer"},
        headers=auth_headers,
    )
    assert completed.status_code == 200, completed.text
    body = completed.json()
    assert body["status"] == "completed"
    assert body["actual_minutes"] == 75
    assert body["ended_at"] is not None
    assert body["deviation_note"] == "Took longer"

    task_after = client.get(f"/v1/tasks/{task['id']}", headers=auth_headers).json()
    assert task_after["status"] == "done"
    assert task_after["actual_duration_minutes"] == 75

    state_after = client.get("/v1/current-state", headers=auth_headers).json()
    assert state_after["tasks"] == []
    assert state_after["recent_state"]["last_event_type"] == "focus.completed"

    # A new task plus re-planning after the deviation.
    client.post(
        "/v1/tasks",
        json=task_payload(
            title="Linear Algebra HW3", deadline=datetime.now(UTC) + timedelta(days=2)
        ),
        headers=auth_headers,
    )
    replanned = client.post(
        f"/v1/plans/{plan['id']}/replan",
        json={"reason": "HW2 took 75 min instead of 60; re-plan remaining work"},
        headers=auth_headers,
    )
    assert replanned.status_code == 201
    assert replanned.json()["basis"]["completed_task_ids"] == [task["id"]]
