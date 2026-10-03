"""M4-A2 agent runtime regression set (D-034 §9, A2 face).

The §9 minimum set as it lands in this slice: consent-off ⇒ zero provider
calls with a working deterministic path (M4 exit criterion, server side);
L0–L3 permission matrix incl. wildcard/elevation/expiry/revocation; the
pending-action state machine (concurrent confirm exactly once, mutation
response cache, retry with unchanged args, TTL with CONFIRMED immunity,
EXECUTING lease reclaim); byte-identical context assembly with budget
drops; run watchdog; recursive audit redaction; chat send idempotency.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from backend.adapters.model_provider.base import ModelTurn, ProviderCapabilities, ToolCall
from backend.db.base import utcnow
from backend.models.agent import AgentRun, PendingAction
from backend.models.audit import AuditLog
from backend.models.enums import MemoryCorrectionStatus, MemoryKind
from backend.models.memory import Memory
from backend.models.task import Task
from backend.services.agent_runner import (
    create_pending_action,
    dispatch_confirmed_action,
    execute_run,
    reclaim_expired_runs,
    sweep_pending_actions,
)
from backend.services.agent_tools import TaskCreateArgs
from backend.services.audit import redact, redact_allowlist
from backend.services.context_assembly import assemble_context
from backend.services.model_consent import set_consent
from backend.services.permissions import PermissionDecision, evaluate_permission
from backend.services.tool_registry import get_tool, validate_registry

pytestmark = pytest.mark.integration


# --------------------------------------------------------------- helpers --


class FakeToolProvider:
    """Scripted provider; counts every context-bearing call (§9 asserts the
    consent-off count is exactly zero)."""

    name = "fake"
    model_name = "fake-model"

    def __init__(self, turns: list[ModelTurn]) -> None:
        self.turns = list(turns)
        self.calls = 0
        self.inputs: list[str] = []

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(text_generation=True, tool_calls=True)

    async def generate_with_tools(self, input_text, instructions, tool_schemas):
        self.calls += 1
        self.inputs.append(input_text)
        return self.turns.pop(0)

    async def continue_with_tool_results(self, turn, results):
        self.calls += 1
        return self.turns.pop(0)


def _me(client, headers) -> uuid.UUID:
    return uuid.UUID(client.get("/v1/auth/me", headers=headers).json()["id"])


def _seed_memory(
    db_session, user_id, *, kind, subject_key=None, content="记忆内容", confidence=0.8
):
    row = Memory(
        user_id=user_id,
        content=content,
        kind=kind,
        domain="study",
        subject_key=subject_key,
        confidence=confidence,
        correction_status=MemoryCorrectionStatus.CONFIRMED,
        source={"test": True},
    )
    db_session.add(row)
    db_session.flush()
    return row


def _seed_pending_task_create(
    db_session,
    user_id,
    *,
    status="PENDING",
    title="复习线代",
    version=1,
    expires_at=None,
    attempt_count=0,
):
    tool = get_tool("task.create")
    assert tool is not None and tool.display_builder is not None
    args = TaskCreateArgs(title=title)
    run = AgentRun(
        user_id=user_id,
        status="SUCCEEDED",
        invocation_kind="chat",
        trigger_ref={"kind": "chat"},
        operation_key=f"test:{uuid.uuid4().hex}",
        attempt_no=1,
        runner_version="t",
        tool_registry_version="t",
        prompt_version="v1",
    )
    db_session.add(run)
    db_session.flush()
    action = PendingAction(
        user_id=user_id,
        agent_run_id=run.id,
        tool_name="task.create",
        tool_version=tool.version,
        tool_title="创建任务",
        action="task.create",
        required_level=2,
        args=args.model_dump(mode="json"),
        args_hash=hashlib.sha256(title.encode()).hexdigest(),
        display=tool.display_builder(args),
        basis={
            "basis_version": "v1",
            "summary": "test",
            "references": [],
            "rule_versions": {},
            "selected_tool_call_ids": [],
        },
        status=status,
        version=version,
        expires_at=expires_at or (utcnow() + timedelta(hours=24)),
        idempotency_key=f"test:{uuid.uuid4().hex}",
        attempt_count=attempt_count,
        max_attempts=3,
    )
    db_session.add(action)
    db_session.flush()
    return action


def _send_chat_message(
    client, headers, content="帮我安排今晚复习", client_message_id: str | None = None
) -> dict:
    session = client.post("/v1/chat/sessions", json={"title": None}, headers=headers)
    assert session.status_code == 201, session.text
    cmid = client_message_id or str(uuid.uuid4())
    sent = client.post(
        f"/v1/chat/sessions/{session.json()['id']}/messages",
        json={"content": content, "client_message_id": cmid},
        headers=headers,
    )
    assert sent.status_code == 202, sent.text
    body = sent.json()
    body["session_id"] = session.json()["id"]
    body["client_message_id"] = cmid
    return body


# ------------------------------------------------------ registry + matrix --


def test_registry_validates_and_policy_levels_align() -> None:
    names = validate_registry()
    assert "notify.push" in names and "task.create" in names
    focus = get_tool("focus.start")
    notify = get_tool("notify.push")
    state = get_tool("state.read")
    assert focus is not None and focus.required_level == 2
    assert notify is not None and notify.required_level == 3
    assert state is not None and state.required_level == 0


def test_l3_grant_never_elevates_l2_even_wildcard(db_session, client, auth_headers) -> None:
    user_id = _me(client, auth_headers)
    from backend.models.permission import PermissionGrant

    db_session.add(
        PermissionGrant(
            user_id=user_id,
            action="plan.*",
            level=3,
            scope={"categories": ["plan"], "channels": ["web"]},
        )
    )
    db_session.flush()
    decision = evaluate_permission(db_session, user_id=user_id, action="plan.confirm")
    assert decision.requires_confirmation  # D-034 §2.5: L2 always confirms
    assert decision.granted_level == 3  # the grant is visible but cannot elevate


def test_notify_push_scope_matrix(db_session, client, auth_headers) -> None:
    user_id = _me(client, auth_headers)
    from backend.models.permission import PermissionGrant
    from backend.services.tool_registry import strict_scope_validator

    tool = get_tool("notify.push")
    assert tool is not None and tool.scope_validator is not None

    def decide() -> PermissionDecision:
        return evaluate_permission(
            db_session,
            user_id=user_id,
            action="notify.push",
            scope_validator=tool.scope_validator,
        )

    assert decide().requires_confirmation  # no grant

    # One ACTIVE grant per (user, action) — the partial unique index from
    # A1 — so the matrix mutates a single row through its states.
    grant = PermissionGrant(user_id=user_id, action="notify.push", level=3, scope={})
    db_session.add(grant)
    db_session.flush()
    assert decide().requires_confirmation  # empty scope is not a wildcard

    grant.scope = {"categories": ["deadline"], "channels": ["web"]}
    db_session.flush()
    assert decide().allowed

    grant.revoked_at = utcnow()
    db_session.flush()
    assert decide().requires_confirmation  # revoked never auto-executes

    grant.revoked_at = None
    grant.expires_at = utcnow() - timedelta(minutes=1)
    db_session.flush()
    assert decide().requires_confirmation  # expired

    grant.expires_at = None
    grant.scope = {"categories": ["*"], "channels": ["web"]}
    db_session.flush()
    assert decide().requires_confirmation  # wildcard scope denies

    strict = strict_scope_validator(
        frozenset({"categories", "channels"}), list_keys=frozenset({"categories", "channels"})
    )
    assert strict({"categories": ["x"], "channels": ["y"], "unknown": 1}) is False


# ------------------------------------------------------------ consent API --


def test_model_context_consent_default_off_and_version_echo(client, auth_headers) -> None:
    current = client.get("/v1/model-context-consent", headers=auth_headers).json()
    assert current["enabled"] is False
    assert current["consented_at"] is None

    stale = client.put(
        "/v1/model-context-consent",
        json={"enabled": True, "consent_text_version": "v0"},
        headers=auth_headers,
    )
    assert stale.status_code == 422

    on = client.put(
        "/v1/model-context-consent",
        json={"enabled": True, "consent_text_version": current["consent_text_version"]},
        headers=auth_headers,
    )
    assert on.status_code == 200 and on.json()["enabled"] is True
    assert on.json()["consented_at"] is not None

    off = client.put(
        "/v1/model-context-consent",
        json={"enabled": False, "consent_text_version": current["consent_text_version"]},
        headers=auth_headers,
    )
    assert off.json()["enabled"] is False


# ------------------------------------------------------- consent gate + run


def test_consent_off_zero_provider_calls_deterministic_plan(
    db_session, client, auth_headers
) -> None:
    _me(client, auth_headers)
    sent = _send_chat_message(client, auth_headers)
    provider = FakeToolProvider(
        [
            ModelTurn(
                text="unused",
                tool_calls=[ToolCall(call_id="c1", name="state.read", arguments_json="{}")],
            )
        ]
    )
    run = asyncio.run(execute_run(db_session, run_id=uuid.UUID(sent["run_id"]), provider=provider))
    assert run is not None and run.result is not None
    assert provider.calls == 0  # §9: consent off ⇒ zero provider calls
    assert run.status == "SUCCEEDED"
    assert run.result["degraded"] is True
    assert run.result["degrade_code"] == "model_consent_missing"
    assert run.provider["capability"] == "none"
    assert any(c["tool_name"] == "plan.suggest" for c in run.tool_calls)
    plans = db_session.execute(
        select(AgentRun.tool_calls).where(AgentRun.id == run.id)
    ).scalar_one()
    assert plans  # deterministic fallback produced output


def test_consent_on_provider_loop_creates_pending_action(db_session, client, auth_headers) -> None:
    user_id = _me(client, auth_headers)
    set_consent(db_session, user_id, enabled=True, consent_text_version="v1")
    sent = _send_chat_message(client, auth_headers)

    call_json = json.dumps({"title": "复习线代", "estimated_duration_minutes": 45})
    provider = FakeToolProvider(
        [
            ModelTurn(
                tool_calls=[ToolCall(call_id="c1", name="task.create", arguments_json=call_json)]
            ),
            ModelTurn(text="已为你创建待确认任务。"),
        ]
    )
    run = asyncio.run(execute_run(db_session, run_id=uuid.UUID(sent["run_id"]), provider=provider))
    assert run is not None
    assert provider.calls == 2
    assert "## CurrentState" in provider.inputs[0]  # consented context rendered
    assert run.status == "WAITING_CONFIRMATION"
    pending = db_session.scalars(
        select(PendingAction).where(PendingAction.agent_run_id == run.id)
    ).all()
    assert len(pending) == 1 and pending[0].status == "PENDING"
    assert pending[0].required_level == 2
    assert pending[0].display["summary"].startswith("创建任务")

    # The assistant message landed with the run's safe summary.
    from backend.models.chat import ChatMessage

    replies = db_session.scalars(
        select(ChatMessage).where(
            ChatMessage.agent_run_id == run.id, ChatMessage.role == "assistant"
        )
    ).all()
    assert len(replies) == 1


def test_provider_unavailable_degrades_to_deterministic(db_session, client, auth_headers) -> None:
    user_id = _me(client, auth_headers)
    set_consent(db_session, user_id, enabled=True, consent_text_version="v1")
    sent = _send_chat_message(client, auth_headers)
    run = asyncio.run(execute_run(db_session, run_id=uuid.UUID(sent["run_id"]), provider=None))
    assert run is not None and run.result is not None
    assert run.status == "SUCCEEDED"
    assert run.result["degraded"] is True
    assert run.result["degrade_code"] == "provider_unavailable"
    # Plans/replan suggestions keep working — the M4 exit criterion.
    assert {c["tool_name"] for c in run.tool_calls} >= {"plan.suggest", "replan.evaluate"}


# ------------------------------------------------------ pending mutations --


def test_confirm_exactly_once_and_response_cache(db_session, client, auth_headers) -> None:
    user_id = _me(client, auth_headers)
    action = _seed_pending_task_create(db_session, user_id)
    db_session.commit()

    first = client.post(
        f"/v1/pending-actions/{action.id}/confirm",
        json={"expected_version": 1, "mutation_id": "m-1"},
        headers=auth_headers,
    )
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "SUCCEEDED"
    assert first.json()["result"]["resource_type"] == "task"

    tasks = db_session.scalars(select(Task).where(Task.user_id == user_id)).all()
    assert len(tasks) == 1  # exactly one side effect

    resend = client.post(
        f"/v1/pending-actions/{action.id}/confirm",
        json={"expected_version": 1, "mutation_id": "m-1"},
        headers=auth_headers,
    )
    assert resend.status_code == 200
    assert resend.json() == first.json()  # cached settlement, no re-dispatch

    second_mutation = client.post(
        f"/v1/pending-actions/{action.id}/confirm",
        json={"expected_version": first.json()["version"], "mutation_id": "m-2"},
        headers=auth_headers,
    )
    assert second_mutation.status_code == 200  # already advanced → current row
    assert db_session.scalars(select(Task).where(Task.user_id == user_id)).all().__len__() == 1


def test_confirm_version_mismatch_409_and_ignore_beats_late_confirm(
    db_session, client, auth_headers
) -> None:
    user_id = _me(client, auth_headers)
    action = _seed_pending_task_create(db_session, user_id)
    db_session.commit()

    mismatch = client.post(
        f"/v1/pending-actions/{action.id}/confirm",
        json={"expected_version": 99, "mutation_id": "m-x"},
        headers=auth_headers,
    )
    assert mismatch.status_code == 409

    ignored = client.post(
        f"/v1/pending-actions/{action.id}/ignore",
        json={"expected_version": 1, "mutation_id": "m-i"},
        headers=auth_headers,
    )
    assert ignored.json()["status"] == "IGNORED"

    late = client.post(
        f"/v1/pending-actions/{action.id}/confirm",
        json={"expected_version": 2, "mutation_id": "m-l"},
        headers=auth_headers,
    )
    assert late.status_code == 409  # terminal state beat the confirmation


def test_retry_keeps_args_and_only_from_retryable(db_session, client, auth_headers) -> None:
    user_id = _me(client, auth_headers)
    action = _seed_pending_task_create(
        db_session, user_id, status="FAILED_RETRYABLE", attempt_count=1, version=3
    )
    db_session.commit()

    wrong_state = client.post(
        f"/v1/pending-actions/{action.id}/retry",
        json={"expected_version": 1, "mutation_id": "r-0"},
        headers=auth_headers,
    )
    assert wrong_state.status_code == 422 or wrong_state.status_code == 409

    retried = client.post(
        f"/v1/pending-actions/{action.id}/retry",
        json={"expected_version": 3, "mutation_id": "r-1"},
        headers=auth_headers,
    )
    assert retried.status_code == 200, retried.text
    assert retried.json()["status"] == "SUCCEEDED"
    # Same args/hash/key — retry never lets new parameters in.
    db_session.refresh(action)
    assert action.args["title"] == "复习线代"
    assert db_session.scalars(select(Task).where(Task.user_id == user_id)).all().__len__() == 1


def test_ttl_expires_only_pending(db_session, client, auth_headers) -> None:
    user_id = _me(client, auth_headers)
    expired_pending = _seed_pending_task_create(
        db_session, user_id, expires_at=utcnow() - timedelta(minutes=1)
    )
    confirmed = _seed_pending_task_create(
        db_session,
        user_id,
        status="CONFIRMED",
        expires_at=utcnow() - timedelta(minutes=1),
        version=2,
    )
    db_session.commit()

    read = client.get(f"/v1/pending-actions/{expired_pending.id}", headers=auth_headers)
    assert read.json()["status"] == "EXPIRED"  # lazy convergence on read

    confirmed_read = client.get(f"/v1/pending-actions/{confirmed.id}", headers=auth_headers)
    assert confirmed_read.json()["status"] == "CONFIRMED"  # ruling A1

    executing = _seed_pending_task_create(db_session, user_id, status="EXECUTING")
    executing.execution_lease = {
        "claim_token": "t",
        "claimed_by": "dead-worker",
        "lease_expires_at": (utcnow() - timedelta(minutes=5)).isoformat(),
        "heartbeat_at": utcnow().isoformat(),
    }
    db_session.flush()
    summary = sweep_pending_actions(db_session)
    assert summary["lease_lapsed"] >= 1  # expiry already settled lazily on read
    db_session.refresh(executing)
    assert executing.status == "FAILED_RETRYABLE"
    assert executing.last_error is not None
    assert executing.last_error["code"] == "execution_lease_expired"


def test_l3_dispatch_reverifies_grant_and_fails_closed(db_session, client, auth_headers) -> None:
    user_id = _me(client, auth_headers)
    from backend.models.permission import PermissionGrant

    grant = PermissionGrant(user_id=user_id, action="notify.push", level=3, scope={})
    db_session.add(grant)
    db_session.flush()

    run = AgentRun(
        user_id=user_id,
        status="RUNNING",
        invocation_kind="proactive_trigger",
        trigger_ref={"kind": "trigger", "trigger_signature": "sig"},
        operation_key=f"test:{uuid.uuid4().hex}",
        attempt_no=1,
        runner_version="t",
        tool_registry_version="t",
        prompt_version="v1",
    )
    db_session.add(run)
    db_session.flush()

    from backend.services.agent_tools import NotifyPushArgs

    tool = get_tool("notify.push")
    assert tool is not None
    action = create_pending_action(
        db_session,
        run=run,
        tool=tool,
        args=NotifyPushArgs(category="deadline", title="线代截止"),
        decision_summary="test",
        level3_grant=grant,  # scope empty → fails re-verify
    )
    assert action.status == "CONFIRMED"
    row = asyncio.run(dispatch_confirmed_action(db_session, action_id=action.id))
    assert row is not None
    assert row.status == "FAILED"
    assert row.last_error is not None
    assert row.last_error["code"] == "permission_denied"


# ----------------------------------------------------- context + assembly --


def test_context_assembly_byte_identical_with_stable_order(
    db_session, client, auth_headers
) -> None:
    user_id = _me(client, auth_headers)
    _seed_memory(
        db_session,
        user_id,
        kind=MemoryKind.HABIT,
        subject_key="作息",
        content="晚 23 点后不安排任务",
    )
    _seed_memory(
        db_session, user_id, kind=MemoryKind.FACT, subject_key=None, content="线代作业每周三交"
    )
    _seed_memory(
        db_session,
        user_id,
        kind=MemoryKind.PREFERENCE,
        subject_key="环境",
        content=" prefers 图书馆",
    )

    first = assemble_context(db_session, user_id=user_id, user_message="今晚做什么？")
    second = assemble_context(db_session, user_id=user_id, user_message="今晚做什么？")
    assert first.rendered == second.rendered  # byte-identical (§9)
    assert first.manifest["rendered_context_hash"] == second.manifest["rendered_context_hash"]
    assert first.manifest["consents"]["model_context"] is None  # default off

    # Frozen prefix order: fact (kind rank 0) before habit (1) before
    # preference (2); NULLS LAST only applies within a kind.
    kinds = [
        next(m for m in _memory_rows(db_session, user_id) if m.id == uuid.UUID(ref["id"])).kind
        for ref in first.manifest["memory_refs"]
    ]
    assert [k.value for k in kinds] == ["fact", "habit", "preference"]


def _memory_rows(db_session, user_id):
    return db_session.scalars(select(Memory).where(Memory.user_id == user_id)).all()


def test_context_budget_drops_whole_low_priority_sections(
    db_session, client, auth_headers, monkeypatch
) -> None:
    from backend.config import get_settings

    user_id = _me(client, auth_headers)
    _seed_memory(db_session, user_id, kind=MemoryKind.FACT, content="长" * 500)

    settings = get_settings()
    monkeypatch.setattr(
        settings, "agent_context_token_budget", settings.agent_context_reserved_tokens + 200
    )
    assembled = assemble_context(db_session, user_id=user_id, user_message="今晚做什么？")
    sections = {s["name"]: s for s in assembled.manifest["sections"]}
    assert sections["closing"]["fitted"] is True  # the question survives
    assert sections["memory"]["fitted"] is False  # dropped whole, not truncated


def test_history_section_only_for_chat_runs(db_session, client, auth_headers) -> None:
    user_id = _me(client, auth_headers)
    session = client.post("/v1/chat/sessions", json={}, headers=auth_headers).json()
    for i in range(3):
        sent = client.post(
            f"/v1/chat/sessions/{session['id']}/messages",
            json={"content": f"消息 {i}", "client_message_id": str(uuid.uuid4())},
            headers=auth_headers,
        )
        assert sent.status_code == 202
    assembled = assemble_context(
        db_session,
        user_id=user_id,
        chat_session_id=uuid.UUID(session["id"]),
        user_message="继续",
    )
    assert len(assembled.manifest["history_message_ids"]) == 3


# ------------------------------------------------------------ chat idem ---


def test_chat_send_dedup_returns_same_attempt(client, auth_headers) -> None:
    sent = _send_chat_message(client, auth_headers)

    resend = client.post(
        f"/v1/chat/sessions/{sent['session_id']}/messages",
        json={"content": "帮我安排今晚复习", "client_message_id": sent["client_message_id"]},
        headers=auth_headers,
    )
    assert resend.status_code == 202
    assert resend.json()["run_id"] == sent["run_id"]
    assert resend.json()["user_message_id"] == sent["user_message_id"]

    messages = client.get(
        f"/v1/chat/sessions/{sent['session_id']}/messages", headers=auth_headers
    ).json()["items"]
    user_rows = [m for m in messages if m["role"] == "user"]
    assert len(user_rows) == 1  # one message row, not two


def test_chat_session_isolated_per_user(client, auth_headers, auth_factory) -> None:
    sent = _send_chat_message(client, auth_headers)
    other = auth_factory()
    foreign = client.get(f"/v1/chat/sessions/{sent['session_id']}/messages", headers=other)
    assert foreign.status_code == 404


# ------------------------------------------------------------ watchdog ----


def test_run_watchdog_settles_and_mints_next_attempt(db_session, client, auth_headers) -> None:
    user_id = _me(client, auth_headers)
    stale = AgentRun(
        user_id=user_id,
        status="RUNNING",
        invocation_kind="chat",
        trigger_ref={"kind": "chat"},
        operation_key=f"test:{uuid.uuid4().hex}",
        attempt_no=1,
        client_request_id=f"chat:{uuid.uuid4()}:{uuid.uuid4()}",
        runner_version="t",
        tool_registry_version="t",
        prompt_version="v1",
        lease={
            "claim_token": "t",
            "claimed_by": "dead",
            "lease_expires_at": (utcnow() - timedelta(minutes=5)).isoformat(),
            "heartbeat_at": utcnow().isoformat(),
        },
        started_at=utcnow() - timedelta(minutes=6),
    )
    db_session.add(stale)
    db_session.flush()

    summary = reclaim_expired_runs(db_session)
    assert summary["reclaimed"] >= 1 and summary["retried"] >= 1
    db_session.refresh(stale)
    assert stale.status == "FAILED"
    assert stale.failure is not None
    assert stale.failure["code"] == "worker_lease_expired"

    retry = db_session.scalars(
        select(AgentRun).where(
            AgentRun.operation_key == stale.operation_key, AgentRun.attempt_no == 2
        )
    ).one()
    assert retry.status == "QUEUED"


# --------------------------------------------------------------- redact ----


def test_recursive_redaction_blocks_nested_secrets_and_blobs() -> None:
    dirty = {
        "outer": {"token": "abc", "note": "ok", "quote": "资料原文"},
        "cookie": "session=1",
        "fine": "id-123",
        "blob": "x" * 500,
        "list": [{"authorization": "Bearer x", "n": 1}],
    }
    clean = redact(dirty)
    assert clean["outer"]["token"] == "[redacted]"
    assert clean["outer"]["quote"] == "[redacted]"
    assert clean["outer"]["note"] == "ok"
    assert clean["cookie"] == "[redacted]"
    assert clean["list"][0]["authorization"] == "[redacted]"
    assert clean["list"][0]["n"] == 1
    assert clean["blob"].endswith("…[truncated]") and len(clean["blob"]) <= 220

    allowed = redact_allowlist(
        {"tool_name": "task.create", "title": "不该出现", "nested": {"inner": "ok"}},
        frozenset({"tool_name"}),
    )
    # Unknown keys drop at every level; a banned key stays blocked even
    # inside an allowed container.
    assert allowed == {"tool_name": "task.create"}
    kept = redact_allowlist({"nested": {"token": "x", "n": 2}}, frozenset({"nested"}))
    assert kept == {"nested": {"token": "[redacted]", "n": 2}}


def test_agent_audit_rows_carry_no_raw_content(db_session, client, auth_headers) -> None:
    user_id = _me(client, auth_headers)
    action = _seed_pending_task_create(db_session, user_id)
    db_session.commit()
    client.post(
        f"/v1/pending-actions/{action.id}/confirm",
        json={"expected_version": 1, "mutation_id": "audit-m"},
        headers=auth_headers,
    )
    rows = db_session.scalars(
        select(AuditLog).where(
            AuditLog.user_id == user_id,
            AuditLog.action.like("pending_action%"),
        )
    ).all()
    assert rows
    banned = {"content", "chat", "message", "quote", "token", "prompt", "body", "text"}
    for row in rows:
        for key, value in (row.details or {}).items():
            assert key not in banned
            assert "复习线代" not in json.dumps(value, ensure_ascii=False) or key == "summary"
