from __future__ import annotations

import pytest

from tests.fixtures.payloads import assignment_event, goal_payload, task_payload

pytestmark = pytest.mark.integration


def test_goal_and_task_with_event_link(client, auth_headers) -> None:
    goal = client.post("/v1/goals", json=goal_payload(), headers=auth_headers).json()
    event = client.post("/v1/events", json=assignment_event(), headers=auth_headers).json()

    created = client.post(
        "/v1/tasks",
        json=task_payload(goal_id=goal["id"], related_event_ids=[event["id"]]),
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    task = created.json()
    # Client contract fields.
    assert task["goal_id"] == goal["id"]
    assert event["id"] in task["source_event_ids"]
    assert task["status"] == "todo"
    assert task["due_at"] is not None
    assert task["estimate_minutes"] == 120


def test_task_requires_owned_goal(client, auth_factory) -> None:
    alice = auth_factory()
    bob = auth_factory()
    goal = client.post("/v1/goals", json=goal_payload(), headers=alice).json()

    response = client.post("/v1/tasks", json=task_payload(goal_id=goal["id"]), headers=bob)
    assert response.status_code == 404


def test_task_update_status_uses_client_enum(client, auth_headers) -> None:
    task = client.post("/v1/tasks", json=task_payload(), headers=auth_headers).json()

    updated = client.patch(
        f"/v1/tasks/{task['id']}",
        json={"status": "IN_PROGRESS", "actual_duration_minutes": 30},
        headers=auth_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "in_progress"
    assert updated.json()["completed_at"] is None

    completed = client.patch(
        f"/v1/tasks/{task['id']}", json={"status": "COMPLETED"}, headers=auth_headers
    )
    assert completed.json()["status"] == "done"
    assert completed.json()["completed_at"] is not None


def test_task_list_returns_array_and_filters(client, auth_headers) -> None:
    goal = client.post("/v1/goals", json=goal_payload(), headers=auth_headers).json()
    client.post("/v1/tasks", json=task_payload(title="A"), headers=auth_headers)
    client.post("/v1/tasks", json=task_payload(title="B", goal_id=goal["id"]), headers=auth_headers)

    by_goal = client.get("/v1/tasks", params={"goal_id": goal["id"]}, headers=auth_headers)
    assert isinstance(by_goal.json(), list)
    assert [item["title"] for item in by_goal.json()] == ["B"]

    by_status = client.get("/v1/tasks", params={"status": "TODO"}, headers=auth_headers)
    assert len(by_status.json()) == 2


def test_task_event_link_and_unlink(client, auth_headers) -> None:
    task = client.post("/v1/tasks", json=task_payload(), headers=auth_headers).json()
    event = client.post("/v1/events", json=assignment_event(), headers=auth_headers).json()

    linked = client.post(f"/v1/tasks/{task['id']}/events/{event['id']}", headers=auth_headers)
    assert event["id"] in linked.json()["source_event_ids"]

    unlinked = client.delete(f"/v1/tasks/{task['id']}/events/{event['id']}", headers=auth_headers)
    assert unlinked.json()["source_event_ids"] == []


def test_task_isolation_between_users(client, auth_factory) -> None:
    alice = auth_factory()
    bob = auth_factory()
    task = client.post("/v1/tasks", json=task_payload(), headers=alice).json()

    assert client.get(f"/v1/tasks/{task['id']}", headers=bob).status_code == 404
    assert client.get("/v1/tasks", headers=bob).json() == []
