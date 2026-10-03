"""M4-A3 retrieval + proactive wiring regression set.

A3's faces: chat DELETEs (soft, idempotent-204, session archive cascades
message soft-deletes — retrieval eligibility drops in the same
transaction); in-session search (CJK substring via pg_trgm GIN, sub-3-char
degrade still correct, wildcards literal, keyset stable); proactive run
queueing (one run per trigger signature, ever) and its deterministic
settlement (zero provider calls; notify.push pending action — grant →
auto-execute, no grant → PENDING card); the §6/§8 disturbance budget
(category gate -> quiet hours -> per-local-day budget, midnight-crossing
windows legal, suppression is honest policy, not failure).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from backend.db.base import utcnow
from backend.models.agent import AgentRun, PendingAction
from backend.models.audit import AuditLog
from backend.models.chat import ChatMessage, ChatSession
from backend.models.enums import PlanStatus
from backend.models.notification import NotificationPreference
from backend.models.permission import PermissionGrant
from backend.models.plan import Plan, PlanItem
from backend.models.task import Task
from backend.services.agent_runner import execute_run, queue_proactive_run
from backend.services.notification_delivery import settle_and_deliver
from backend.services.replan_triggers import evaluate_replan_triggers

pytestmark = pytest.mark.integration

_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _me(client, headers) -> uuid.UUID:
    return uuid.UUID(client.get("/v1/auth/me", headers=headers).json()["id"])


def _session(client, headers, title: str = "检索测试") -> dict:
    created = client.post("/v1/chat/sessions", json={"title": title}, headers=headers)
    assert created.status_code == 201, created.text
    return created.json()


def _send(client, headers, session_id: str, content: str) -> dict:
    sent = client.post(
        f"/v1/chat/sessions/{session_id}/messages",
        json={"content": content, "client_message_id": str(uuid.uuid4())},
        headers=headers,
    )
    assert sent.status_code == 202, sent.text
    return sent.json()


def _messages(client, headers, session_id: str) -> list[dict]:
    listed = client.get(f"/v1/chat/sessions/{session_id}/messages", headers=headers)
    assert listed.status_code == 200, listed.text
    return listed.json()["items"]


def _search(client, headers, session_id: str, q: str, **params) -> dict:
    found = client.get(
        f"/v1/chat/sessions/{session_id}/messages/search",
        params={"q": q, **params},
        headers=headers,
    )
    assert found.status_code == 200, found.text
    return found.json()


def _prefs(db_session, user_id: uuid.UUID, **overrides) -> NotificationPreference:
    row = NotificationPreference(
        user_id=user_id,
        enabled_categories=overrides.get("enabled_categories", ["replan"]),
        daily_budget=overrides.get("daily_budget", 3),
        timezone=overrides.get("timezone", "Asia/Shanghai"),
        quiet_hours_start=overrides.get("quiet_hours_start"),
        quiet_hours_end=overrides.get("quiet_hours_end"),
    )
    db_session.add(row)
    db_session.flush()
    return row


def _notify_grant(db_session, user_id: uuid.UUID, categories: list[str]) -> PermissionGrant:
    grant = PermissionGrant(
        user_id=user_id,
        action="notify.push",
        level=3,
        scope={"categories": categories, "channels": ["web"]},
    )
    db_session.add(grant)
    db_session.flush()
    return grant


def _seed_at_risk_deadline(db_session, user_id: uuid.UUID) -> None:
    """A pending task whose deadline already passed — the engine's rate
    limiter exempts deadline-at-risk users (D-031 §2), so back-to-back
    triggers in one test are all allowed to fire."""

    db_session.add(
        Task(user_id=user_id, title="已过期任务", deadline=utcnow() - timedelta(hours=1))
    )
    db_session.flush()


def _overrun_suggestion(db_session, client, headers, user_id: uuid.UUID) -> Plan:
    """Fire a real focus_overrun trigger (same seeding as the engine tests)."""

    task = client.post(
        "/v1/tasks",
        json={"title": "线性代数作业", "estimated_duration_minutes": 75},
        headers=headers,
    ).json()
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
            task_id=uuid.UUID(task["id"]),
            title="线性代数作业",
            order_index=0,
            planned_start=datetime.now(UTC),
            planned_end=datetime.now(UTC) + timedelta(minutes=75),
            planned_minutes=75,
        )
    )
    db_session.add(plan)
    db_session.flush()
    focus = client.post("/v1/focus-sessions", json={"task_id": task["id"]}, headers=headers).json()
    patched = client.patch(
        f"/v1/focus-sessions/{focus['id']}",
        json={"status": "completed", "actual_minutes": 100, "deviation_note": "超时"},
        headers=headers,
    )
    assert patched.status_code == 200, patched.text
    suggestion = evaluate_replan_triggers(db_session, user_id=user_id)
    assert suggestion is not None
    return suggestion


# ------------------------------------------------------------- DELETE face --


def test_delete_message_drops_retrieval_eligibility(
    client, auth_headers, auth_factory, db_session
) -> None:
    session = _session(client, auth_headers)
    _send(client, auth_headers, session["id"], "二次方程的解法复习")
    _send(client, auth_headers, session["id"], "英语单词背诵计划")
    assert len(_messages(client, auth_headers, session["id"])) == 2
    assert len(_search(client, auth_headers, session["id"], "解法")["items"]) == 1

    target = _messages(client, auth_headers, session["id"])[0]
    assert (
        client.delete(f"/v1/chat/messages/{target['id']}", headers=auth_headers).status_code == 204
    )
    # Idempotent-204, like the grant revoke.
    assert (
        client.delete(f"/v1/chat/messages/{target['id']}", headers=auth_headers).status_code == 204
    )

    remaining = _messages(client, auth_headers, session["id"])
    assert [m["content"] for m in remaining] == ["英语单词背诵计划"]
    assert _search(client, auth_headers, session["id"], "解法")["items"] == []
    assert len(_search(client, auth_headers, session["id"], "单词")["items"]) == 1

    # Cross-user isolation stays a 404, not a 403 (existence is not leaked).
    other = auth_factory()
    survivor = _messages(client, auth_headers, session["id"])[0]
    assert client.delete(f"/v1/chat/messages/{survivor['id']}", headers=other).status_code == 404


def test_delete_session_archives_and_cascades_soft_delete(client, auth_headers, db_session) -> None:
    session = _session(client, auth_headers, title="级联测试")
    _send(client, auth_headers, session["id"], "第一条消息")
    _send(client, auth_headers, session["id"], "第二条消息")

    assert (
        client.delete(f"/v1/chat/sessions/{session['id']}", headers=auth_headers).status_code == 204
    )
    assert (
        client.delete(f"/v1/chat/sessions/{session['id']}", headers=auth_headers).status_code == 204
    )

    # Gone from the user's view everywhere at once.
    listed = client.get("/v1/chat/sessions", headers=auth_headers).json()["items"]
    assert all(s["id"] != session["id"] for s in listed)
    assert client.get(f"/v1/chat/sessions/{session['id']}", headers=auth_headers).status_code == 404
    assert (
        client.get(f"/v1/chat/sessions/{session['id']}/messages", headers=auth_headers).status_code
        == 404
    )
    assert (
        client.get(
            f"/v1/chat/sessions/{session['id']}/messages/search",
            params={"q": "消息"},
            headers=auth_headers,
        ).status_code
        == 404
    )

    # The cascade really soft-deleted both messages in the same transaction
    # — no retrieval path can resurrect them.
    session_id = uuid.UUID(session["id"])
    rows = db_session.scalars(select(ChatMessage).where(ChatMessage.session_id == session_id)).all()
    assert len(rows) == 2
    assert all(row.deleted_at is not None for row in rows)
    assert db_session.get(ChatSession, session_id).archived_at is not None


# ------------------------------------------------------------- search face --


def test_search_cjk_substring_short_degrade_wildcards_keyset(client, auth_headers) -> None:
    session = _session(client, auth_headers, title="搜索测试")
    for content in (
        "线性代数第三章重点",
        "概率论的中心极限定理",
        "线性代数习题课笔记",
        "完成率100%的项目复盘",
    ):
        _send(client, auth_headers, session["id"], content)

    # 3+ chars: trgm-indexable substring, newest-first.
    hits = _search(client, auth_headers, session["id"], "线性代数")
    assert hits["total"] == 2
    assert [m["content"] for m in hits["items"]] == [
        "线性代数习题课笔记",
        "线性代数第三章重点",
    ]

    # 1 char: no trigram, degrades to an unindexed filter — still correct.
    assert _search(client, auth_headers, session["id"], "线")["total"] == 2

    # Wildcards are literal (autoescape), not patterns.
    assert _search(client, auth_headers, session["id"], "100%")["total"] == 1
    assert _search(client, auth_headers, session["id"], "%线性%")["total"] == 0

    # Keyset pagination is stable under the newest-first ordering.
    page1 = _search(client, auth_headers, session["id"], "线性代数", limit=1)
    assert len(page1["items"]) == 1 and page1["next_cursor"] is not None
    page2 = _search(
        client,
        auth_headers,
        session["id"],
        "线性代数",
        limit=1,
        cursor=page1["next_cursor"],
    )
    assert len(page2["items"]) == 1
    assert {page1["items"][0]["id"], page2["items"][0]["id"]} == {m["id"] for m in hits["items"]}

    # Malformed queries fail closed.
    assert (
        client.get(
            f"/v1/chat/sessions/{session['id']}/messages/search",
            params={"q": "   "},
            headers=auth_headers,
        ).status_code
        == 422
    )
    assert (
        client.get(
            f"/v1/chat/sessions/{session['id']}/messages/search",
            params={"q": "x" * 201},
            headers=auth_headers,
        ).status_code
        == 422
    )


def test_search_other_users_session_is_404(client, auth_headers, auth_factory) -> None:
    session = _session(client, auth_headers)
    _send(client, auth_headers, session["id"], "隔离检查")
    assert (
        client.get(
            f"/v1/chat/sessions/{session['id']}/messages/search",
            params={"q": "隔离"},
            headers=auth_factory(),
        ).status_code
        == 404
    )


# ------------------------------------------------------- proactive wiring --


def test_queue_proactive_run_dedup_per_signature(db_session, client, auth_headers) -> None:
    user_id = _me(client, auth_headers)
    first = queue_proactive_run(
        db_session,
        user_id=user_id,
        trigger_kind="replan_trigger",
        trigger_signature="overrun:item1:100",
    )
    assert first is not None
    assert first.invocation_kind == "proactive_trigger"
    assert first.operation_key == "trigger:overrun:item1:100"
    assert first.trigger_ref["trigger_signature"] == "overrun:item1:100"
    assert first.status == "QUEUED"

    # Same signature: never a second run — not now, not after the first
    # settles (the operation-key unique is forever, not active-only).
    assert (
        queue_proactive_run(
            db_session,
            user_id=user_id,
            trigger_kind="replan_trigger",
            trigger_signature="overrun:item1:100",
        )
        is None
    )
    first.status = "SUCCEEDED"
    db_session.flush()
    assert (
        queue_proactive_run(
            db_session,
            user_id=user_id,
            trigger_kind="replan_trigger",
            trigger_signature="overrun:item1:100",
        )
        is None
    )

    # A different signature is a different operation.
    second = queue_proactive_run(
        db_session,
        user_id=user_id,
        trigger_kind="replan_trigger",
        trigger_signature="new_task:task-2",
    )
    assert second is not None and second.id != first.id


def test_engine_trigger_queues_run_and_refire_dedups(db_session, client, auth_headers) -> None:
    user_id = _me(client, auth_headers)
    suggestion = _overrun_suggestion(db_session, client, auth_headers, user_id)
    signature = suggestion.basis["trigger_signature"]

    run = queue_proactive_run(
        db_session,
        user_id=user_id,
        trigger_kind="replan_trigger",
        trigger_signature=signature,
    )
    assert run is not None
    # The drain's second pass: the engine consumed the fact (no new
    # suggestion), and even if it hadn't, the run queue is signature-deduped.
    assert evaluate_replan_triggers(db_session, user_id=user_id) is None
    assert (
        queue_proactive_run(
            db_session,
            user_id=user_id,
            trigger_kind="replan_trigger",
            trigger_signature=signature,
        )
        is None
    )
    runs = db_session.scalars(
        select(AgentRun).where(
            AgentRun.user_id == user_id,
            AgentRun.invocation_kind == "proactive_trigger",
        )
    ).all()
    assert len(runs) == 1


def test_proactive_settlement_pending_without_grant_then_confirm_suppressed(
    db_session, client, auth_headers
) -> None:
    user_id = _me(client, auth_headers)
    suggestion = _overrun_suggestion(db_session, client, auth_headers, user_id)
    run = queue_proactive_run(
        db_session,
        user_id=user_id,
        trigger_kind="replan_trigger",
        trigger_signature=suggestion.basis["trigger_signature"],
    )
    assert run is not None

    executed = asyncio.run(execute_run(db_session, run_id=run.id, provider=None))
    assert executed is not None
    executed_result = executed.result
    assert executed_result is not None
    assert executed.status == "WAITING_CONFIRMATION"
    assert executed_result["degraded"] is False
    assert "100" in executed_result["summary"]  # cites the trigger's reason
    # Deterministic by design: no provider was ever constructed, let alone
    # called — the consent gate is never engaged on this path.
    assert executed.provider == {"name": "deterministic", "model": "none", "capability": "none"}

    action = db_session.scalar(select(PendingAction).where(PendingAction.agent_run_id == run.id))
    assert action is not None
    assert action.tool_name == "notify.push"
    assert action.status == "PENDING"  # no grant -> explicit confirmation
    assert action.args["category"] == "replan"

    # User confirms; delivery then honestly settles against factory prefs
    # (nothing enabled) — suppressed is policy, so the action SUCCEEDS with
    # an honest summary, and the audit ledger carries the reason.
    confirmed = client.post(
        f"/v1/pending-actions/{action.id}/confirm",
        json={"expected_version": action.version, "mutation_id": "m-replan-1"},
        headers=auth_headers,
    )
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert body["status"] == "SUCCEEDED"
    assert "suppressed" in body["result"]["summary"]
    suppressed = db_session.scalars(
        select(AuditLog).where(
            AuditLog.user_id == user_id, AuditLog.action == "notification.suppressed"
        )
    ).all()
    assert any(a.details.get("reason") == "category_disabled" for a in suppressed)


def test_proactive_with_grant_auto_executes_and_budget_settles_then_exhausts(
    db_session, client, auth_headers
) -> None:
    user_id = _me(client, auth_headers)
    # Deadline-at-risk exempts the engine rate limiter so three triggers can
    # fire back-to-back inside one test (D-031 §2).
    _seed_at_risk_deadline(db_session, user_id)
    prefs = _prefs(db_session, user_id, enabled_categories=["replan"], daily_budget=2)
    _notify_grant(db_session, user_id, categories=["replan"])

    summaries = []
    for index in range(3):
        _overrun_suggestion(db_session, client, auth_headers, user_id)
        run = queue_proactive_run(
            db_session,
            user_id=user_id,
            trigger_kind="replan_trigger",
            trigger_signature=f"sig-{index}",
        )
        assert run is not None
        asyncio.run(execute_run(db_session, run_id=run.id, provider=None))
        action = db_session.scalar(
            select(PendingAction).where(PendingAction.agent_run_id == run.id)
        )
        assert action is not None
        assert action.status == "SUCCEEDED"  # grant auto-executed all three
        summaries.append((action.result or {}).get("summary", ""))
        db_session.refresh(prefs)

    assert prefs.sent_count == 2  # budget 2: third was refused, not charged
    assert prefs.last_sent_at is not None
    assert "delivered" in summaries[0] and "delivered" in summaries[1]
    assert "budget exhausted" in summaries[2]


# ----------------------------------------------------- budget settlement --


def test_settlement_quiet_hours_rollover_and_midnight_window(
    db_session, client, auth_headers, auth_factory
) -> None:
    user_id = _me(client, auth_headers)
    prefs = _prefs(
        db_session,
        user_id,
        enabled_categories=["replan"],
        daily_budget=1,
        quiet_hours_start="22:00",
        quiet_hours_end="07:00",
    )

    # A window crossing midnight (22:00 -> 07:00) covers both sides.
    night = datetime(2026, 10, 3, 23, 30, tzinfo=_SHANGHAI)
    outcome = settle_and_deliver(db_session, user_id=user_id, category="replan", now=night)
    assert outcome["delivered"] is False and outcome["reason"] == "quiet_hours"
    early = datetime(2026, 10, 3, 6, 0, tzinfo=_SHANGHAI)
    assert (
        settle_and_deliver(db_session, user_id=user_id, category="replan", now=early)["reason"]
        == "quiet_hours"
    )

    # Outside the window: a stale (yesterday-local) budget_date rolls over
    # and the count resets — yesterday's spend never taxes today.
    prefs.quiet_hours_start = None
    prefs.quiet_hours_end = None
    prefs.budget_date = night.astimezone(_SHANGHAI).date() - timedelta(days=1)
    prefs.sent_count = 5
    db_session.flush()
    noon = datetime(2026, 10, 3, 12, 0, tzinfo=_SHANGHAI)
    outcome = settle_and_deliver(db_session, user_id=user_id, category="replan", now=noon)
    assert outcome["delivered"] is True
    assert prefs.budget_date == noon.astimezone(_SHANGHAI).date()
    assert prefs.sent_count == 1  # rolled, charged once

    # Budget now exhausted for the rolled day.
    again = settle_and_deliver(
        db_session, user_id=user_id, category="replan", now=noon + timedelta(minutes=1)
    )
    assert again["reason"] == "budget_exhausted"

    # Disabled category is refused before any budget arithmetic.
    prefs.enabled_categories = []
    db_session.flush()
    assert (
        settle_and_deliver(db_session, user_id=user_id, category="replan", now=noon)["reason"]
        == "category_disabled"
    )

    # A user with NO preferences row is factory state (nothing enabled) —
    # and no row is materialized just to refuse a delivery.
    fresh_headers = auth_factory()
    fresh = _me(client, fresh_headers)
    assert (
        settle_and_deliver(db_session, user_id=fresh, category="replan", now=noon)["reason"]
        == "category_disabled"
    )
    assert (
        db_session.scalar(
            select(NotificationPreference).where(NotificationPreference.user_id == fresh)
        )
        is None
    )
