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

import pytest

from tests.fixtures.payloads import assignment_envelope, task_payload

pytestmark = pytest.mark.integration


def test_event_batch_to_focus_main_chain(client, auth_headers) -> None:
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

    # 3. Current state surfaces the pending task with the client shape.
    state = client.get("/v1/current-state", headers=auth_headers).json()
    assert state["tasks"] == [task]

    # 4. Today's plan proposes the task and needs confirmation.
    plan = client.get("/v1/plans/today", headers=auth_headers).json()
    assert plan["status"] == "draft"
    assert plan["confirmation_required"] is True
    assert [item["task_id"] for item in plan["items"]] == [task["id"]]

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
    assert state_after["tasks"] == []


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
