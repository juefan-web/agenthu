from __future__ import annotations

import pytest

from tests.fixtures.payloads import task_payload

pytestmark = pytest.mark.integration


def test_current_state_matches_client_contract(client, auth_headers) -> None:
    response = client.get("/v1/current-state", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    # Client contract fields.
    assert body["version"] >= 1
    assert body["now"] is not None
    assert body["updated_at"] is not None
    assert body["tasks"] == []
    assert "available_minutes" in body
    assert "context" in body
    # Additive backend fields.
    assert body["pending_tasks"] == []
    assert body["current_task"] is None


def test_current_state_reflects_pending_tasks(client, auth_headers) -> None:
    client.post("/v1/tasks", json=task_payload(title="HW2"), headers=auth_headers)
    first = client.get("/v1/current-state", headers=auth_headers).json()
    assert len(first["tasks"]) == 1
    assert first["tasks"][0]["status"] == "todo"

    second = client.get("/v1/current-state", headers=auth_headers).json()
    assert second["version"] > first["version"]


def test_current_state_overrides(client, auth_headers) -> None:
    response = client.patch(
        "/v1/current-state",
        json={"available_minutes": 120, "current_context": {"label": "library"}},
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["available_minutes"] == 120
    assert body["context"] == "library"
    assert body["current_context"]["label"] == "library"


def test_completed_tasks_leave_pending_list(client, auth_headers) -> None:
    task = client.post("/v1/tasks", json=task_payload(), headers=auth_headers).json()
    client.patch(f"/v1/tasks/{task['id']}", json={"status": "COMPLETED"}, headers=auth_headers)
    body = client.get("/v1/current-state", headers=auth_headers).json()
    assert body["tasks"] == []


def test_current_state_rejects_other_users_task(client, auth_factory) -> None:
    alice = auth_factory()
    bob = auth_factory()
    task = client.post("/v1/tasks", json=task_payload(), headers=alice).json()

    response = client.patch("/v1/current-state", json={"current_task_id": task["id"]}, headers=bob)
    assert response.status_code == 404
