"""Deterministic planner v2 (slots_v2, D-031 §1/§4).

No LLM (D-030): the planner is a transparent, reproducible baseline. v2 is
state-aware and explainable — it reads today's schedule through the same
`_today_schedule_entries` the projection uses, places tasks into free slots
only, caps placement by the available-minutes budget (D-027口径) and writes a
structured per-item basis; the human reason is rendered from that basis in
`plan_reason`/client_view (the basis is the record, the reason is a view).
The plan-level basis keeps the `slots_v2` strategy tag so new fixtures can be
compared against historical `deadline_then_priority` plans.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
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
    _overlap_minutes,
    _task_remaining_minutes,
    _today_schedule_entries,
    current_plan_for,
    get_or_create_state,
    pending_tasks,
    recompute_current_state,
)
from backend.services.estimates import DEFAULT_TASK_MINUTES, Estimate, estimate_for_task
from backend.services.plan_validity import client_invalid_item_exists, is_client_valid_plan

# Legacy strategy tag (v1 plans in the wild); kept for fixture comparison.
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
            "strategy": STRATEGY_V2,
            "task_ids": [str(task.id) for task in tasks],
            "current_state_version": state.version,
            "horizon_minutes": horizon_minutes,
            "start_at": start.isoformat(),
            "generated_at": utcnow().isoformat(),
            **(extra_basis or {}),
        },
    )

    # Planner v2 (D-031 §1/§4): build the free-slot list first, then score,
    # split and place — never stacking work on top of today's classes and
    # never exceeding the CurrentState available-minutes budget. Each item
    # carries its structured basis; the human reason is rendered from it in
    # client_view (the basis is the record, the reason is a view).
    plan.items.extend(_generate_v2_items(session, user_id=user_id, tasks=tasks, start=start))

    session.add(plan)
    session.flush()
    return plan


# --------------------------------------------------------------------------- #
# Planner v2 internals
# --------------------------------------------------------------------------- #

STRATEGY_V2 = "slots_v2"
_TRANSIT_BUFFER_MINUTES = 10
_MAX_BLOCK_MINUTES = 90
_DAY_START_HOUR = 8  # local clock; no honest plan starts before 08:00


@dataclass(frozen=True)
class _FreeSlot:
    start: datetime
    end: datetime
    is_longest: bool


def _day_bounds(now: datetime) -> tuple[datetime, datetime]:
    timezone = ZoneInfo(get_settings().default_timezone)
    local = now.astimezone(timezone)
    day_start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    return day_start.astimezone(UTC), day_end.astimezone(UTC)


def _free_slots(
    now: datetime,
    schedule: list[tuple[datetime, datetime, str, str | None]],
) -> list[_FreeSlot]:
    """Free intervals of the local day: [max(now, 08:00 local), day_end)
    minus schedule entries padded with a transit buffer (evaluation §3.1)."""

    day_start, day_end = _day_bounds(now)
    work_start = day_start.replace(hour=_DAY_START_HOUR).astimezone(UTC)
    window_start = max(now, work_start)

    busy: list[tuple[datetime, datetime]] = []
    buffer = timedelta(minutes=_TRANSIT_BUFFER_MINUTES)
    for entry_start, entry_end, _course, _location in schedule:
        clipped_start = max(entry_start - buffer, window_start)
        clipped_end = min(entry_end + buffer, day_end)
        if clipped_end > clipped_start:
            busy.append((clipped_start, clipped_end))
    busy.sort()

    merged: list[list[datetime]] = []
    for b_start, b_end in busy:
        if merged and b_start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b_end)
        else:
            merged.append([b_start, b_end])

    raw: list[tuple[datetime, datetime]] = []
    cursor = window_start
    for b_start, b_end in merged:
        if b_start > cursor:
            raw.append((cursor, b_start))
        cursor = max(cursor, b_end)
    if day_end > cursor:
        raw.append((cursor, day_end))

    free = [_FreeSlot(start, end, False) for start, end in raw if end > start]
    if free:
        longest = max(free, key=lambda slot: (slot.end - slot.start).total_seconds())
        free = [_FreeSlot(slot.start, slot.end, slot is longest) for slot in free]
    return free


def _available_budget(
    schedule: list[tuple[datetime, datetime, str, str | None]],
    current_task: Task | None,
    now: datetime,
) -> int:
    """Same口径 as the projection's available minutes (D-027): local-day
    remaining minus schedule overlap minus the current task's remaining
    estimate, floored at 0 — the badge and the plan cannot disagree."""

    _, day_end = _day_bounds(now)
    day_remaining = int((day_end - now).total_seconds() // 60)
    overlap = _overlap_minutes(schedule, now, day_end)
    return max(0, day_remaining - overlap - _task_remaining_minutes(current_task))


def _slack_minutes(task: Task, estimate_minutes: int, now: datetime) -> int | None:
    if task.deadline is None:
        return None
    remaining = estimate_minutes - (task.actual_duration_minutes or 0)
    return int((task.deadline - now).total_seconds() // 60) - remaining


def _score(task: Task, slack: int | None) -> dict[str, int]:
    """Deterministic urgency(slack) + goal + priority (evaluation §3.1)."""

    clamped = max(0, min(slack, 1440)) if slack is not None else 1440
    urgency = 1440 - clamped
    goal = 50 if task.goal_id is not None else 0
    priority = task.priority * 20
    return {
        "urgency": urgency,
        "goal": goal,
        "priority": priority,
        "total": urgency + goal + priority,
    }


def _split_blocks(remaining_minutes: int) -> list[int]:
    """Long tasks are worked in blocks of at most 90 minutes (§3.1)."""

    blocks: list[int] = []
    left = remaining_minutes
    while left > 0:
        blocks.append(min(left, _MAX_BLOCK_MINUTES))
        left -= blocks[-1]
    return blocks


def _current_task_id(session: Session, user_id: uuid.UUID) -> uuid.UUID | None:
    state = get_or_create_state(session, user_id)
    return state.current_task_id


def _generate_v2_items(
    session: Session,
    *,
    user_id: uuid.UUID,
    tasks: list[Task],
    start: datetime,
) -> list[PlanItem]:
    now = start
    schedule = _today_schedule_entries(session, user_id, now)
    slots = _free_slots(now, schedule)
    current_id = _current_task_id(session, user_id)
    current_task = session.get(Task, current_id) if current_id is not None else None
    budget = _available_budget(schedule, current_task, now)

    ranked: list[tuple[dict[str, int], int, Estimate, Task]] = []
    for task in tasks:
        estimate = estimate_for_task(session, user_id=user_id, task=task)
        slack = _slack_minutes(task, estimate.minutes, now)
        ranked.append((_score(task, slack), slack if slack is not None else 10**6, estimate, task))
    ranked.sort(key=lambda entry: (-entry[0]["total"], entry[1]))

    items: list[PlanItem] = []
    slot_index = 0
    slot_cursor = slots[0].start if slots else now
    placed_total = 0
    for score, slack_sort, estimate, task in ranked:
        remaining = estimate.minutes - (task.actual_duration_minutes or 0)
        if remaining <= 0:
            continue
        slack = slack_sort if slack_sort != 10**6 else None
        blocks = _split_blocks(remaining)
        for block_minutes in blocks:
            placed = False
            while slot_index < len(slots) and not placed:
                slot = slots[slot_index]
                slot_cursor = max(slot_cursor, slot.start)
                if slot_cursor >= slot.end:
                    slot_index += 1
                    continue
                if placed_total + block_minutes > budget:
                    return items  # the available-minutes budget is spent
                block_end = slot_cursor + timedelta(minutes=block_minutes)
                if block_end > slot.end:
                    fit = int((slot.end - slot_cursor).total_seconds() // 60)
                    if fit <= 0:
                        slot_index += 1
                        continue
                    block_minutes -= fit
                    block_end = slot.end
                else:
                    placed = True
                minutes = int((block_end - slot_cursor).total_seconds() // 60)
                items.append(
                    PlanItem(
                        task_id=task.id,
                        title=task.title,
                        order_index=len(items),
                        planned_start=slot_cursor,
                        planned_end=block_end,
                        planned_minutes=minutes,
                        basis={
                            "deadline": task.deadline.isoformat() if task.deadline else None,
                            "slack_minutes": slack,
                            "estimate_minutes": estimate.minutes,
                            "estimate_source": estimate.source,
                            "sample_count": estimate.sample_count or None,
                            "goal_id": str(task.goal_id) if task.goal_id else None,
                            "slot_reason": "今天最长空档" if slot.is_longest else "空闲时段",
                            "score": score,
                            "at_risk": bool(slack is not None and slack < 0),
                        },
                    )
                )
                placed_total += minutes
                slot_cursor = block_end
                if placed_total >= budget:
                    return items
            if not placed and slot_index >= len(slots):
                # No honest room left today for the remaining blocks: the
                # task is not silently forgotten — it stays pending and the
                # next generation (or a replan trigger) retries it.
                break
    return items


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
