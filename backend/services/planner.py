"""Deterministic baseline planner.

M0 does not ship an LLM planner. This module provides a transparent,
reproducible planner so the full loop (Task + deadline -> Plan -> confirm ->
Focus -> result -> re-plan) can be exercised and tested. The LLM planner in M1
will reuse the same Plan model and permission layer.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.errors import ConflictError, NotFoundError
from backend.db.base import utcnow
from backend.models.enums import PlanStatus, TaskStatus
from backend.models.goal import Goal
from backend.models.plan import Plan, PlanItem
from backend.models.task import Task
from backend.services.current_state import get_or_create_state, pending_tasks

DEFAULT_TASK_MINUTES = 60
STRATEGY = "deadline_then_priority"


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
