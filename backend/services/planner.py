"""Deterministic baseline planner.

M0 does not ship an LLM planner. This module provides a transparent,
reproducible planner so the full loop (Task + deadline -> Plan -> confirm ->
Focus -> result -> re-plan) can be exercised and tested. The LLM planner in M1
will reuse the same Plan model and permission layer.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.core.errors import ConflictError, NotFoundError
from backend.db.base import utcnow
from backend.models.enums import PlanStatus, TaskStatus
from backend.models.goal import Goal
from backend.models.plan import Plan, PlanItem
from backend.models.task import Task
from backend.services.current_state import get_or_create_state, pending_tasks

DEFAULT_TASK_MINUTES = 60
STRATEGY = "deadline_then_priority"


def start_of_today() -> datetime:
    """Start of the current day in the configured timezone, as UTC."""

    timezone = ZoneInfo(get_settings().default_timezone)
    local_now = datetime.now(timezone)
    local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return local_start.astimezone(UTC)


def is_client_valid_plan(plan: Plan) -> bool:
    """Whether every plan item satisfies the desktop client's PlanItemSchema.

    The client requires non-null ``task_id``, ``start_at`` and ``end_at``. Manual
    plans may omit them, so they must never be served by ``/v1/plans/today``.
    """

    return all(
        item.task_id is not None and item.planned_start is not None and item.planned_end is not None
        for item in plan.items
    )


def generate_plan(
    session: Session,
    *,
    user_id: uuid.UUID,
    goal_id: uuid.UUID | None = None,
    start_at: datetime | None = None,
    horizon_minutes: int = 240,
    max_tasks: int = 10,
    generated_by: str = "deterministic_planner",
    status: PlanStatus = PlanStatus.PENDING_CONFIRMATION,
    replaces_plan_id: uuid.UUID | None = None,
    replan_reason: str | None = None,
    extra_basis: dict[str, object] | None = None,
) -> Plan:
    start = start_at if start_at is not None else utcnow()

    tasks = pending_tasks(session, user_id, goal_id=goal_id)[:max_tasks]
    state = get_or_create_state(session, user_id)

    plan = Plan(
        user_id=user_id,
        goal_id=goal_id,
        replaces_plan_id=replaces_plan_id,
        title=_plan_title(session, user_id, goal_id),
        status=status,
        permission_level=2,
        generated_by=generated_by,
        replan_reason=replan_reason,
        basis={
            "strategy": STRATEGY,
            "task_ids": [str(task.id) for task in tasks],
            "current_state_version": state.version,
            "horizon_minutes": horizon_minutes,
            "start_at": start.isoformat(),
            "generated_at": utcnow().isoformat(),
            **(extra_basis or {}),
        },
    )

    cursor = start
    horizon_end = start + timedelta(minutes=horizon_minutes)
    for index, task in enumerate(tasks):
        minutes = task.estimated_duration_minutes or DEFAULT_TASK_MINUTES
        planned_end = cursor + timedelta(minutes=minutes)
        if index > 0 and planned_end > horizon_end:
            break
        plan.items.append(
            PlanItem(
                task_id=task.id,
                title=task.title,
                order_index=index,
                planned_start=cursor,
                planned_end=planned_end,
                planned_minutes=minutes,
            )
        )
        cursor = planned_end

    session.add(plan)
    session.flush()
    return plan


def latest_open_plan(
    session: Session,
    user_id: uuid.UUID,
    *,
    since: datetime | None = None,
    scan: int = 10,
) -> Plan | None:
    """Return the most recent client-valid draft/pending plan created since ``since``.

    Used by the client-facing ``/plans/today`` so repeated reads reuse the same
    proposal instead of generating a new plan on every request, while never
    reusing a stale (cross-day) or client-incompatible draft.
    """

    conditions = [
        Plan.user_id == user_id,
        Plan.status.in_([PlanStatus.DRAFT, PlanStatus.PENDING_CONFIRMATION]),
    ]
    if since is not None:
        conditions.append(Plan.created_at >= since)
    stmt = select(Plan).where(*conditions).order_by(Plan.created_at.desc()).limit(scan)
    for plan in session.scalars(stmt):
        if is_client_valid_plan(plan):
            return plan
    return None


def replan(
    session: Session,
    *,
    user_id: uuid.UUID,
    plan_id: uuid.UUID,
    reason: str,
    horizon_minutes: int = 240,
) -> Plan:
    original = session.scalar(select(Plan).where(Plan.id == plan_id, Plan.user_id == user_id))
    if original is None:
        raise NotFoundError("Plan not found")

    if original.status not in (
        PlanStatus.DRAFT,
        PlanStatus.PENDING_CONFIRMATION,
        PlanStatus.CONFIRMED,
    ):
        raise ConflictError(f"Plan in status {original.status.value} cannot be re-planned")

    planned_task_ids = [item.task_id for item in original.items if item.task_id is not None]
    completed_item_ids: list[str] = []
    if planned_task_ids:
        completed_rows = session.scalars(
            select(Task.id).where(
                Task.id.in_(planned_task_ids), Task.status == TaskStatus.COMPLETED
            )
        )
        completed_item_ids = [str(task_id) for task_id in completed_rows]

    original.status = PlanStatus.SUPERSEDED
    session.flush()

    return generate_plan(
        session,
        user_id=user_id,
        goal_id=original.goal_id,
        horizon_minutes=horizon_minutes,
        replaces_plan_id=original.id,
        replan_reason=reason,
        extra_basis={
            "replaced_plan_id": str(original.id),
            "completed_task_ids": completed_item_ids,
            "original_execution_result": original.execution_result,
        },
    )


def _plan_title(session: Session, user_id: uuid.UUID, goal_id: uuid.UUID | None) -> str:
    if goal_id is not None:
        goal = session.scalar(select(Goal).where(Goal.id == goal_id, Goal.user_id == user_id))
        if goal is not None:
            return f"Plan for: {goal.title}"
    return f"Study plan {utcnow().date().isoformat()}"


def remaining_estimate_minutes(tasks: list[Task]) -> int:
    total = 0
    for task in tasks:
        if task.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED):
            continue
        remaining = task.estimated_duration_minutes or DEFAULT_TASK_MINUTES
        if task.actual_duration_minutes:
            remaining = max(0, remaining - task.actual_duration_minutes)
        total += remaining
    return total
