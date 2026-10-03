"""First-batch agent tool implementations (D-034 §4).

Level 0/1 tools read or suggest deterministically; Level 2 tools only ever
create ``pending_actions`` (the runner confirms their args through the
registry's display builder — the executions here run AFTER user
confirmation or a valid Level 3 grant). ``plan.suggest`` and
``replan.evaluate`` are the deterministic fallback: the same registry
entries the model would call, executed directly when no provider context is
allowed (``capability: "none"``) — the M4 exit criterion's server side.

Registered but not yet implemented executors (calendar.write, message.send,
file.delete, data.delete) fail honestly with ``tool_not_implemented``
(non-retryable) instead of faking success.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.base import utcnow
from backend.models.enums import (
    GoalStatus,
    MemoryCorrectionStatus,
    MemoryKind,
    PlanStatus,
    TaskStatus,
)
from backend.models.goal import Goal
from backend.models.memory import Memory
from backend.models.plan import Plan
from backend.models.task import Task
from backend.services.current_state import get_or_create_state
from backend.services.focus import create_focus_session
from backend.services.grounded_answers import (
    GroundingPermissionDenied,
    answer_question,
)
from backend.services.lookup import get_task
from backend.services.memory_retrieval import retrieve_memories
from backend.services.model_consent import active_consent_version
from backend.services.notification_delivery import settle_and_deliver
from backend.services.planner import generate_plan
from backend.services.replan_triggers import evaluate_replan_triggers
from backend.services.tool_registry import (
    ToolDefinition,
    ToolError,
    register_tool,
    strict_scope_validator,
)

TOOL_VERSION = "1.0.0"


@dataclass
class ExecContext:
    """Everything a tool executor may touch. The runner is the only
    constructor; tools never open their own sessions."""

    session: Session
    user_id: uuid.UUID
    provider: Any | None = None
    idempotency_key: str | None = None
    # Set for executions launched from a confirmed pending action; tools that
    # create domain records reference it for auditability.
    pending_action_id: uuid.UUID | None = None


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- inputs --


class StateReadArgs(_StrictModel):
    pass


class MemoryRetrieveArgs(_StrictModel):
    query: str | None = Field(default=None, max_length=500)
    limit: int = Field(default=5, ge=1, le=20)


class GoalReadArgs(_StrictModel):
    pass


class MaterialsAnswerArgs(_StrictModel):
    course_name: str = Field(min_length=1, max_length=300)
    question: str = Field(min_length=1, max_length=2000)


class PlanSuggestArgs(_StrictModel):
    goal_id: uuid.UUID | None = None
    horizon_minutes: int = Field(default=240, ge=30, le=24 * 60)
    max_tasks: int = Field(default=10, ge=1, le=20)


class ReplanEvaluateArgs(_StrictModel):
    pass


class PlanConfirmArgs(_StrictModel):
    plan_id: uuid.UUID


class TaskCreateArgs(_StrictModel):
    title: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=4000)
    deadline: datetime | None = None
    estimated_duration_minutes: int | None = Field(default=None, ge=5, le=24 * 60)
    priority: int | None = Field(default=None, ge=0, le=10)
    goal_id: uuid.UUID | None = None


class TaskUpdateArgs(_StrictModel):
    task_id: uuid.UUID
    title: str | None = Field(default=None, min_length=1, max_length=300)
    deadline: datetime | None = None
    estimated_duration_minutes: int | None = Field(default=None, ge=5, le=24 * 60)
    status: TaskStatus | None = None
    clear_deadline: bool = False

    @model_validator(mode="after")
    def _at_least_one_change(self) -> TaskUpdateArgs:
        if (
            self.title is None
            and self.deadline is None
            and self.estimated_duration_minutes is None
            and self.status is None
        ):
            raise ValueError("task.update needs at least one field to change")
        return self


class MemoryWriteArgs(_StrictModel):
    content: str = Field(min_length=1, max_length=4000)
    title: str | None = Field(default=None, max_length=300)
    kind: MemoryKind = MemoryKind.FACT
    domain: str = Field(default="general", max_length=50)
    subject_key: str | None = Field(default=None, max_length=300)


class FocusStartArgs(_StrictModel):
    task_id: uuid.UUID


class NotifyPushArgs(_StrictModel):
    category: str = Field(min_length=1, max_length=50)
    title: str = Field(min_length=1, max_length=200)
    body: str | None = Field(default=None, max_length=1000)


# Server-defined category vocabulary (contract §6: the client renders the
# words, the server defines them). A3 wires exactly one producer — replan
# suggestions surfaced by the trigger engine.
NOTIFY_CATEGORY_REPLAN = "replan"


class _PlaceholderArgs(_StrictModel):
    """Registered-but-unimplemented Level 2 tools share a permissive input:
    validation of their real shape lands with their implementation."""

    model_config = ConfigDict(extra="allow")


# ------------------------------------------------------------ executors ---


async def _exec_state_read(ctx: ExecContext, args: StateReadArgs) -> dict[str, Any]:
    state = get_or_create_state(ctx.session, ctx.user_id)
    return {
        "summary": "Current state read",
        "state_version": state.version,
        "available_minutes": state.available_minutes,
        "current_task_id": str(state.current_task_id) if state.current_task_id else None,
        "current_plan_id": str(state.current_plan_id) if state.current_plan_id else None,
        "pending_task_count": len(state.pending_task_ids or []),
    }


async def _exec_memory_retrieve(ctx: ExecContext, args: MemoryRetrieveArgs) -> dict[str, Any]:
    rows = retrieve_memories(
        ctx.session,
        user_id=ctx.user_id,
        kinds=[MemoryKind.FACT, MemoryKind.HABIT, MemoryKind.PREFERENCE],
        limit=args.limit,
    )
    entries: list[dict[str, Any]] = []
    for row in rows:
        entry: dict[str, Any] = {
            "id": str(row.id),
            "kind": row.kind.value if row.kind else None,
            "subject_key": row.subject_key,
            "confidence": row.confidence,
            "content_revision": row.content_revision,
        }
        # Memory content only leaves the backend under an active global
        # model-context consent — same gate as the assembled context.
        if active_consent_version(ctx.session, ctx.user_id) is not None:
            entry["content"] = row.content
        entries.append(entry)
    return {"summary": f"{len(entries)} memories", "memories": entries}


async def _exec_goal_read(ctx: ExecContext, args: GoalReadArgs) -> dict[str, Any]:
    rows = list(
        ctx.session.scalars(
            select(Goal).where(Goal.user_id == ctx.user_id, Goal.status == GoalStatus.ACTIVE)
        )
    )
    return {
        "summary": f"{len(rows)} active goals",
        "goals": [
            {"id": str(row.id), "title": row.title, "priority": row.priority} for row in rows
        ],
    }


async def _exec_materials_answer(ctx: ExecContext, args: MaterialsAnswerArgs) -> dict[str, Any]:
    if ctx.provider is None:
        raise ToolError(
            "provider_unavailable",
            "Course-material answering needs a model provider",
            retryable=True,
        )
    try:
        answer = await answer_question(
            ctx.session,
            ctx.provider,
            user_id=ctx.user_id,
            course_name=args.course_name,
            question=args.question,
            model_version=TOOL_VERSION,
        )
    except GroundingPermissionDenied as exc:
        # D-033 per-course gate missing — degrade honestly, never fake grounded.
        raise ToolError(
            "grounding_consent_missing",
            f"Grounding is not enabled: {exc}",
            retryable=False,
        ) from exc
    return {
        "summary": "Grounded answer",
        "resource_type": "material_answer",
        "resource_id": str(answer.id),
    }


async def _exec_plan_suggest(ctx: ExecContext, args: PlanSuggestArgs) -> dict[str, Any]:
    plan = generate_plan(
        ctx.session,
        user_id=ctx.user_id,
        goal_id=args.goal_id,
        horizon_minutes=args.horizon_minutes,
        max_tasks=args.max_tasks,
        generated_by="agent:plan.suggest",
    )
    return {
        "summary": f"Plan suggested ({len(plan.items)} items)",
        "resource_type": "plan",
        "resource_id": str(plan.id),
    }


async def _exec_replan_evaluate(ctx: ExecContext, args: ReplanEvaluateArgs) -> dict[str, Any]:
    suggestion = evaluate_replan_triggers(ctx.session, user_id=ctx.user_id)
    if suggestion is None:
        return {"summary": "No replan trigger fired"}
    return {
        "summary": "Replan suggestion created",
        "resource_type": "plan",
        "resource_id": str(suggestion.id),
    }


def _confirm_plan(session: Session, user_id: uuid.UUID, plan_id: uuid.UUID) -> Plan:
    plan = session.scalar(select(Plan).where(Plan.id == plan_id, Plan.user_id == user_id))
    if plan is None:
        raise ToolError("plan_not_found", "Plan not found", retryable=False)
    if plan.status == PlanStatus.CONFIRMED:
        return plan  # retry-safe: the desired end state already holds
    if plan.status not in (PlanStatus.PENDING_CONFIRMATION, PlanStatus.DRAFT):
        raise ToolError(
            "plan_not_confirmable",
            f"Plan in status {plan.status.value} cannot be confirmed",
            retryable=False,
        )
    plan.status = PlanStatus.CONFIRMED
    plan.confirmed_at = utcnow()
    session.flush()
    return plan


async def _exec_plan_confirm(ctx: ExecContext, args: PlanConfirmArgs) -> dict[str, Any]:
    plan = _confirm_plan(ctx.session, ctx.user_id, args.plan_id)
    return {
        "summary": "Plan confirmed",
        "resource_type": "plan",
        "resource_id": str(plan.id),
    }


async def _exec_task_create(ctx: ExecContext, args: TaskCreateArgs) -> dict[str, Any]:
    task = Task(
        user_id=ctx.user_id,
        title=args.title,
        description=args.description,
        source="agent",
        deadline=args.deadline,
        estimated_duration_minutes=args.estimated_duration_minutes,
        priority=args.priority or 0,
        goal_id=args.goal_id,
    )
    ctx.session.add(task)
    ctx.session.flush()
    return {
        "summary": f"Task created: {args.title}",
        "resource_type": "task",
        "resource_id": str(task.id),
    }


async def _exec_task_update(ctx: ExecContext, args: TaskUpdateArgs) -> dict[str, Any]:
    task = get_task(ctx.session, user_id=ctx.user_id, task_id=args.task_id)
    before = {
        "title": task.title,
        "deadline": task.deadline.isoformat() if task.deadline else None,
    }
    if args.title is not None:
        task.title = args.title
    if args.deadline is not None:
        task.deadline = args.deadline
    elif args.clear_deadline:
        task.deadline = None
    if args.estimated_duration_minutes is not None:
        task.estimated_duration_minutes = args.estimated_duration_minutes
    if args.status is not None:
        task.status = args.status
    ctx.session.flush()
    return {
        "summary": "Task updated",
        "resource_type": "task",
        "resource_id": str(task.id),
        "before": before,
    }


async def _exec_memory_write(ctx: ExecContext, args: MemoryWriteArgs) -> dict[str, Any]:
    # Model-produced memory stays UNREVIEWED with confidence capped at 0.5
    # (D-031 §3): it may never become a stable fact without the user.
    memory = Memory(
        user_id=ctx.user_id,
        content=args.content,
        kind=args.kind,
        domain=args.domain,
        subject_key=args.subject_key,
        confidence=0.5,
        correction_status=MemoryCorrectionStatus.UNREVIEWED,
        source={"tool": "memory.write", "runner": "agent"},
    )
    ctx.session.add(memory)
    ctx.session.flush()
    return {
        "summary": "Memory saved for review",
        "resource_type": "memory",
        "resource_id": str(memory.id),
    }


async def _exec_focus_start(ctx: ExecContext, args: FocusStartArgs) -> dict[str, Any]:
    task = get_task(ctx.session, user_id=ctx.user_id, task_id=args.task_id)
    session = create_focus_session(ctx.session, user_id=ctx.user_id, task=task)
    return {
        "summary": f"Focus started for: {task.title}",
        "resource_type": "focus_session",
        "resource_id": str(session.id),
    }


async def _exec_notify_push(ctx: ExecContext, args: NotifyPushArgs) -> dict[str, Any]:
    # Level 3 dispatch: the grant re-verification happens in the runner
    # immediately before this executes (§5.1). A3 delivery: the §6/§8
    # disturbance budget settles atomically here — category gate, quiet
    # hours (user-local, midnight-crossing legal) and the per-local-day
    # budget. Suppression is policy working as intended, not a failure:
    # the pending action settles SUCCEEDED with an honest suppressed
    # summary, and the audit ledger carries the reason.
    outcome = settle_and_deliver(
        ctx.session,
        user_id=ctx.user_id,
        category=args.category,
        pending_action_id=ctx.pending_action_id,
    )
    return {
        "summary": outcome["summary"],
        "resource_type": "notification",
        "delivered": outcome["delivered"],
        "suppressed_reason": outcome["reason"],
    }


async def _exec_not_implemented(ctx: ExecContext, args: _PlaceholderArgs) -> dict[str, Any]:
    raise ToolError(
        "tool_not_implemented",
        "This tool is registered but its executor lands in a later slice",
        retryable=False,
    )


# ------------------------------------------------------ display builders --


def _display(
    summary: str, parameters: list[dict[str, Any]], impact: str, risk_note: str | None = None
) -> dict[str, Any]:
    out: dict[str, Any] = {"summary": summary, "parameters": parameters, "impact": impact}
    if risk_note:
        out["risk_note"] = risk_note
    return out


# ------------------------------------------------------- registration -----


def _fmt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


register_tool(
    ToolDefinition(
        name="state.read",
        version=TOOL_VERSION,
        description=(
            "Read the user's current state projection (version, availability, current task/plan)."
        ),
        input_model=StateReadArgs,
        side_effect=False,
        data_scope=frozenset({"current_state"}),
        audit_fields=frozenset(),
        display_builder=lambda a: _display("读取当前状态", [], "无（只读）"),
        execute=_exec_state_read,
    )
)

register_tool(
    ToolDefinition(
        name="memory.retrieve",
        version=TOOL_VERSION,
        description="Retrieve memory entries (fact/habit/preference) for reasoning.",
        input_model=MemoryRetrieveArgs,
        side_effect=False,
        data_scope=frozenset({"memory"}),
        audit_fields=frozenset({"limit"}),
        display_builder=lambda a: _display(
            f"检索记忆（前 {a.limit} 条）",
            [{"label": "条数上限", "value": str(a.limit)}],
            "无（只读）",
        ),
        execute=_exec_memory_retrieve,
    )
)

register_tool(
    ToolDefinition(
        name="goal.read",
        version=TOOL_VERSION,
        description="Read the user's active goals.",
        input_model=GoalReadArgs,
        side_effect=False,
        data_scope=frozenset(),
        audit_fields=frozenset(),
        display_builder=lambda a: _display("读取目标", [], "无（只读）"),
        execute=_exec_goal_read,
    )
)

register_tool(
    ToolDefinition(
        name="materials.answer",
        version=TOOL_VERSION,
        description=(
            "Answer a question from the user's course materials"
            " (D-033 gated, grounded citations only)."
        ),
        input_model=MaterialsAnswerArgs,
        side_effect=False,
        data_scope=frozenset({"materials"}),
        audit_fields=frozenset({"course_name"}),
        display_builder=lambda a: _display(
            "课程资料问答",
            [
                {"label": "课程", "value": a.course_name},
                {"label": "问题", "value": a.question[:120]},
            ],
            "无（只读，发送命中片段受课程同意约束）",
        ),
        execute=_exec_materials_answer,
    )
)

register_tool(
    ToolDefinition(
        name="plan.suggest",
        version=TOOL_VERSION,
        description=(
            "Deterministically suggest a study plan from pending tasks and current state."
            " Also the provider-outage fallback."
        ),
        input_model=PlanSuggestArgs,
        side_effect=True,
        idempotency="natural",
        data_scope=frozenset({"current_state"}),
        audit_fields=frozenset({"goal_id", "horizon_minutes", "max_tasks"}),
        display_builder=lambda a: _display(
            "生成计划建议",
            [
                {"label": "目标", "value": _fmt(a.goal_id)},
                {"label": "时间窗（分钟）", "value": str(a.horizon_minutes)},
                {"label": "任务上限", "value": str(a.max_tasks)},
            ],
            "创建待确认的计划（不改动已确认计划）",
        ),
        execute=_exec_plan_suggest,
    )
)

register_tool(
    ToolDefinition(
        name="replan.evaluate",
        version=TOOL_VERSION,
        description="Evaluate replan triggers and create a replan suggestion when one fires.",
        input_model=ReplanEvaluateArgs,
        side_effect=True,
        idempotency="natural",
        data_scope=frozenset({"current_state"}),
        audit_fields=frozenset(),
        display_builder=lambda a: _display("评估重排触发器", [], "最多创建一条重排建议"),
        execute=_exec_replan_evaluate,
    )
)

register_tool(
    ToolDefinition(
        name="plan.confirm",
        version=TOOL_VERSION,
        description="Confirm a pending plan and make it the user's current plan.",
        input_model=PlanConfirmArgs,
        side_effect=True,
        idempotency="required",
        idempotency_key=lambda a: f"plan.confirm:{a.plan_id}",
        failure_mode="create_pending",
        data_scope=frozenset(),
        audit_fields=frozenset({"plan_id"}),
        display_builder=lambda a: _display(
            "确认计划",
            [{"label": "计划", "value": str(a.plan_id)}],
            "该计划将成为当前计划",
            "将改变已确认的计划安排",
        ),
        execute=_exec_plan_confirm,
    )
)

register_tool(
    ToolDefinition(
        name="task.create",
        version=TOOL_VERSION,
        description="Create a task on the user's behalf.",
        input_model=TaskCreateArgs,
        side_effect=True,
        idempotency="required",
        idempotency_key=(
            lambda a: f"task.create:{a.title}:{a.deadline.isoformat() if a.deadline else ''}"
        ),
        failure_mode="create_pending",
        data_scope=frozenset(),
        audit_fields=frozenset({"title", "deadline", "estimated_duration_minutes", "goal_id"}),
        display_builder=lambda a: _display(
            f"创建任务：{a.title}",
            [
                {"label": "标题", "value": a.title},
                {"label": "截止", "value": _fmt(a.deadline)},
                {"label": "预计时长（分钟）", "value": _fmt(a.estimated_duration_minutes)},
                {"label": "目标", "value": _fmt(a.goal_id)},
            ],
            "将在你的任务列表新增一条任务",
        ),
        execute=_exec_task_create,
    )
)

register_tool(
    ToolDefinition(
        name="task.update",
        version=TOOL_VERSION,
        description="Modify an existing task (title, deadline, estimate or status).",
        input_model=TaskUpdateArgs,
        side_effect=True,
        idempotency="required",
        idempotency_key=lambda a: (
            f"task.update:{a.task_id}:{a.title or ''}:"
            f"{a.deadline.isoformat() if a.deadline else ''}:"
            f"{a.status.value if a.status else ''}"
        ),
        failure_mode="create_pending",
        data_scope=frozenset(),
        audit_fields=frozenset({"task_id", "title", "deadline", "status"}),
        display_builder=lambda a: _display(
            "更新任务",
            [
                {"label": "任务", "value": str(a.task_id)},
                {"label": "新标题", "value": _fmt(a.title)},
                {"label": "新截止", "value": _fmt(a.deadline)},
                {"label": "新状态", "value": a.status.value if a.status else "—"},
            ],
            "将修改现有任务字段",
        ),
        execute=_exec_task_update,
    )
)

register_tool(
    ToolDefinition(
        name="memory.write",
        version=TOOL_VERSION,
        description=(
            "Save a memory entry for the user (saved as UNREVIEWED, confidence capped at 0.5)."
        ),
        input_model=MemoryWriteArgs,
        side_effect=True,
        idempotency="required",
        idempotency_key=lambda a: f"memory.write:{hash(a.content) & 0xFFFFFFFFFFFF}:{a.kind.value}",
        failure_mode="create_pending",
        data_scope=frozenset(),
        audit_fields=frozenset({"kind", "domain", "subject_key"}),
        display_builder=lambda a: _display(
            "写入记忆（待复核）",
            [
                {"label": "类型", "value": a.kind.value},
                {"label": "内容", "value": a.content[:120]},
            ],
            "将保存为未复核记忆（置信度≤0.5），可在记忆页修改或删除",
        ),
        execute=_exec_memory_write,
    )
)

register_tool(
    ToolDefinition(
        name="focus.start",
        version=TOOL_VERSION,
        description="Start a focus session for a task on the user's behalf.",
        input_model=FocusStartArgs,
        side_effect=True,
        idempotency="required",
        idempotency_key=lambda a: f"focus.start:{a.task_id}",
        failure_mode="create_pending",
        data_scope=frozenset(),
        audit_fields=frozenset({"task_id"}),
        display_builder=lambda a: _display(
            "开始专注",
            [{"label": "任务", "value": str(a.task_id)}],
            "将为该任务启动一个专注会话",
            "代表你启动专注，占用该任务的专注锁",
        ),
        execute=_exec_focus_start,
    )
)

register_tool(
    ToolDefinition(
        name="notify.push",
        version=TOOL_VERSION,
        description=(
            "Send a proactive push notification (Level 3; requires an active scoped grant)."
        ),
        input_model=NotifyPushArgs,
        side_effect=True,
        idempotency="required",
        idempotency_key=lambda a: f"notify.push:{a.category}:{hash(a.title) & 0xFFFFFFFFFFFF}",
        failure_mode="fail_closed",
        data_scope=frozenset(),
        audit_fields=frozenset({"category"}),
        # §5.3: scope must name categories and channels explicitly; unknown
        # fields, empty scope and wildcards all deny.
        scope_validator=strict_scope_validator(
            frozenset({"categories", "channels", "local_time_window"}),
            list_keys=frozenset({"categories", "channels"}),
        ),
        display_builder=lambda a: _display(
            f"发送通知（{a.category}）",
            [
                {"label": "类别", "value": a.category},
                {"label": "标题", "value": a.title},
            ],
            "将向你推送一条通知",
            "对外发送类动作，仅在有效授权（Level 3）下自动执行",
        ),
        execute=_exec_notify_push,
    )
)

for _name in ("calendar.write", "message.send", "file.delete", "data.delete"):
    register_tool(
        ToolDefinition(
            name=_name,
            version=TOOL_VERSION,
            description=f"{_name}: registered Level 2 tool; executor lands in a later slice.",
            input_model=_PlaceholderArgs,
            side_effect=True,
            idempotency="required",
            idempotency_key=lambda a, _n=_name: f"{_n}:placeholder",
            failure_mode="create_pending",
            data_scope=frozenset(),
            audit_fields=frozenset(),
            display_builder=lambda a, _n=_name: _display(
                _n,
                [],
                "该动作的执行器在后续切片落地",
                "当前仅登记，确认后会明确失败（tool_not_implemented）",
            ),
            execute=_exec_not_implemented,
        )
    )


__all__ = ["ExecContext"]
