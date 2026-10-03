"""Deterministic-first agent runner (D-034 §3/§5/§6).

Execution model: a ``QUEUED`` run is claimed atomically (status + lease in
one ``UPDATE ... WHERE status='QUEUED'``), executed, and settled — every
state transition commits WITH its audit row in the same transaction (the
append-only ledger requirement; ``safe_record_audit`` is not used here).

Provider policy, in order:

1. No active global model-context consent → ``capability: "none"``; the
   deterministic tools (``plan.suggest`` + ``replan.evaluate``) run via the
   SAME registry entries, the run is ``SUCCEEDED`` with
   ``result.degraded=true, degrade_code=model_consent_missing``. Zero
   provider calls are made (the M4 exit criterion's server side).
2. Provider unavailable / no tool capability → same deterministic path with
   the matching degrade code.
3. Consent active + tool-capable provider → bounded tool loop (§6.2 caps),
   every model call passing schema → permission → display validation in
   that fixed order.

Side effects: Level 2/3 model proposals only ever create ``pending_actions``
here; execution happens in :func:`dispatch_confirmed_action` after user
confirmation (Level 2) or a re-verified scoped grant (Level 3).
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.db.base import utcnow
from backend.models.agent import AgentRun, PendingAction, PendingActionMutation
from backend.models.chat import ChatMessage
from backend.models.enums import AuditActor, AuditDecision
from backend.schemas.agent import pending_action_read
from backend.services import agent_tools
from backend.services.agent_tools import ExecContext
from backend.services.audit import record_audit, redact_allowlist
from backend.services.context_assembly import assemble_context
from backend.services.permissions import (
    PermissionLevel,
    evaluate_permission,
)
from backend.services.tool_registry import (
    INPUT_REDACTION_VERSION,
    RUNNER_VERSION,
    TOOL_REGISTRY_VERSION,
    ToolDefinition,
    ToolError,
    get_tool,
)

settings = get_settings()
logger = logging.getLogger(__name__)

_AGENT_AUDIT_ALLOWED = frozenset(
    {"tool_name", "tool_version", "code", "retryable", "status", "attempt", "count"}
)

DEGRADE_MODEL_CONSENT_MISSING = "model_consent_missing"
DEGRADE_PROVIDER_UNAVAILABLE = "provider_unavailable"
DEGRADE_NO_TOOL_SUPPORT = "no_tool_support"


# ----------------------------------------------------------------- leases --


def _new_lease(worker: str, seconds: int) -> dict[str, Any]:
    now = utcnow()
    return {
        "claim_token": str(uuid.uuid4()),
        "claimed_by": worker,
        "lease_expires_at": (now + timedelta(seconds=seconds)).isoformat(),
        "heartbeat_at": now.isoformat(),
    }


def _lease_expired(lease: dict[str, Any] | None) -> bool:
    if not lease:
        return True
    expires = lease.get("lease_expires_at")
    if not expires:
        return True
    return datetime.fromisoformat(expires) <= datetime.now(UTC)


def heartbeat_run(session: Session, run: AgentRun) -> None:
    lease = run.lease or {}
    lease["heartbeat_at"] = utcnow().isoformat()
    lease["lease_expires_at"] = (
        utcnow() + timedelta(seconds=settings.agent_run_lease_seconds)
    ).isoformat()
    run.lease = lease
    session.flush()


def claim_run(session: Session, run_id: uuid.UUID, *, worker: str = "worker") -> AgentRun | None:
    """QUEUED → RUNNING, atomically. Returns ``None`` when another worker
    owns it or it is already terminal."""

    lease = _new_lease(worker, settings.agent_run_lease_seconds)
    result = session.execute(
        update(AgentRun)
        .where(AgentRun.id == run_id, AgentRun.status == "QUEUED")
        .values(
            status="RUNNING",
            lease=lease,
            started_at=utcnow(),
            updated_at=utcnow(),
        )
    )
    if int(getattr(result, "rowcount", 0)) != 1:
        session.rollback()
        return None
    run = session.get(AgentRun, run_id)
    assert run is not None  # the conditional UPDATE just matched this row
    record_audit(
        session,
        action="agent.run.started",
        actor=AuditActor.SYSTEM.value,
        user_id=run.user_id,
        resource_type="agent_run",
        resource_id=str(run.id),
        details={"status": "RUNNING", "attempt": run.attempt_no},
    )
    session.commit()
    return run


def audit_run_queued(session: Session, run: AgentRun) -> None:
    record_audit(
        session,
        action="agent.run.queued",
        actor=AuditActor.SYSTEM.value,
        user_id=run.user_id,
        resource_type="agent_run",
        resource_id=str(run.id),
        details={"invocation_kind": run.invocation_kind, "attempt": run.attempt_no},
    )


# ------------------------------------------------------- pending creation --


def _args_hash(args: Any) -> str:
    canonical = json.dumps(
        args if isinstance(args, dict) else args.model_dump(mode="json"),
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def create_pending_action(
    session: Session,
    *,
    run: AgentRun,
    tool: ToolDefinition,
    args: Any,
    decision_summary: str,
    references: list[dict[str, Any]] | None = None,
    level3_grant: Any | None = None,
) -> PendingAction:
    """Level 2 → PENDING; Level 3 with a live scoped grant → CONFIRMED
    (grant-based confirmation basis, §5.1). The idempotency key namespaces
    the tool's stable key by the run's operation key, so attempt retries
    dedup onto the same row while distinct workflows stay distinct."""

    assert tool.idempotency_key is not None  # level>=2 tools validated at registration
    key = f"{run.operation_key}:{tool.idempotency_key(args)}"
    existing = session.scalar(
        select(PendingAction).where(
            PendingAction.user_id == run.user_id, PendingAction.idempotency_key == key
        )
    )
    if existing is not None:
        return existing

    action = PendingAction(
        user_id=run.user_id,
        agent_run_id=run.id,
        tool_name=tool.name,
        tool_version=tool.version,
        tool_title=tool.description[:200],
        action=tool.name,
        required_level=tool.required_level,
        args=args.model_dump(mode="json") if not isinstance(args, dict) else args,
        args_hash=_args_hash(args),
        display=tool.display_builder(args) if tool.display_builder else {},
        basis={
            "basis_version": "v1",
            "summary": decision_summary,
            "references": references or [],
            "rule_versions": {"tool_registry": TOOL_REGISTRY_VERSION},
            "selected_tool_call_ids": [],
        },
        status="PENDING",
        version=1,
        expires_at=utcnow() + timedelta(hours=settings.agent_pending_ttl_hours),
        idempotency_key=key,
    )
    if level3_grant is not None:
        # §5.1/§5.3: grant snapshot at creation, re-verified at execution.
        action.status = "CONFIRMED"
        action.confirmed_at = utcnow()
        action.grant_id = level3_grant.id
        action.grant_snapshot = {
            "grant_id": str(level3_grant.id),
            "scope_hash": hashlib.sha256(
                json.dumps(level3_grant.scope, sort_keys=True).encode()
            ).hexdigest()[:16],
            "checked_at": utcnow().isoformat(),
        }
    session.add(action)
    session.flush()
    record_audit(
        session,
        action="pending_action.created",
        actor=AuditActor.AGENT.value,
        user_id=run.user_id,
        resource_type="pending_action",
        resource_id=str(action.id),
        permission_level=tool.required_level,
        decision=AuditDecision.REQUIRE_CONFIRMATION.value
        if level3_grant is None
        else AuditDecision.ALLOW.value,
        details=redact_allowlist(
            {"tool_name": tool.name, "tool_version": tool.version, "status": action.status},
            _AGENT_AUDIT_ALLOWED,
        ),
    )
    return action


# ------------------------------------------------------------- execution ---


def _tool_call_row(
    call_id: str,
    tool: Any,
    args: Any,
    status: str,
    started_at: datetime,
    error_code: str | None = None,
    result_ref: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "call_id": call_id,
        "tool_name": tool.name,
        "tool_version": tool.version,
        "args_hash": _args_hash(args),
        "input_redaction_version": INPUT_REDACTION_VERSION,
        "status": status,
        "started_at": started_at.isoformat(),
        "ended_at": utcnow().isoformat(),
    }
    if error_code:
        row["error_code"] = error_code
    if result_ref:
        row["result_ref"] = result_ref
    return row


def _level3_grant(session: Session, user_id: uuid.UUID, tool: ToolDefinition) -> Any | None:
    decision = evaluate_permission(
        session,
        user_id=user_id,
        action=tool.name,
        scope_validator=tool.scope_validator,
    )
    if decision.allowed:
        from backend.models.permission import PermissionGrant

        grant = session.scalar(
            select(PermissionGrant).where(
                PermissionGrant.user_id == user_id,
                PermissionGrant.action == tool.name,
                PermissionGrant.level == PermissionLevel.AUTO,
                PermissionGrant.revoked_at.is_(None),
            )
        )
        return grant
    return None


async def _execute_tool(
    session: Session,
    *,
    run: AgentRun,
    tool: ToolDefinition,
    args: Any,
    provider: Any | None,
    idempotency_key: str | None = None,
    pending_action_id: uuid.UUID | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Run a validated tool. Returns (result, error_code)."""

    assert tool.execute is not None  # register_tool rejects implementation-less tools
    ctx = ExecContext(
        session=session,
        user_id=run.user_id,
        provider=provider,
        idempotency_key=idempotency_key,
        pending_action_id=pending_action_id,
    )
    try:
        result = await tool.execute(ctx, args)
        return result, None
    except ToolError as exc:
        return None, exc.code
    except Exception:
        logger.exception("Tool %s crashed", tool.name)
        return None, "tool_internal_error"


