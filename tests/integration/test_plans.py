from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tests.fixtures.payloads import task_payload

pytestmark = pytest.mark.integration


def _make_task(client, headers, *, title: str, days: int) -> dict:
    return client.post(
        "/v1/tasks",
        json=task_payload(title=title, deadline=datetime.now(UTC) + timedelta(days=days)),
        headers=headers,
    ).json()


def test_manual_plan_create_read_confirm_cancel(client, auth_headers) -> None:
    created = client.post(
        "/v1/plans",
        json={
            "title": "Tonight",
            "permission_level": 2,
            "basis": {"reason": "user created"},
            "items": [{"title": "Read chapter 2", "order_index": 0, "planned_minutes": 45}],
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    plan = created.json()
    assert plan["status"] == "draft"
    assert plan["confirmation_required"] is True
    assert plan["generated_at"] is not None
    assert len(plan["items"]) == 1

    fetched = client.get(f"/v1/plans/{plan['id']}", headers=auth_headers)
    assert fetched.status_code == 200

    confirmed = client.post(f"/v1/plans/{plan['id']}/confirm", headers=auth_headers)
    assert confirmed.json()["status"] == "confirmed"
    assert confirmed.json()["confirmation_required"] is False

    other = client.post(
        "/v1/plans", json={"title": "Draft", "items": []}, headers=auth_headers
    ).json()
    cancelled = client.post(f"/v1/plans/{other['id']}/cancel", headers=auth_headers)
    assert cancelled.json()["status"] == "superseded"


def test_generate_plan_orders_by_deadline(client, auth_headers) -> None:
    _make_task(client, auth_headers, title="Later", days=3)
    _make_task(client, auth_headers, title="Sooner", days=1)

    generated = client.post("/v1/plans/generate", json={}, headers=auth_headers)
    assert generated.status_code == 201, generated.text
    plan = generated.json()
    assert plan["status"] == "draft"
    assert plan["confirmation_required"] is True
    assert [item["title"] for item in plan["items"]] == ["Sooner", "Later"]
    assert plan["basis"]["strategy"] == "deadline_then_priority"
    # Client plan items require present start/end/reason.
    for item in plan["items"]:
        assert item["task_id"] is not None
        assert item["start_at"] is not None
        assert item["end_at"] is not None
        assert item["reason"]


def test_today_plan_generates_when_missing(client, auth_headers) -> None:
    _make_task(client, auth_headers, title="HW2", days=1)
    today = client.get("/v1/plans/today", headers=auth_headers)
    assert today.status_code == 200, today.text
    body = today.json()
    assert body["status"] == "draft"
    assert len(body["items"]) == 1


def test_today_plan_is_idempotent(client, auth_headers) -> None:
    _make_task(client, auth_headers, title="HW2", days=1)
    first = client.get("/v1/plans/today", headers=auth_headers).json()
    second = client.get("/v1/plans/today", headers=auth_headers).json()
    assert first["id"] == second["id"]

    plans = client.get("/v1/plans", headers=auth_headers).json()
    assert plans["total"] == 1


def test_replan_supersedes_previous_plan(client, auth_headers) -> None:
    _make_task(client, auth_headers, title="HW2", days=1)
    plan = client.post("/v1/plans/generate", json={}, headers=auth_headers).json()
    client.post(f"/v1/plans/{plan['id']}/confirm", headers=auth_headers)

    replanned = client.post(
        f"/v1/plans/{plan['id']}/replan",
        json={"reason": "Finished earlier than expected", "horizon_minutes": 180},
        headers=auth_headers,
    )
    assert replanned.status_code == 201, replanned.text
    new_plan = replanned.json()
    assert new_plan["replan_reason"] == "Finished earlier than expected"

    original = client.get(f"/v1/plans/{plan['id']}", headers=auth_headers).json()
    assert original["status"] == "superseded"


def test_replan_rejects_terminal_plans(client, auth_headers) -> None:
    _make_task(client, auth_headers, title="HW2", days=1)
    plan = client.post("/v1/plans/generate", json={}, headers=auth_headers).json()
    client.post(f"/v1/plans/{plan['id']}/replan", json={"reason": "first"}, headers=auth_headers)

    superseded = client.get(f"/v1/plans/{plan['id']}", headers=auth_headers).json()
    assert superseded["status"] == "superseded"

    response = client.post(
        f"/v1/plans/{plan['id']}/replan", json={"reason": "again"}, headers=auth_headers
    )
    assert response.status_code == 409


def test_plan_item_update(client, auth_headers) -> None:
    plan = client.post(
        "/v1/plans",
        json={"title": "Plan", "items": [{"title": "Step 1", "order_index": 0}]},
        headers=auth_headers,
    ).json()
    item_id = plan["items"][0]["id"]
    response = client.patch(
        f"/v1/plans/{plan['id']}/items/{item_id}",
        json={"status": "COMPLETED", "actual_minutes": 40},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["items"][0]["status"] == "COMPLETED"
    assert response.json()["items"][0]["actual_minutes"] == 40


def test_confirming_unknown_plan_is_404(client, auth_headers) -> None:
    response = client.post(
        "/v1/plans/00000000-0000-0000-0000-000000000000/confirm", headers=auth_headers
    )
    assert response.status_code == 404


def test_plan_cannot_reference_other_users_task(client, auth_factory) -> None:
    alice = auth_factory()
    bob = auth_factory()
    task = _make_task(client, alice, title="Alice HW", days=1)

    response = client.post(
        "/v1/plans",
        json={"title": "Bob plan", "items": [{"title": "x", "task_id": task["id"]}]},
        headers=bob,
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_plan_isolation_between_users(client, auth_factory) -> None:
    alice = auth_factory()
    bob = auth_factory()
    plan = client.post("/v1/plans", json={"title": "Alice plan", "items": []}, headers=alice).json()
    assert client.get(f"/v1/plans/{plan['id']}", headers=bob).status_code == 404
