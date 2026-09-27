"""Frozen contract smoke test for the desktop client (`packages/contracts`).

These assertions mirror the Zod schemas the client validates responses with, so
a Backend change that breaks client parsing fails here instead of at runtime.
"""

from __future__ import annotations

from typing import Any

import pytest

pytestmark = pytest.mark.integration

TASK_FIELDS = {"id", "title", "due_at", "estimate_minutes", "status", "source_event_ids"}
CURRENT_STATE_FIELDS = {
    "version",
    "updated_at",
    "now",
    "context",
    "tasks",
    "available_minutes",
}
PLAN_FIELDS = {"id", "generated_at", "items", "confirmation_required", "status"}
PLAN_ITEM_FIELDS = {"task_id", "start_at", "end_at", "reason"}
FOCUS_FIELDS = {
    "id",
    "task_id",
    "started_at",
    "ended_at",
    "actual_minutes",
    "status",
    "deviation_note",
}
BATCH_FIELDS = {"accepted_event_ids", "duplicate_event_ids", "rejected", "next_cursor"}

TASK_STATUSES = {"todo", "in_progress", "done", "cancelled"}
PLAN_STATUSES = {"draft", "confirmed", "active", "completed", "superseded"}
FOCUS_STATUSES = {"running", "paused", "completed", "abandoned"}


def _envelope(client_event_id: str, upstream_id: str) -> dict[str, Any]:
    return {
        "client_event_id": client_event_id,
        "type": "study.assignment.discovered",
        "occurred_at": "2026-09-26T10:00:00+08:00",
        "source": "onethu",
        "data": {"title": "HW1"},
        "context": {},
        "provenance": {
            "connector": "onethu",
            "connector_version": "2e3455f",
            "upstream_id": upstream_id,
            "semantic_version": "v1",
            "fetched_at": "2026-09-26T10:00:01+08:00",
        },
    }


def test_task_matches_client_schema(client, auth_headers) -> None:
    task = client.post(
        "/v1/tasks",
        json={"title": "HW2", "due_at": "2026-09-28T10:00:00+08:00", "estimate_minutes": 60},
        headers=auth_headers,
    ).json()
    assert set(task) >= TASK_FIELDS
    assert task["status"] in TASK_STATUSES
    assert isinstance(task["source_event_ids"], list)

    listing = client.get("/v1/tasks", headers=auth_headers)
    assert isinstance(listing.json(), list)


def test_current_state_matches_client_schema(client, auth_headers) -> None:
    client.post("/v1/tasks", json={"title": "HW2"}, headers=auth_headers)
    state = client.get("/v1/current-state", headers=auth_headers).json()
    assert set(state) >= CURRENT_STATE_FIELDS
    assert isinstance(state["tasks"], list)
    assert all(set(task) >= TASK_FIELDS for task in state["tasks"])


def test_today_plan_matches_client_schema(client, auth_headers) -> None:
    client.post("/v1/tasks", json={"title": "HW2"}, headers=auth_headers)
    plan = client.get("/v1/plans/today", headers=auth_headers).json()
    assert set(plan) >= PLAN_FIELDS
    assert plan["status"] in PLAN_STATUSES
    assert isinstance(plan["confirmation_required"], bool)
    for item in plan["items"]:
        assert set(item) >= PLAN_ITEM_FIELDS
        assert item["task_id"] is not None
        assert item["start_at"] is not None
        assert item["end_at"] is not None
        assert item["reason"]


def test_focus_session_matches_client_schema(client, auth_headers) -> None:
    task = client.post("/v1/tasks", json={"title": "HW2"}, headers=auth_headers).json()
    session = client.post(
        "/v1/focus-sessions", json={"task_id": task["id"]}, headers=auth_headers
    ).json()
    assert set(session) >= FOCUS_FIELDS
    assert session["status"] in FOCUS_STATUSES

    completed = client.patch(
        f"/v1/focus-sessions/{session['id']}",
        json={"status": "completed", "actual_minutes": 30},
        headers=auth_headers,
    ).json()
    assert completed["status"] == "completed"
    assert completed["actual_minutes"] == 30
    assert completed["ended_at"] is not None


def test_event_batch_matches_client_schema(client, auth_headers) -> None:
    payload = {"events": [_envelope("c-1", "hw-1")], "client_cursor": None}
    response = client.post("/v1/events/batch", json=payload, headers=auth_headers).json()
    assert set(response) >= BATCH_FIELDS
    assert response["accepted_event_ids"] == ["c-1"]

    again = client.post("/v1/events/batch", json=payload, headers=auth_headers).json()
    assert again["duplicate_event_ids"] == ["c-1"]


def test_missing_token_returns_401(client) -> None:
    response = client.get("/v1/tasks")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


def test_invalid_token_returns_401(client) -> None:
    response = client.get("/v1/tasks", headers={"Authorization": "Bearer not-a-real-token"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"
