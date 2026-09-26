"""End-to-end Study + Time loop through the HTTP contract.

course/assignment event -> task+deadline -> generated plan -> confirm ->
focus start -> focus complete -> actual duration -> current state -> re-plan
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tests.fixtures.payloads import assignment_event, goal_payload, task_payload

pytestmark = pytest.mark.integration


def test_full_study_time_loop(client, auth_headers) -> None:
    goal = client.post("/api/v1/goals", json=goal_payload(), headers=auth_headers).json()

    event = client.post("/api/v1/events", json=assignment_event(), headers=auth_headers).json()
    task = client.post(
        "/api/v1/tasks",
        json=task_payload(
            title="Linear Algebra HW2",
            deadline=datetime.now(UTC) + timedelta(days=1),
            estimated_minutes=60,
            goal_id=goal["id"],
            related_event_ids=[event["id"]],
        ),
        headers=auth_headers,
    ).json()

    # Plan is generated and requires confirmation.
    plan = client.post("/api/v1/plans/generate", json={}, headers=auth_headers).json()
    assert plan["permission_level"] == 2
    assert len(plan["items"]) == 1

    state_before = client.get("/api/v1/current-state", headers=auth_headers).json()
    assert state_before["current_plan"] is None

    confirmed = client.post(f"/api/v1/plans/{plan['id']}/confirm", headers=auth_headers)
    assert confirmed.json()["status"] == "CONFIRMED"

    state_confirmed = client.get("/api/v1/current-state", headers=auth_headers).json()
    assert state_confirmed["current_plan"]["id"] == plan["id"]

    # Focus start -> event -> task becomes IN_PROGRESS.
    started = client.post(f"/api/v1/tasks/{task['id']}/focus/start", headers=auth_headers)
    assert started.status_code == 200
    assert started.json()["type"] == "focus.started"
    assert client.get(f"/api/v1/tasks/{task['id']}", headers=auth_headers).json()["status"] == (
        "IN_PROGRESS"
    )

    # Focus complete -> actual duration recorded -> task completed.
    completed = client.post(
        f"/api/v1/tasks/{task['id']}/focus/complete",
        json={"actual_minutes": 75, "completed": True, "notes": "Took longer than planned"},
        headers=auth_headers,
    )
    assert completed.status_code == 200, completed.text
    completed_task = completed.json()
    assert completed_task["status"] == "COMPLETED"
    assert completed_task["actual_duration_minutes"] == 75

    state_after = client.get("/api/v1/current-state", headers=auth_headers).json()
    assert state_after["pending_tasks"] == []
    assert state_after["recent_state"]["last_event_type"] == "focus.completed"

    # A new task plus re-planning after the deviation.
    client.post(
        "/api/v1/tasks",
        json=task_payload(
            title="Linear Algebra HW3", deadline=datetime.now(UTC) + timedelta(days=2)
        ),
        headers=auth_headers,
    )
    replanned = client.post(
        f"/api/v1/plans/{plan['id']}/replan",
        json={"reason": "HW2 took 75 min instead of 60; re-plan remaining work"},
        headers=auth_headers,
    )
    assert replanned.status_code == 201
    assert replanned.json()["replaces_plan_id"] == plan["id"]
    assert replanned.json()["basis"]["completed_task_ids"] == [task["id"]]
