"""M4 basis-gap slice (coordinator ruling 2026-10-04; A contract §7,
B contract §5, B4①).

Three producers the frozen contracts promised but A2/A3 never landed:
1. the deterministic planner/replan writes a structured DecisionBasis under
   ``Plan.basis.agent_decision`` citing what the placement consumed;
2. deleting a message (or archiving its session) flips every stored
   reference citing it to ``source_deleted`` in the same transaction —
   the client never guesses a dead source;
3. chat runs cite their triggering message as a ``chat_message``
   reference — id + occurred_at locator, never the content.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from backend.adapters.model_provider.base import ModelTurn, ToolCall
from backend.config import get_settings
from backend.db.base import utcnow
from backend.models.agent import AgentRun, PendingAction
from backend.models.enums import PlanStatus
from backend.models.event import Event
from backend.models.plan import Plan, PlanItem
from backend.services.agent_runner import execute_run
from backend.services.model_consent import set_consent
from backend.services.planner import generate_plan
from backend.services.replan_triggers import evaluate_replan_triggers
from tests.integration.test_m4_runtime import FakeToolProvider, _send_chat_message

pytestmark = pytest.mark.integration


def _me(client, headers) -> uuid.UUID:
    return uuid.UUID(client.get("/v1/auth/me", headers=headers).json()["id"])


def _local_day_start(now: datetime) -> datetime:
    """08:00 local today as UTC — a deterministic placement start with the
    whole day ahead, whatever the wall clock is (#56 full-calendar-day
    lesson)."""

    timezone = ZoneInfo(get_settings().default_timezone)
    local = now.astimezone(timezone).replace(hour=8, minute=0, second=0, microsecond=0)
    return local.astimezone(UTC)


def _refs_by_kind(document: dict | None, kind: str) -> list[dict]:
    if document is None:
        return []
    return [r for r in document.get("references", []) if r.get("kind") == kind]


# ------------------------------------------------- planner agent_decision --


def test_generated_plan_carries_agent_decision(client, auth_headers, db_session) -> None:
    user_id = _me(client, auth_headers)
    task = client.post(
        "/v1/tasks",
        json={"title": "线性代数复习", "estimated_duration_minutes": 30},
        headers=auth_headers,
    ).json()

    plan = generate_plan(
        db_session, user_id=user_id, start_at=_local_day_start(utcnow()), status=PlanStatus.DRAFT
    )
    decision = plan.basis["agent_decision"]
    assert decision["basis_version"] == "v1"
    assert decision["summary"]
    assert decision["rule_versions"] == {"planner": "slots_v2"}
    assert decision["selected_tool_call_ids"] == []

    task_refs = _refs_by_kind(decision, "task")
    assert any(r["id"] == task["id"] and r["label"] == "线性代数复习" for r in task_refs)
    state_refs = _refs_by_kind(decision, "current_state")
    assert len(state_refs) == 1
    assert isinstance(state_refs[0]["locator"]["state_version"], int)

    # The legacy keys BasisPanel reads keep their original positions.
    assert plan.basis["strategy"] == "slots_v2"
    assert str(task["id"]) in plan.basis["task_ids"]


def test_replan_suggestion_carries_agent_decision(client, auth_headers, db_session) -> None:
    user_id = _me(client, auth_headers)
    overrun = client.post(
        "/v1/tasks",
        json={"title": "线性代数作业", "estimated_duration_minutes": 75},
        headers=auth_headers,
    ).json()
    # The suggestion needs something placeable: the overrun task itself is
    # fully consumed (75 planned, 100 actual), so a second pending task is
    # what the new plan schedules — and cites.
    client.post(
        "/v1/tasks",
        json={"title": "英语听力", "estimated_duration_minutes": 30},
        headers=auth_headers,
    )
    confirmed = Plan(
        user_id=user_id,
        title="Confirmed base",
        status=PlanStatus.CONFIRMED,
        basis={"strategy": "slots_v2"},
        permission_level=2,
        generated_by="deterministic_planner",
        confirmed_at=utcnow() - timedelta(seconds=60),
    )
    confirmed.items.append(
        PlanItem(
            task_id=uuid.UUID(overrun["id"]),
            title="线性代数作业",
            order_index=0,
            planned_start=datetime.now(UTC),
            planned_end=datetime.now(UTC) + timedelta(minutes=75),
            planned_minutes=75,
        )
    )
    db_session.add(confirmed)
    db_session.flush()
    focus = client.post(
        "/v1/focus-sessions", json={"task_id": overrun["id"]}, headers=auth_headers
    ).json()
    patched = client.patch(
        f"/v1/focus-sessions/{focus['id']}",
        json={"status": "completed", "actual_minutes": 100, "deviation_note": "超时"},
        headers=auth_headers,
    )
    assert patched.status_code == 200, patched.text

    suggestion = evaluate_replan_triggers(db_session, user_id=user_id)
    assert suggestion is not None
    decision = suggestion.basis["agent_decision"]
    # The human reason IS the decision summary; the trigger legacy keys the
    # engine dedupes on stay where they were.
    assert decision["summary"] == suggestion.replan_reason
    assert suggestion.basis["trigger_signature"].startswith("overrun:")
    assert _refs_by_kind(decision, "task")
    assert _refs_by_kind(decision, "current_state")


def test_schedule_events_cited_in_plan_basis(client, auth_headers, db_session) -> None:
    user_id = _me(client, auth_headers)
    db_session.add(
        Event(
            user_id=user_id,
            type="time.schedule.entry",
            timestamp=utcnow(),
            source="test",
            data={"course_name": "线性代数", "location": "六教"},
            provenance={"connector": "test", "upstream_id": "sec-gap-1"},
        )
    )
    db_session.flush()

    plan = generate_plan(
        db_session, user_id=user_id, start_at=_local_day_start(utcnow()), status=PlanStatus.DRAFT
    )
    event_refs = _refs_by_kind(plan.basis["agent_decision"], "event")
    assert any("线性代数" in r["label"] for r in event_refs)
    assert all(r["locator"]["occurred_at"] for r in event_refs)


# ------------------------------------------------- chat_message producer --


def _chat_run_with_task_create(client, auth_headers, db_session) -> tuple[dict, AgentRun]:
    """A settled chat run whose L2 pending action cites the trigger message."""

    user_id = _me(client, auth_headers)
    set_consent(db_session, user_id, enabled=True, consent_text_version="v1")
    sent = _send_chat_message(client, auth_headers, content="把线性代数作业加入今天日程")
    provider = FakeToolProvider(
        [
            ModelTurn(
                tool_calls=[
                    ToolCall(
                        call_id="c1",
                        name="task.create",
                        arguments_json=json.dumps(
                            {"title": "复习线代", "estimated_duration_minutes": 45}
                        ),
                    )
                ]
            ),
            ModelTurn(text="已为你创建待确认任务。"),
        ]
    )
    run = asyncio.run(execute_run(db_session, run_id=uuid.UUID(sent["run_id"]), provider=provider))
    assert run is not None and run.status == "WAITING_CONFIRMATION"
    return sent, run


def test_chat_run_cites_triggering_message(client, auth_headers, db_session) -> None:
    sent, run = _chat_run_with_task_create(client, auth_headers, db_session)
    chat_refs = _refs_by_kind(run.decision_basis, "chat_message")
    assert len(chat_refs) == 1
    reference = chat_refs[0]
    assert reference["id"] == sent["user_message_id"]
    assert reference["locator"]["message_id"] == sent["user_message_id"]
    assert reference["locator"]["occurred_at"]
    assert reference["label"] == "对话消息"  # locator only — never the content

    state_refs = _refs_by_kind(run.decision_basis, "current_state")
    assert isinstance(state_refs[0]["locator"]["state_version"], int)
    assert "version" not in state_refs[0]  # B4②: rides the locator, not top-level

    # The pending action inherits the same citing references (§2 display face).
    action = db_session.scalar(select(PendingAction).where(PendingAction.agent_run_id == run.id))
    assert action is not None
    assert any(
        r.get("id") == sent["user_message_id"] for r in _refs_by_kind(action.basis, "chat_message")
    )


# ---------------------------------------------------- source_deleted flip --


def test_delete_message_flips_citing_references(client, auth_headers, db_session) -> None:
    sent, run = _chat_run_with_task_create(client, auth_headers, db_session)
    deleted = client.delete(f"/v1/chat/messages/{sent['user_message_id']}", headers=auth_headers)
    assert deleted.status_code == 204

    read = client.get(f"/v1/agent/runs/{run.id}", headers=auth_headers).json()
    chat_refs = _refs_by_kind(read["decision_basis"], "chat_message")
    assert chat_refs and chat_refs[0]["state"] == "source_deleted"
    action = db_session.scalar(select(PendingAction).where(PendingAction.agent_run_id == run.id))
    assert _refs_by_kind(action.basis, "chat_message")[0]["state"] == "source_deleted"


def test_archive_session_flips_citing_references(client, auth_headers, db_session) -> None:
    sent, run = _chat_run_with_task_create(client, auth_headers, db_session)
    deleted = client.delete(f"/v1/chat/sessions/{sent['session_id']}", headers=auth_headers)
    assert deleted.status_code == 204

    read = client.get(f"/v1/agent/runs/{run.id}", headers=auth_headers).json()
    chat_refs = _refs_by_kind(read["decision_basis"], "chat_message")
    assert chat_refs and chat_refs[0]["state"] == "source_deleted"


def test_delete_is_idempotent_for_flipped_references(client, auth_headers, db_session) -> None:
    sent, run = _chat_run_with_task_create(client, auth_headers, db_session)
    first = client.delete(f"/v1/chat/messages/{sent['user_message_id']}", headers=auth_headers)
    second = client.delete(f"/v1/chat/messages/{sent['user_message_id']}", headers=auth_headers)
    assert first.status_code == 204 and second.status_code == 204

    read = client.get(f"/v1/agent/runs/{run.id}", headers=auth_headers).json()
    chat_refs = _refs_by_kind(read["decision_basis"], "chat_message")
    assert chat_refs and chat_refs[0]["state"] == "source_deleted"