def _settle_run(
    session: Session,
    run: AgentRun,
    *,
    status: str,
    result: dict[str, Any] | None = None,
    failure: dict[str, Any] | None = None,
) -> None:
    run.status = status
    run.finished_at = utcnow()
    run.updated_at = utcnow()
    if result is not None:
        run.result = result
    if failure is not None:
        run.failure = failure
    record_audit(
        session,
        action=f"agent.run.{status.lower()}",
        actor=AuditActor.SYSTEM.value,
        user_id=run.user_id,
        resource_type="agent_run",
        resource_id=str(run.id),
        details=redact_allowlist({"status": status}, _AGENT_AUDIT_ALLOWED),
    )
    session.flush()


async def dispatch_confirmed_action(
    session: Session,
    *,
    action_id: uuid.UUID,
    provider: Any | None = None,
    worker: str = "worker",
) -> PendingAction | None:
    """Claim a CONFIRMED action (FOR UPDATE SKIP LOCKED) and execute it.

    ``None`` means another worker holds it (or it is not in a claimable
    state) — both are benign for the caller. Failures map to the 8-state
    machine: retryable errors → ``FAILED_RETRYABLE`` (attempts left) else
    ``FAILED``; Level 3 grant re-verification failures are final
    ``permission_denied``/``permission_revoked``.
    """

    row = session.execute(
        select(PendingAction)
        .where(
            PendingAction.id == action_id,
            PendingAction.status.in_(("CONFIRMED", "FAILED_RETRYABLE")),
        )
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()
    if row is None:
        return None
    if row.status == "FAILED_RETRYABLE":
        if row.attempt_count >= row.max_attempts:
            return session.get(PendingAction, action_id)
        row.status = "CONFIRMED"

    row.status = "EXECUTING"
    row.executed_at = utcnow()
    row.attempt_count += 1
    row.execution_lease = _new_lease(worker, settings.agent_execution_lease_seconds)
    row.version += 1
    session.flush()
    record_audit(
        session,
        action="pending_action.dispatched",
        actor=AuditActor.SYSTEM.value,
        user_id=row.user_id,
        resource_type="pending_action",
        resource_id=str(row.id),
        details=redact_allowlist(
            {
                "tool_name": row.tool_name,
                "tool_version": row.tool_version,
                "attempt": row.attempt_count,
            },
            _AGENT_AUDIT_ALLOWED,
        ),
    )

    tool = get_tool(row.tool_name)
    failure: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    if tool is None:
        failure = {
            "code": "tool_not_registered",
            "retryable": False,
            "safe_message": "Tool is no longer registered",
        }
    elif row.required_level == PermissionLevel.AUTO:
        # §5.1: the grant is re-verified at the moment of execution.
        grant = _level3_grant(session, row.user_id, tool)
        if grant is None:
            failure = {
                "code": "permission_denied",
                "retryable": False,
                "safe_message": "Level-3 grant missing, expired, revoked or out of scope",
            }

    if failure is None and tool is not None:
        try:
            args = tool.input_model.model_validate(row.args)
        except Exception:
            failure = {
                "code": "tool_arguments_invalid",
                "retryable": False,
                "safe_message": "Stored arguments no longer validate",
            }
        else:
            run = session.get(AgentRun, row.agent_run_id)
            assert run is not None
            exec_result, error_code = await _execute_tool(
                session,
                run=run,
                tool=tool,
                args=args,
                provider=provider,
                idempotency_key=row.idempotency_key,
                pending_action_id=row.id,
            )
            if error_code is None:
                result = exec_result
            else:
                retryable = error_code in ("provider_unavailable", "tool_internal_error")
                failure = {
                    "code": error_code,
                    "retryable": retryable,
                    "safe_message": f"Tool failed: {error_code}",
                }

    now = utcnow()
    if failure is None:
        row.status = "SUCCEEDED"
        row.finished_at = now
        row.result = result or {"summary": "Done"}
        row.updated_at = now
        audit_action = "pending_action.succeeded"
    elif failure["retryable"] and row.attempt_count < row.max_attempts:
        row.status = "FAILED_RETRYABLE"
        row.last_error = {"code": failure["code"], "message": failure["safe_message"]}
        row.updated_at = now
        audit_action = "pending_action.retryable_failed"
    else:
        row.status = "FAILED"
        row.finished_at = now
        row.last_error = {"code": failure["code"], "message": failure["safe_message"]}
        row.updated_at = now
        audit_action = "pending_action.failed"
    record_audit(
        session,
        action=audit_action,
        actor=AuditActor.SYSTEM.value,
        user_id=row.user_id,
        resource_type="pending_action",
        resource_id=str(row.id),
        details=redact_allowlist(
            {"tool_name": row.tool_name, "status": row.status, "code": (failure or {}).get("code")},
            _AGENT_AUDIT_ALLOWED,
        ),
    )
    session.commit()
    return session.get(PendingAction, action_id)


# ------------------------------------------------------------ the run ------


def _chat_context(session: Session, run: AgentRun) -> tuple[uuid.UUID | None, str | None]:
    """Chat runs derive (session_id, user message) from the frozen
    client_request_id formula ``chat:{session_id}:{client_message_id}``."""

    if run.invocation_kind != "chat" or not run.client_request_id:
        return None, None
    parts = run.client_request_id.split(":", 2)
    if len(parts) != 3:
        return None, None
    _, session_id_raw, message_id_raw = parts
    try:
        session_id = uuid.UUID(session_id_raw)
        message_id = uuid.UUID(message_id_raw)
    except ValueError:
        return None, None
    message = session.scalar(
        select(ChatMessage).where(ChatMessage.id == message_id, ChatMessage.user_id == run.user_id)
    )
    return session_id, (message.content if message is not None else None)


async def execute_run(
    session: Session,
    *,
    run_id: uuid.UUID,
    provider: Any | None = None,
    worker: str = "worker",
) -> AgentRun | None:
    run = claim_run(session, run_id, worker=worker)
    if run is None:
        return None
    assert run is not None  # claim_run already returned for the miss case

    tool_calls: list[dict[str, Any]] = []
    pending_ids: list[uuid.UUID] = []
    usage_total = {"input_tokens": 0, "output_tokens": 0, "tool_tokens": 0}
    references: list[dict[str, Any]] = []
    degrade_code: str | None = None
    summary_parts: list[str] = []

    try:
        chat_session_id, user_message = _chat_context(session, run)
        assembled = assemble_context(
            session,
            user_id=run.user_id,
            chat_session_id=chat_session_id,
            user_message=user_message,
        )
        run.context_snapshot = assembled.manifest
        run.prompt_version = assembled.manifest["prompt_version"]
        references.append(
            {
                "kind": "current_state",
                "id": str(run.user_id),
                "label": "CurrentState",
                "state": None,
                "version": str(assembled.manifest["state_version"]),
            }
        )

        caps = provider.capabilities() if provider is not None else None
        if assembled.consent_version is None:
            provider = None
            degrade_code = DEGRADE_MODEL_CONSENT_MISSING
        elif provider is None:
            degrade_code = DEGRADE_PROVIDER_UNAVAILABLE
        elif caps is None or not caps.tool_calls:
            provider = None
            degrade_code = DEGRADE_NO_TOOL_SUPPORT

        if provider is None:
            # Deterministic path: same registry entries, same code path —
            # plans and replan suggestions keep working without a provider.
            provider_info = {"name": "deterministic", "model": "none", "capability": "none"}
            for tool_name, args_obj in (
                ("plan.suggest", agent_tools.PlanSuggestArgs()),
                ("replan.evaluate", agent_tools.ReplanEvaluateArgs()),
            ):
                tool = get_tool(tool_name)
                assert tool is not None
                started = utcnow()
                result, error_code = await _execute_tool(
                    session, run=run, tool=tool, args=args_obj, provider=None
                )
                tool_calls.append(
                    _tool_call_row(
                        f"det-{len(tool_calls) + 1}",
                        tool,
                        args_obj,
                        "succeeded" if error_code is None else "failed",
                        started,
                        error_code=error_code,
                        result_ref=result,
                    )
                )
                if error_code is None and result and result.get("summary"):
                    summary_parts.append(result["summary"])
                if error_code is None and result and result.get("resource_type") == "plan":
                    references.append(
                        {
                            "kind": "plan",
                            "id": result["resource_id"],
                            "label": result["summary"],
                            "state": None,
                        }
                    )
            run.tool_calls = tool_calls
            run.decision_basis = {
                "basis_version": "v1",
                "summary": "; ".join(summary_parts) or "Deterministic pass complete",
                "references": references,
                "rule_versions": {"tool_registry": TOOL_REGISTRY_VERSION, "runner": RUNNER_VERSION},
                "selected_tool_call_ids": [c["call_id"] for c in tool_calls],
            }
            _settle_run(
                session,
                run,
                status="SUCCEEDED",
                result={
                    "summary": "; ".join(summary_parts) or "Deterministic pass complete",
                    "degraded": True,
                    "degrade_code": degrade_code,
                },
            )
        else:
            provider_info = {
                "name": provider.name,
                "model": getattr(provider, "model_name", ""),
                "capability": "tools",
                "data_scope": sorted({"current_state", "memory", "chat"}),
                "consent_version": assembled.consent_version,
            }
            tool_schemas = [
                t.tool_schemas()
                for t in (
                    get_tool(n)
                    for n in (
                        "state.read",
                        "memory.retrieve",
                        "goal.read",
                        "materials.answer",
                        "plan.suggest",
                        "replan.evaluate",
                        "task.create",
                        "task.update",
                        "memory.write",
                        "focus.start",
                        "plan.confirm",
                    )
                )
                if t is not None
            ]
            turn = await provider.generate_with_tools(assembled.rendered, None, tool_schemas)
            turns_used = 1
            usage_total["input_tokens"] += turn.usage.get("input_tokens", 0)
            usage_total["output_tokens"] += turn.usage.get("output_tokens", 0)

            while True:
                if not turn.tool_calls:
                    if turn.text:
                        summary_parts.append(turn.text[:500])
                    break
                if (
                    turns_used > settings.agent_max_model_turns
                    or len(tool_calls) + len(turn.tool_calls) > settings.agent_max_tool_calls
                ):
                    degrade_code = "tool_round_limit"
                    break
                results: list[Any] = []
                for call in turn.tool_calls:
                    tool = get_tool(call.name)
                    call_id = call.call_id or f"call-{len(tool_calls) + 1}"
                    started = utcnow()
                    if tool is None:
                        tool_calls.append(
                            _tool_call_row(
                                call_id,
                                _UnknownTool(call.name),
                                {},
                                "failed",
                                started,
                                error_code="tool_not_registered",
                            )
                        )
                        results.append(
                            _tool_result(call_id, "failed", {"error": "tool_not_registered"})
                        )
                        continue
                    # Stage 1: schema (one repair retry), Stage 2: permission,
                    # Stage 3: display — fixed order (§6.2).
                    args, schema_error = _validate_arguments(tool, call.arguments_json, provider)
                    if schema_error is not None:
                        args = schema_error.get("repaired_args")
                        if args is None:
                            tool_calls.append(
                                _tool_call_row(
                                    call_id,
                                    tool,
                                    {"_raw": call.arguments_json},
                                    "failed",
                                    started,
                                    error_code="tool_arguments_invalid",
                                )
                            )
                            results.append(
                                _tool_result(call_id, "failed", {"error": "tool_arguments_invalid"})
                            )
                            continue
                    decision = evaluate_permission(
                        session,
                        user_id=run.user_id,
                        action=tool.name,
                        scope_validator=tool.scope_validator,
                    )
                    if not (decision.allowed or decision.requires_confirmation):
                        tool_calls.append(
                            _tool_call_row(
                                call_id,
                                tool,
                                args,
                                "failed",
                                started,
                                error_code="permission_denied",
                            )
                        )
                        results.append(
                            _tool_result(call_id, "failed", {"error": "permission_denied"})
                        )
                        continue
                    if tool.required_level <= PermissionLevel.SUGGEST:
                        exec_result, error_code = await _execute_tool(
                            session,
                            run=run,
                            tool=tool,
                            args=args,
                            provider=provider,
                            idempotency_key=None,
                        )
                        status = "succeeded" if error_code is None else "failed"
                        tool_calls.append(
                            _tool_call_row(
                                call_id,
                                tool,
                                args,
                                status,
                                started,
                                error_code=error_code,
                                result_ref=exec_result,
                            )
                        )
                        payload = (
                            exec_result
                            if error_code is None and exec_result is not None
                            else {"error": error_code or "tool_failed"}
                        )
                        results.append(_tool_result(call_id, status, payload))
                        if exec_result and error_code is None and exec_result.get("summary"):
                            summary_parts.append(exec_result["summary"])
                    else:
                        grant = (
                            _level3_grant(session, run.user_id, tool)
                            if tool.required_level == PermissionLevel.AUTO
                            else None
                        )
                        action = create_pending_action(
                            session,
                            run=run,
                            tool=tool,
                            args=args,
                            decision_summary=f"Proposed by {provider.name} tool call",
                            references=references,
                            level3_grant=grant,
                        )
                        pending_ids.append(action.id)
                        if grant is not None:
                            await dispatch_confirmed_action(
                                session, action_id=action.id, provider=provider
                            )
                        tool_calls.append(
                            _tool_call_row(
                                call_id,
                                tool,
                                args,
                                "succeeded",
                                started,
                                result_ref={"pending_action_id": str(action.id)},
                            )
                        )
                        results.append(
                            _tool_result(
                                call_id, "succeeded", {"pending_action_id": str(action.id)}
                            )
                        )
                        summary_parts.append(f"待确认动作已创建：{tool.name}")
                run.tool_calls = tool_calls
                run.usage = usage_total
                session.flush()
                if turns_used >= settings.agent_max_model_turns:
                    degrade_code = degrade_code or "tool_round_limit"
                    break
                turn = await provider.continue_with_tool_results(turn, results)
                turns_used += 1
                usage_total["input_tokens"] += turn.usage.get("input_tokens", 0)
                usage_total["output_tokens"] += turn.usage.get("output_tokens", 0)

            run.usage = usage_total
            run.decision_basis = {
                "basis_version": "v1",
                "summary": "; ".join(summary_parts)[:1000] or "Tool pass complete",
                "references": references,
                "rule_versions": {"tool_registry": TOOL_REGISTRY_VERSION, "runner": RUNNER_VERSION},
                "selected_tool_call_ids": [c["call_id"] for c in tool_calls],
            }
            if pending_ids:
                _settle_run(
                    session,
                    run,
                    status="WAITING_CONFIRMATION",
                    result={
                        "summary": "; ".join(summary_parts)[:1000],
                        "degraded": degrade_code is not None,
                        **({"degrade_code": degrade_code} if degrade_code else {}),
                    },
                )
            else:
                _settle_run(
                    session,
                    run,
                    status="SUCCEEDED",
                    result={
                        "summary": "; ".join(summary_parts)[:1000],
                        "degraded": degrade_code is not None,
                        **({"degrade_code": degrade_code} if degrade_code else {}),
                    },
                )
        run.provider = provider_info
        run.usage = usage_total
        run.budget = {
            "reserved_total": settings.agent_context_reserved_tokens,
            "actual_total": usage_total["input_tokens"] + usage_total["output_tokens"],
        }
        _write_assistant_message(session, run, "; ".join(summary_parts))
        session.commit()
    except Exception as exc:
        session.rollback()
        run = session.get(AgentRun, run_id)
        if run is not None and run.status == "RUNNING":
            _settle_run(
                session,
                run,
                status="FAILED",
                failure={
                    "code": "runner_internal_error",
                    "retryable": True,
                    "safe_message": f"Run failed: {type(exc).__name__}",
                },
            )
            session.commit()
        raise
    final = session.get(AgentRun, run_id)
    assert final is not None
    return final


def _write_assistant_message(session: Session, run: AgentRun, summary: str) -> None:
    if run.invocation_kind != "chat" or not summary:
        return
    session_id, _ = _chat_context(session, run)
    if session_id is None:
        return
    existing = session.scalar(select(ChatMessage).where(ChatMessage.agent_run_id == run.id))
    if existing is not None:
        return
    session.add(
        ChatMessage(
            session_id=session_id,
            user_id=run.user_id,
            role="assistant",
            content=summary[:4000],
            agent_run_id=run.id,
        )
    )


class _UnknownTool:
    """Minimal duck-typed stand-in for audit rows about unknown tools."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.version = "unknown"

    def tool_schemas(self) -> dict[str, Any]:
        return {"name": self.name}


def _tool_result(call_id: str, status: str, payload: dict[str, Any]) -> Any:
    from backend.adapters.model_provider.base import ToolResult

    return ToolResult(
        call_id=call_id,
        status=status,
        safe_result_json=json.dumps(payload, ensure_ascii=False, default=str)[:4000],
    )


def _validate_arguments(
    tool: ToolDefinition, arguments_json: str, provider: Any | None
) -> tuple[Any, dict[str, Any] | None]:
    """Stage 1 of the fixed pipeline: strict schema validation with ONE
    repair retry (error fed back to the provider). Returns (args, None) on
    success or (None, error) / (args, {"repaired_args": args}) semantics
    simplified: on success returns (args, None); on failure returns
    (None, {"repaired": False}) after the repair attempt also failed."""

    try:
        return tool.input_model.model_validate_json(arguments_json), None
    except Exception:
        pass
    if provider is None:
        return None, {"repaired": False}
    try:
        repair = provider.generate(
            f'Return corrected JSON arguments for tool "{tool.name}" matching this'
            f" schema exactly, nothing else: {tool.input_model.model_json_schema()}"
            f"\nOriginal input: {arguments_json}",
        )
        return tool.input_model.model_validate_json(repair), None
    except Exception:
        return None, {"repaired": False}


# ------------------------------------------------------------- watchdogs ---


def sweep_pending_actions(session: Session) -> dict[str, int]:
    """TTL expiry (PENDING only — CONFIRMED never expires, ruling A1) and
    settlement for EXECUTING rows whose execution lease expired.

    An EXECUTING row with a dead lease had its whole transaction rolled
    back with the worker (execution and settlement share one transaction),
    so re-queueing it as FAILED_RETRYABLE under the SAME idempotency key is
    safe: the key guarantees no second side effect even if the lost worker
    somehow completed after all."""

    expired = 0
    lease_lapsed = 0
    rows = list(
        session.scalars(
            select(PendingAction).where(
                PendingAction.status == "PENDING", PendingAction.expires_at <= utcnow()
            )
        )
    )
    for row in rows:
        row.status = "EXPIRED"
        row.updated_at = utcnow()
        expired += 1
        record_audit(
            session,
            action="pending_action.expired",
            actor=AuditActor.SYSTEM.value,
            user_id=row.user_id,
            resource_type="pending_action",
            resource_id=str(row.id),
            details=redact_allowlist(
                {"tool_name": row.tool_name, "status": "EXPIRED"}, _AGENT_AUDIT_ALLOWED
            ),
        )
    session.flush()

    stuck = list(
        session.scalars(select(PendingAction).where(PendingAction.status == "EXECUTING").limit(50))
    )
    for row in stuck:
        if not _lease_expired(row.execution_lease):
            continue
        if row.attempt_count < row.max_attempts:
            row.status = "FAILED_RETRYABLE"
        else:
            row.status = "FAILED"
            row.finished_at = utcnow()
        row.last_error = {
            "code": "execution_lease_expired",
            "message": "Execution lease expired before settlement",
        }
        row.updated_at = utcnow()
        lease_lapsed += 1
        record_audit(
            session,
            action="pending_action.lease_reclaimed",
            actor=AuditActor.SYSTEM.value,
            user_id=row.user_id,
            resource_type="pending_action",
            resource_id=str(row.id),
            details=redact_allowlist(
                {
                    "tool_name": row.tool_name,
                    "status": row.status,
                    "code": "execution_lease_expired",
                },
                _AGENT_AUDIT_ALLOWED,
            ),
        )
    session.commit()
    return {"expired": expired, "lease_lapsed": lease_lapsed}


async def recover_pending_actions(session: Session, *, provider: Any | None = None) -> int:
    """Re-dispatch CONFIRMED/FAILED_RETRYABLE rows (§5.2 recovery worker).
    ``dispatch_confirmed_action`` claims atomically with SKIP LOCKED, so rows
    another live worker holds are skipped, never double-executed."""

    ids = list(
        session.scalars(
            select(PendingAction.id)
            .where(PendingAction.status.in_(("CONFIRMED", "FAILED_RETRYABLE")))
            .limit(20)
        )
    )
    dispatched = 0
    for action_id in ids:
        row = await dispatch_confirmed_action(session, action_id=action_id, provider=provider)
        if row is not None and row.status in ("SUCCEEDED", "FAILED", "FAILED_RETRYABLE"):
            dispatched += 1
    return dispatched


def reclaim_expired_runs(session: Session, *, max_rows: int = 20) -> dict[str, int]:
    """Watchdog for RUNNING runs with expired leases (§3.2).

    Settlement first looks for visible downstream results (pending actions
    created by the lost attempt): found → the attempt settles
    WAITING_CONFIRMATION; not found → FAILED/worker_lease_expired and a
    fresh attempt row is minted under the same operation key."""

    reclaimed = 0
    retried = 0
    rows = list(
        session.scalars(
            select(AgentRun)
            .where(AgentRun.status == "RUNNING")
            .order_by(AgentRun.created_at)
            .limit(max_rows)
        )
    )
    for run in rows:
        if not _lease_expired(run.lease):
            continue
        pend = session.scalars(
            select(PendingAction.id).where(PendingAction.agent_run_id == run.id)
        ).first()
        if pend is not None:
            _settle_run(
                session,
                run,
                status="WAITING_CONFIRMATION",
                result={
                    "summary": "Recovered: pending actions await confirmation",
                    "degraded": True,
                    "degrade_code": "worker_lease_expired",
                },
            )
            reclaimed += 1
        else:
            _settle_run(
                session,
                run,
                status="FAILED",
                failure={
                    "code": "worker_lease_expired",
                    "retryable": True,
                    "safe_message": "Worker lease expired before completion",
                },
            )
            existing_attempts = list(
                session.scalars(
                    select(AgentRun.attempt_no).where(
                        AgentRun.user_id == run.user_id,
                        AgentRun.operation_key == run.operation_key,
                    )
                )
            )
            retry = AgentRun(
                user_id=run.user_id,
                status="QUEUED",
                invocation_kind="retry",
                trigger_ref=run.trigger_ref,
                parent_run_id=run.id,
                operation_key=run.operation_key,
                attempt_no=max(existing_attempts or [0]) + 1,
                client_request_id=None,
                runner_version=RUNNER_VERSION,
                tool_registry_version=TOOL_REGISTRY_VERSION,
                prompt_version=run.prompt_version,
            )
            session.add(retry)
            audit_run_queued(session, retry)
            session.flush()
            reclaimed += 1
            retried += 1
        session.commit()
    return {"reclaimed": reclaimed, "retried": retried}


# ------------------------------------------------------ mutation cache -----


def cached_mutation_response(
    session: Session, *, pending_action_id: uuid.UUID, mutation_id: str
) -> dict[str, Any] | None:
    row = session.scalar(
        select(PendingActionMutation).where(
            PendingActionMutation.pending_action_id == pending_action_id,
            PendingActionMutation.mutation_id == mutation_id,
        )
    )
    return row.response if row is not None else None


def store_mutation_response(
    session: Session,
    *,
    pending_action_id: uuid.UUID,
    user_id: uuid.UUID,
    mutation_id: str,
    kind: str,
    response: dict[str, Any],
) -> None:
    session.add(
        PendingActionMutation(
            pending_action_id=pending_action_id,
            user_id=user_id,
            mutation_id=mutation_id,
            kind=kind,
            response=response,
        )
    )
    session.flush()


__all__ = [
    "audit_run_queued",
    "cached_mutation_response",
    "claim_run",
    "create_pending_action",
    "dispatch_confirmed_action",
    "execute_run",
    "heartbeat_run",
    "pending_action_read",
    "reclaim_expired_runs",
    "recover_pending_actions",
    "store_mutation_response",
    "sweep_pending_actions",
]
