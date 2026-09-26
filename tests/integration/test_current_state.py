from __future__ import annotations

import pytest

from tests.fixtures.payloads import task_payload

pytestmark = pytest.mark.integration


def test_current_state_starts_empty_and_has_version(client, auth_headers) -> None:
    response = client.get("/api/v1/current-state", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["pending_tasks"] == []
    assert body["current_task"] is None
    assert body["version"] >= 1
    assert body["current_time"] is not None


def test_current_state_reflects_pending_tasks(client, auth_headers) -> None:
    client.post("/api/v1/tasks", json=task_payload(title="HW2"), headers=auth_headers)
    first = client.get("/api/v1/current-state", headers=auth_headers).json()
    assert len(first["pending_tasks"]) == 1

    second = client.get("/api/v1/current-state", headers=auth_headers).json()
    assert second["version"] > first["version"]


def test_current_state_overrides(client, auth_headers) -> None:
    response = client.patch(
        "/api/v1/current-state",
        json={"available_minutes": 120, "current_context": {"location": "library"}},
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["available_minutes"] == 120
    assert body["current_context"]["location"] == "library"


def test_completed_tasks_leave_pending_list(client, auth_headers) -> None:
    task = client.post("/api/v1/tasks", json=task_payload(), headers=auth_headers).json()
    client.patch(f"/api/v1/tasks/{task['id']}", json={"status": "COMPLETED"}, headers=auth_headers)
    body = client.get("/api/v1/current-state", headers=auth_headers).json()
    assert body["pending_tasks"] == []
