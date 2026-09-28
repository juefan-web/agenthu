from __future__ import annotations

import pytest

from tests.fixtures.payloads import task_payload

pytestmark = pytest.mark.integration


def _task(client, headers, title: str = "HW2") -> dict:
    return client.post("/v1/tasks", json=task_payload(title=title), headers=headers).json()


def test_start_session_twice_is_idempotent(client, auth_headers) -> None:
    task = _task(client, auth_headers)
    first = client.post("/v1/focus-sessions", json={"task_id": task["id"]}, headers=auth_headers)
    second = client.post("/v1/focus-sessions", json={"task_id": task["id"]}, headers=auth_headers)
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]


def test_complete_twice_does_not_double_count(client, auth_headers) -> None:
    task = _task(client, auth_headers)
    session = client.post(
        "/v1/focus-sessions", json={"task_id": task["id"]}, headers=auth_headers
    ).json()

    first = client.patch(
        f"/v1/focus-sessions/{session['id']}",
        json={"status": "completed", "actual_minutes": 40},
        headers=auth_headers,
    ).json()
    assert first["actual_minutes"] == 40

    second = client.patch(
        f"/v1/focus-sessions/{session['id']}",
        json={"status": "completed", "actual_minutes": 40},
        headers=auth_headers,
    ).json()
    assert second["actual_minutes"] == 40
    assert second["status"] == "completed"

    task_after = client.get(f"/v1/tasks/{task['id']}", headers=auth_headers).json()
    assert task_after["actual_duration_minutes"] == 40

    # Only one focus.completed event exists for the session.
    events = client.get(
        "/v1/events", params={"type": "focus.completed"}, headers=auth_headers
    ).json()
    assert events["total"] == 1


def test_explicit_zero_actual_minutes_is_preserved(client, auth_headers) -> None:
    task = _task(client, auth_headers)
    session = client.post(
        "/v1/focus-sessions", json={"task_id": task["id"]}, headers=auth_headers
    ).json()

    completed = client.patch(
        f"/v1/focus-sessions/{session['id']}",
        json={"status": "completed", "actual_minutes": 0},
        headers=auth_headers,
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["actual_minutes"] == 0

    event = client.get(
        "/v1/events", params={"type": "focus.completed"}, headers=auth_headers
    ).json()["items"][0]
    assert event["data"]["actual_minutes"] == 0

    task_after = client.get(f"/v1/tasks/{task['id']}", headers=auth_headers).json()
    assert task_after["actual_duration_minutes"] == 0


def test_second_session_time_still_accumulates(client, auth_headers) -> None:
    """Time worked after the first completion must not be lost (C2).

    A task finished once is COMPLETED; a later focus session on the same task
    still contributes its actual minutes to the task and the confirmed plan
    item, without regressing the completion state.
    """

    task = _task(client, auth_headers)

    first = client.post(
        "/v1/focus-sessions", json={"task_id": task["id"]}, headers=auth_headers
    ).json()
    client.patch(
        f"/v1/focus-sessions/{first['id']}",
        json={"status": "completed", "actual_minutes": 30},
        headers=auth_headers,
    )
    task_after_first = client.get(f"/v1/tasks/{task['id']}", headers=auth_headers).json()
    assert task_after_first["status"] == "done"
    assert task_after_first["actual_duration_minutes"] == 30
    completed_at_first = task_after_first["completed_at"]

    second = client.post(
        "/v1/focus-sessions", json={"task_id": task["id"]}, headers=auth_headers
    ).json()
    assert second["id"] != first["id"]
    client.patch(
        f"/v1/focus-sessions/{second['id']}",
        json={"status": "completed", "actual_minutes": 25},
        headers=auth_headers,
    )

    task_after = client.get(f"/v1/tasks/{task['id']}", headers=auth_headers).json()
    # Every session's time is kept; the completion state is sticky.
    assert task_after["status"] == "done"
    assert task_after["actual_duration_minutes"] == 55
    assert task_after["completed_at"] == completed_at_first

    # The second session emitted its own focus.completed event (one per
    # session, deduplicated per session).
    events = client.get(
        "/v1/events", params={"type": "focus.completed"}, headers=auth_headers
    ).json()
    assert events["total"] == 2
    assert {event["data"]["actual_minutes"] for event in events["items"]} == {30, 25}


def test_pause_and_resume(client, auth_headers) -> None:
    task = _task(client, auth_headers)
    session = client.post(
        "/v1/focus-sessions", json={"task_id": task["id"]}, headers=auth_headers
    ).json()

    paused = client.patch(
        f"/v1/focus-sessions/{session['id']}", json={"status": "paused"}, headers=auth_headers
    ).json()
    assert paused["status"] == "paused"

    resumed = client.patch(
        f"/v1/focus-sessions/{session['id']}", json={"status": "running"}, headers=auth_headers
    ).json()
    assert resumed["status"] == "running"


def test_unknown_status_is_rejected(client, auth_headers) -> None:
    task = _task(client, auth_headers)
    session = client.post(
        "/v1/focus-sessions", json={"task_id": task["id"]}, headers=auth_headers
    ).json()
    response = client.patch(
        f"/v1/focus-sessions/{session['id']}", json={"status": "exploded"}, headers=auth_headers
    )
    assert response.status_code == 422


def test_focus_session_ownership(client, auth_factory) -> None:
    alice = auth_factory()
    bob = auth_factory()
    task = _task(client, alice)

    # Bob cannot start a session for Alice's task.
    assert (
        client.post("/v1/focus-sessions", json={"task_id": task["id"]}, headers=bob).status_code
        == 404
    )

    session = client.post("/v1/focus-sessions", json={"task_id": task["id"]}, headers=alice).json()
    assert client.get(f"/v1/focus-sessions/{session['id']}", headers=bob).status_code == 404
    assert (
        client.patch(
            f"/v1/focus-sessions/{session['id']}",
            json={"status": "completed"},
            headers=bob,
        ).status_code
        == 404
    )
