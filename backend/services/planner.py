"""Deterministic baseline planner.

M0 does not ship an LLM planner. This module provides a transparent,
reproducible planner so the full loop (Task + deadline -> Plan -> confirm ->
Focus -> result -> re-plan) can be exercised and tested. The LLM planner in M1
will reuse the same Plan model and permission layer.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.core.errors import ConflictError, NotFoundError
from backend.db.base import utcnow
from backend.models.enums import PlanStatus, TaskStatus
from backend.models.goal import Goal
from backend.models.plan import Plan, PlanItem
from backend.models.task import Task
from backend.services.current_state import (
    current_plan_for,
    get_or_create_state,
    pending_tasks,
    recompute_current_state,
)
from backend.services.plan_validity import client_invalid_item_exists, is_client_valid_plan

DEFAULT_TASK_MINUTES = 60
STRATEGY = "deadline_then_priority"


def start_of_today() -> datetime:
    """Start of the current day in the configured timezone, as UTC."""

    timezone = ZoneInfo(get_settings().default_timezone)
    local_now = datetime.now(timezone)
    local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return local_start.astimezone(UTC)


def _today_lock_key(user_id: uuid.UUID, day_start: datetime) -> int:
    """Stable PostgreSQL advisory-lock key for a (user, local day) pair."""

    material = f"{user_id}:{day_start.date().isoformat()}".encode()
    return int.from_bytes(hashlib.blake2b(material, digest_size=8).digest(), "big", signed=True)


def lock_today_proposal(session: Session, *, user_id: uuid.UUID, day_start: datetime) -> None:
    """Serialize generation of one user's today proposal at the database level.

    ``GET /v1/plans/today`` does a read-then-insert. Without a lock, two
    concurrent first requests can both observe "no proposal" and insert
    duplicates. A transaction-level advisory lock keyed by (user, local day)
    makes the second request wait until the first commits, after which it sees
    the existing row. The lock is released when the request transaction ends.
    On non-PostgreSQL dialects this is a no-op, but only PostgreSQL runs the API
    in this project.
    """

    if session.get_bind().dialect.name != "postgresql":
        return
    session.execute(select(func.pg_advisory_xact_lock(_today_lock_key(user_id, day_start))))


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
) -> Plan | None:
    """Return the most recent client-valid draft/pending plan created since ``since``.

    Used by the client-facing ``/plans/today`` so repeated reads reuse the same
    proposal instead of generating a new plan on every request, while never
    reusing a stale (cross-day) or client-incompatible draft.

    Client validity is enforced in SQL (no item with a null ``task_id`` /
    ``planned_start`` / ``planned_end``) rather than by scanning a fixed number
    of rows in Python: a fixed scan window could skip a valid plan sitting
    behind several invalid proposals and generate a duplicate.

    An empty draft is only reusable while the user has no pending tasks
    (merge-1 report D7): ``is_client_valid_plan`` treats empty items as valid,
    so reusing an empty draft once tasks exist would hide those tasks from
    today until the draft is manually cancelled.
    """

    has_any_item = select(PlanItem.id).where(PlanItem.plan_id == Plan.id).exists()
    has_pending_tasks = (
        select(Task.id)
        .where(
            Task.user_id == user_id,
            Task.status.in_((TaskStatus.TODO, TaskStatus.IN_PROGRESS)),
        )
        .exists()
    )
    conditions = [
        Plan.user_id == user_id,
        Plan.status.in_([PlanStatus.DRAFT, PlanStatus.PENDING_CONFIRMATION]),
        or_(has_any_item, ~has_pending_tasks),
        ~client_invalid_item_exists(),
    ]
    if since is not None:
        conditions.append(Plan.created_at >= since)
    stmt = select(Plan).where(*conditions).order_by(Plan.created_at.desc()).limit(1)
    return session.scalar(stmt)


def resolve_today_plan(session: Session, user_id: uuid.UUID) -> Plan:
    """Return the client's today plan, generating one under a per-day lock.

    Selection rules are frozen in DECISIONS.md D-019: the user's latest
    client-valid confirmed plan wins, otherwise a client-valid draft/pending
    plan created since the start of today, otherwise a newly generated plan.
    The advisory lock makes concurrent first requests idempotent.
    """

    day_start = start_of_today()
    lock_today_proposal(session, user_id=user_id, day_start=day_start)

    plan = current_plan_for(session, user_id)
    if plan is not None and not is_client_valid_plan(plan):
        plan = None
    if plan is None:
        plan = latest_open_plan(session, user_id, since=day_start)
    if plan is None:
        plan = generate_plan(session, user_id=user_id)
        recompute_current_state(session, user_id)
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
