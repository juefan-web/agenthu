"""Replan-suggestion trigger engine (D-031 §2, evaluation §3.3).

Level 1 semantics: evaluation only reads facts and may create a DRAFT
suggestion — it never mutates the confirmed plan (the L4 protection) and
never calls ``replan()`` (that would supersede before acceptance). The
engine is idempotent per (target, trigger signature): re-running an
evaluation that already produced its suggestion returns it instead of
stacking another; a *different* trigger on the same target cancels the stale
suggestion first. Rate limiting (≤1 per 30 minutes unless a deadline is at
risk) is enforced here too, so every caller — worker cron or test — gets the
same policy for free.

The rest-state trigger from evaluation §3.3 is deferred until a rest state
exists as a first-class CurrentState input (outline M2 CurrentState 补全).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.db.base import utcnow
from backend.models.enums import FocusSessionStatus, PlanItemStatus, PlanStatus, TaskStatus
from backend.models.event import Event
from backend.models.focus_session import FocusSession
from backend.models.plan import Plan
from backend.models.task import Task
from backend.services.current_state import current_plan_for, pending_tasks
from backend.services.planner import generate_plan

TRIGGER_GENERATED_BY = "replan_trigger"
OVERRUN_RATIO = 1.3
EARLY_RATIO = 0.5
NEW_TASK_WINDOW = timedelta(hours=48)
RATE_LIMIT = timedelta(minutes=30)


def evaluate_replan_triggers(
    session: Session, *, user_id: uuid.UUID, now: datetime | None = None
) -> Plan | None:
    """Create (or return) the pending suggestion for the user's confirmed
    plan when a trigger fires. Returns None when nothing applies."""

    now = now or utcnow()
    plan = current_plan_for(session, user_id)
    if plan is None:
        return None  # suggestions always replace a confirmed plan (D-031 §2)

    # Facts that already produced a suggestion for this target (any status):
    # a consumed trigger must not keep shadowing fresher ones.
    consumed: set[str] = set()
    prior = session.scalars(
        select(Plan).where(
            Plan.user_id == user_id,
            Plan.replaces_plan_id == plan.id,
            Plan.generated_by == TRIGGER_GENERATED_BY,
        )
    )
    for suggestion in prior:
        signature = suggestion.basis.get("trigger_signature")
        if isinstance(signature, str):
            consumed.add(signature)

    trigger = _detect_trigger(session, user_id=user_id, plan=plan, now=now, consumed=consumed)
    if trigger is None:
        return None

    stale = list(
        session.scalars(
            select(Plan).where(
                Plan.user_id == user_id,
                Plan.replaces_plan_id == plan.id,
                Plan.status == PlanStatus.DRAFT,
                Plan.generated_by == TRIGGER_GENERATED_BY,
            )
        )
    )
    for suggestion in stale:
        if suggestion.basis.get("trigger_signature") == trigger["signature"]:
            return suggestion  # this fact already has its suggestion
    # Rate limit: a fresh suggestion at most every 30 minutes, unless a
    # deadline is at risk (D-031 §2). Column-level select: the server default
    # is not echoed onto un-refreshed ORM instances.
    if not _deadline_at_risk(session, user_id, now):
        latest_created = session.scalar(
            select(Plan.created_at)
            .where(
                Plan.user_id == user_id,
                Plan.generated_by == TRIGGER_GENERATED_BY,
            )
            .order_by(Plan.created_at.desc())
            .limit(1)
        )
        if latest_created is not None and now - latest_created < RATE_LIMIT:
            return None
    # A new trigger retires the previous suggestion for this target (#22
    # review note 3: suggestions never stack).
    for suggestion in stale:
        suggestion.status = PlanStatus.CANCELLED
        suggestion.cancelled_at = now
    session.flush()

    return generate_plan(
        session,
        user_id=user_id,
        status=PlanStatus.DRAFT,
        replaces_plan_id=plan.id,
        replan_reason=trigger["reason"],
        generated_by=TRIGGER_GENERATED_BY,
        extra_basis={
            "trigger": trigger["kind"],
            "trigger_signature": trigger["signature"],
        },
    )


def _detect_trigger(
    session: Session,
    *,
    user_id: uuid.UUID,
    plan: Plan,
    now: datetime,
    consumed: set[str],
) -> dict | None:
    timezone = ZoneInfo(get_settings().default_timezone)
    planned_task_ids = {item.task_id for item in plan.items}

    # 1. Focus overrun / early finish on a confirmed item (the E4 trigger:
    # the reason must cite the actual minutes).
    match: dict | None = None
    for item in plan.items:
        if item.status == PlanItemStatus.COMPLETED and item.actual_minutes and item.planned_minutes:
            ratio = item.actual_minutes / item.planned_minutes
            if ratio >= OVERRUN_RATIO:
                match = {
                    "kind": "focus_overrun",
                    "signature": f"overrun:{item.id}:{item.actual_minutes}",
                    "reason": (
                        f"「{item.title}」Focus 实际 {item.actual_minutes} 分钟，"
                        f"达计划 {item.planned_minutes} 分钟的 {ratio:.0%}，"
                        "今日后续安排需要重排"
                    ),
                }
            elif ratio <= EARLY_RATIO:
                match = {
                    "kind": "focus_early",
                    "signature": f"early:{item.id}:{item.actual_minutes}",
                    "reason": (
                        f"「{item.title}」提前完成（实际 {item.actual_minutes} 分钟，"
                        f"计划 {item.planned_minutes} 分钟），空出的时段可以安排其他任务"
                    ),
                }
            if match is not None and match["signature"] not in consumed:
                return match
            match = None

    # 2. A task with a deadline inside 48h arrived after the plan was
    # confirmed and is not in it (round-5 L4's explicit path).
    for task in pending_tasks(session, user_id):
        if task.id in planned_task_ids or task.deadline is None:
            continue
        if plan.confirmed_at is not None and task.created_at is not None:
            signature = f"new_task:{task.id}"
            if (
                task.created_at > plan.confirmed_at
                and task.deadline - now <= NEW_TASK_WINDOW
                and signature not in consumed
            ):
                return {
                    "kind": "new_task",
                    "signature": signature,
                    "reason": (
                        f"新任务「{task.title}」{_human_deadline(task.deadline, now)}截止，"
                        "未包含在当前计划中"
                    ),
                }

    # 3. A confirmed item's slot has passed without the work starting.
    running_task_ids = set(
        session.scalars(
            select(FocusSession.task_id).where(
                FocusSession.user_id == user_id,
                FocusSession.status.in_((FocusSessionStatus.RUNNING, FocusSessionStatus.PAUSED)),
            )
        )
    )
    task_status = {
        task.id: task.status
        for task in session.scalars(select(Task).where(Task.user_id == user_id))
    }
    for item in plan.items:
        if (
            item.status == PlanItemStatus.PENDING
            and item.planned_end is not None
            and item.planned_end < now
            and item.task_id is not None
            and item.task_id not in running_task_ids
            and task_status.get(item.task_id) in (TaskStatus.TODO, TaskStatus.IN_PROGRESS)
        ):
            signature = f"slot_passed:{item.id}:{item.planned_end.isoformat()}"
            if signature in consumed:
                continue
            window = (
                f"{item.planned_start.astimezone(timezone):%H:%M}"
                f"–{item.planned_end.astimezone(timezone):%H:%M}"
                if item.planned_start is not None
                else "原定时段"
            )
            return {
                "kind": "slot_passed",
                "signature": signature,
                "reason": f"「{item.title}」的时段 {window} 已过还未开始，需要重排今日剩余安排",
            }

    # 4. Today's schedule changed after confirmation.
    if plan.confirmed_at is not None:
        changed = session.scalars(
            select(Event.id)
            .where(
                Event.user_id == user_id,
                Event.type == "time.schedule.entry",
                Event.timestamp > plan.confirmed_at,
            )
            .order_by(Event.timestamp.desc())
        )
        for event_id in changed:
            signature = f"schedule_change:{event_id}"
            if signature not in consumed:
                return {
                    "kind": "schedule_change",
                    "signature": signature,
                    "reason": "今日课表在计划确认后有变更，需要核对今日安排",
                }
    return None


def _deadline_at_risk(session: Session, user_id: uuid.UUID, now: datetime) -> bool:
    for task in pending_tasks(session, user_id):
        if task.deadline is not None and task.deadline <= now:
            return True
    return False


def _human_deadline(deadline: datetime, now: datetime) -> str:
    timezone = ZoneInfo(get_settings().default_timezone)
    local = deadline.astimezone(timezone)
    today = now.astimezone(timezone).date()
    if local.date() == today:
        prefix = "今天"
    elif local.date() == today + timedelta(days=1):
        prefix = "明天"
    else:
        prefix = f"{local.month}月{local.day}日"
    return f"{prefix} {local:%H:%M}"
