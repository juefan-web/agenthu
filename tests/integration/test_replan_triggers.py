"""Replan-suggestion trigger engine (D-031 §2, evaluation §3.3).

Confirmed plans are constructed through the ORM with explicit times so the
detection logic is tested deterministically (the planner's own placement is
covered by test_planner_v2). The engine is invoked directly — the worker cron
is a thin drain loop around it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from backend.models.enums import PlanStatus
from backend.models.plan import Plan, PlanItem
from backend.services.replan_triggers import evaluate_replan_triggers

pytestmark = pytest.mark.integration


def _make_confirmed_plan(
    db_session,
    user_id: uuid.UUID,
    *,
    task_id: uuid.UUID,
    title: str,
    planned_minutes: int,
    planned_start: datetime | None = None,
    planned_end: datetime | None = None,
) -> Plan:
    start = planned_start or datetime.now(UTC)
    end = planned_end or start + timedelta(minutes=planned_minutes)
    plan = Plan(
        user_id=user_id,
        title="Confirmed base",
        status=PlanStatus.CONFIRMED,
        basis={"strategy": "slots_v2"},
        permission_level=2,
        generated_by="deterministic_planner",
        confirmed_at=datetime.now(UTC) - timedelta(seconds=60),
    )
    plan.items.append(
        PlanItem(
            task_id=task_id,
            title=title,
            order_index=0,
            planned_start=start,
            planned_end=end,
            planned_minutes=planned_minutes,
        )
    )
    db_session.add(plan)
    db_session.flush()
    return plan


def _me(client, headers) -> uuid.UUID:
    return uuid.UUID(client.get("/v1/auth/me", headers=headers).json()["id"])


def _suggestions(client, headers) -> list[dict]:
    return [
        plan
        for plan in client.get("/v1/plans?status=draft&limit=200", headers=headers).json()["items"]
        if plan["replaces_plan_id"] is not None
    ]


def test_overrun_creates_suggestion_and_protects_confirmed(
    client, auth_headers, db_session
) -> None:
    task = client.post(
        "/v1/tasks",
        json={"title": "线性代数作业", "estimated_duration_minutes": 75},
        headers=auth_headers,
    ).json()
    plan = _make_confirmed_plan(
        db_session,
        _me(client, auth_headers),
        task_id=uuid.UUID(task["id"]),
        title="线性代数作业",
        planned_minutes=75,
    )
    session = client.post(
        "/v1/focus-sessions", json={"task_id": task["id"]}, headers=auth_headers
    ).json()
    client.patch(
        f"/v1/focus-sessions/{session['id']}",
        json={"status": "completed", "actual_minutes": 100, "deviation_note": "超时"},
        headers=auth_headers,
    )

    suggestion = evaluate_replan_triggers(db_session, user_id=_me(client, auth_headers))
    assert suggestion is not None
    assert suggestion.status == PlanStatus.DRAFT
    assert suggestion.replaces_plan_id == plan.id
    assert "100" in (suggestion.replan_reason or "")
    assert suggestion.basis["trigger"] == "focus_overrun"
    # L4 protection: acceptance is the only path that retires the plan.
    assert plan.status == PlanStatus.CONFIRMED

    # Idempotent per signature: the consumed fact is not re-detected, so
    # re-evaluation yields nothing new and nothing stacks.
    assert evaluate_replan_triggers(db_session, user_id=_me(client, auth_headers)) is None
    assert len(_suggestions(client, auth_headers)) == 1


def test_new_task_trigger_after_confirmation(client, auth_headers, db_session) -> None:
    first = client.post(
        "/v1/tasks", json={"title": "First", "estimated_duration_minutes": 30}, headers=auth_headers
    ).json()
    _make_confirmed_plan(
        db_session,
        _me(client, auth_headers),
        task_id=uuid.UUID(first["id"]),
        title="First",
        planned_minutes=30,
    )
    # A near-deadline task arriving after confirmation (manual here; the
    # derivation path marks dirty the same way).
    client.post(
        "/v1/tasks",
        json={
            "title": "急件作业",
            "deadline": (datetime.now(UTC) + timedelta(hours=20)).isoformat(),
        },
        headers=auth_headers,
    )

    suggestion = evaluate_replan_triggers(db_session, user_id=_me(client, auth_headers))
    assert suggestion is not None
    assert suggestion.basis["trigger"] == "new_task"
    assert "急件作业" in (suggestion.replan_reason or "")


def test_rate_limit_without_at_risk_then_exemption(client, auth_headers, db_session) -> None:
    user_id = _me(client, auth_headers)
    task_a = client.post(
        "/v1/tasks", json={"title": "A", "estimated_duration_minutes": 75}, headers=auth_headers
    ).json()
    plan_a = _make_confirmed_plan(
        db_session, user_id, task_id=uuid.UUID(task_a["id"]), title="A", planned_minutes=75
    )
    focus = client.post(
        "/v1/focus-sessions", json={"task_id": task_a["id"]}, headers=auth_headers
    ).json()
    client.patch(
        f"/v1/focus-sessions/{focus['id']}",
        json={"status": "completed", "actual_minutes": 100},
        headers=auth_headers,
    )
    first = evaluate_replan_triggers(db_session, user_id=user_id)
    assert first is not None

    # A different trigger inside the 30-minute window, no deadline at risk:
    # suppressed by the rate limit.
    client.post(
        "/v1/tasks",
        json={
            "title": "Second trigger",
            "deadline": (datetime.now(UTC) + timedelta(hours=20)).isoformat(),
        },
        headers=auth_headers,
    )
    assert evaluate_replan_triggers(db_session, user_id=user_id) is None

    # At-risk (an overdue task) lifts the rate limit; the stale suggestion is
    # retired rather than stacked (#22 review note 3).
    client.post(
        "/v1/tasks",
        json={
            "title": "Overdue",
            "deadline": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
        },
        headers=auth_headers,
    )
    second = evaluate_replan_triggers(db_session, user_id=user_id)
    assert second is not None and second.id != first.id
    db_session.refresh(first)
    assert first.status == PlanStatus.CANCELLED
    assert plan_a.status == PlanStatus.CONFIRMED  # still never mutated


def test_slot_passed_trigger(client, auth_headers, db_session) -> None:
    user_id = _me(client, auth_headers)
    task = client.post(
        "/v1/tasks",
        json={"title": "Missed slot", "estimated_duration_minutes": 30},
        headers=auth_headers,
    ).json()
    _make_confirmed_plan(
        db_session,
        user_id,
        task_id=uuid.UUID(task["id"]),
        title="Missed slot",
        planned_minutes=30,
        planned_start=datetime.now(UTC) - timedelta(hours=2),
        planned_end=datetime.now(UTC) - timedelta(hours=1),
    )
    suggestion = evaluate_replan_triggers(db_session, user_id=user_id)
    assert suggestion is not None
    assert suggestion.basis["trigger"] == "slot_passed"
    assert "已过" in (suggestion.replan_reason or "")


def test_schedule_change_trigger(client, auth_headers, db_session) -> None:
    user_id = _me(client, auth_headers)
    task = client.post(
        "/v1/tasks",
        json={"title": "Planned", "estimated_duration_minutes": 30},
        headers=auth_headers,
    ).json()
    _make_confirmed_plan(
        db_session, user_id, task_id=uuid.UUID(task["id"]), title="Planned", planned_minutes=30
    )
    now = datetime.now(UTC).isoformat()
    client.post(
        "/v1/events",
        json={
            "client_event_id": f"trig:{uuid.uuid4().hex}",
            "type": "time.schedule.entry",
            "occurred_at": now,
            "source": "onethu",
            "data": {
                "course_name": "新课",
                "date": datetime.now(UTC).strftime("%Y-%m-%d"),
                "start_time": "16:00",
                "end_time": "17:40",
            },
            "context": {},
            "provenance": {
                "connector": "onethu",
                "connector_version": "test",
                "upstream_id": f"trig:{uuid.uuid4().hex}",
                "semantic_version": "v1",
                "fetched_at": now,
            },
        },
        headers=auth_headers,
    )
    suggestion = evaluate_replan_triggers(db_session, user_id=user_id)
    assert suggestion is not None
    assert suggestion.basis["trigger"] == "schedule_change"


def test_no_confirmed_plan_means_no_suggestion(client, auth_headers, db_session) -> None:
    task = client.post(
        "/v1/tasks", json={"title": "Free", "estimated_duration_minutes": 30}, headers=auth_headers
    ).json()
    focus = client.post(
        "/v1/focus-sessions", json={"task_id": task["id"]}, headers=auth_headers
    ).json()
    client.patch(
        f"/v1/focus-sessions/{focus['id']}",
        json={"status": "completed", "actual_minutes": 90},
        headers=auth_headers,
    )
    assert evaluate_replan_triggers(db_session, user_id=_me(client, auth_headers)) is None


def test_dirty_marker_roundtrip() -> None:
    from backend.worker.enqueue import drain_dirty_users, mark_user_dirty

    marker = uuid.uuid4()
    if not mark_user_dirty(marker):
        pytest.skip("Redis is not available")
    drained = drain_dirty_users(limit=1000)
    assert str(marker) in drained
