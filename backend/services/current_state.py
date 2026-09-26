"""CurrentState projection.

CurrentState answers "what is the user's present?" It is recomputed from Tasks,
Plans and recent Events; it is not a copy of the Event stream. The projection is
persisted with a monotonically increasing ``version`` so clients can sync.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.db.base import utcnow
from backend.models.current_state import CurrentState
from backend.models.enums import PlanStatus, TaskStatus
from backend.models.event import Event
from backend.models.plan import Plan
from backend.models.task import Task
from backend.schemas.current_state import CurrentStateRead, CurrentStateUpdate
from backend.schemas.plan import PlanRead
from backend.schemas.task import TaskRead
from backend.services.lookup import ensure_owned_tasks

_PENDING_STATUSES = (TaskStatus.TODO, TaskStatus.IN_PROGRESS)
_RECENT_WINDOW = timedelta(hours=24)
_RECENT_EVENT_SCAN = 20


def get_or_create_state(session: Session, user_id: uuid.UUID) -> CurrentState:
    state = session.scalar(select(CurrentState).where(CurrentState.user_id == user_id))
    if state is None:
        state = CurrentState(user_id=user_id, version=0, current_time=utcnow())
        session.add(state)
        session.flush()
    return state


def pending_tasks(
    session: Session, user_id: uuid.UUID, goal_id: uuid.UUID | None = None
) -> list[Task]:
    conditions = [Task.user_id == user_id, Task.status.in_(_PENDING_STATUSES)]
    if goal_id is not None:
        conditions.append(Task.goal_id == goal_id)
    stmt = (
        select(Task)
        .where(*conditions)
        .order_by(
            Task.deadline.asc().nulls_last(),
            Task.priority.desc(),
            Task.created_at.asc(),
        )
    )
    return list(session.scalars(stmt))


def current_plan_for(session: Session, user_id: uuid.UUID) -> Plan | None:
    """Return the plan the user has actually confirmed.

    Unconfirmed proposals are intentionally excluded: they are not yet the
    user's current plan, even though they are visible via the Plans API.
    """

    stmt = (
        select(Plan)
        .where(Plan.user_id == user_id, Plan.status == PlanStatus.CONFIRMED)
        .order_by(Plan.confirmed_at.desc().nulls_last(), Plan.created_at.desc())
        .limit(1)
    )
    return session.scalar(stmt)


def recompute_current_state(session: Session, user_id: uuid.UUID) -> CurrentStateRead:
    now = utcnow()
    state = get_or_create_state(session, user_id)
    tasks = pending_tasks(session, user_id)

    current_task: Task | None = None
    if state.current_task_id is not None:
        current_task = next((t for t in tasks if t.id == state.current_task_id), None)
    if current_task is None:
        current_task = next((t for t in tasks if t.status == TaskStatus.IN_PROGRESS), None)

    plan = current_plan_for(session, user_id)
    recent = _recent_events_summary(session, user_id)

    state.version = (state.version or 0) + 1
    state.current_time = now
    state.current_task_id = current_task.id if current_task else None
    state.current_plan_id = plan.id if plan else None
    state.pending_task_ids = [str(task.id) for task in tasks]
    state.recent_state = recent
    session.flush()

    return _to_read(state, current_task, tasks, plan)


def update_overrides(
    session: Session, user_id: uuid.UUID, payload: CurrentStateUpdate
) -> CurrentStateRead:
    state = get_or_create_state(session, user_id)
    if payload.current_context is not None:
        state.current_context = payload.current_context
    if payload.available_minutes is not None:
        state.available_minutes = payload.available_minutes
    if payload.current_task_id is not None:
        ensure_owned_tasks(session, user_id=user_id, task_ids=[payload.current_task_id])
        state.current_task_id = payload.current_task_id
    session.flush()
    return recompute_current_state(session, user_id)


def _recent_events_summary(session: Session, user_id: uuid.UUID) -> dict[str, object]:
    latest = session.scalar(
        select(Event).where(Event.user_id == user_id).order_by(Event.timestamp.desc()).limit(1)
    )
    window_start = utcnow() - _RECENT_WINDOW
    count_24h = session.scalar(
        select(func.count())
        .select_from(Event)
        .where(Event.user_id == user_id, Event.timestamp >= window_start)
    )
    recent_types = list(
        session.scalars(
            select(Event.type)
            .where(Event.user_id == user_id)
            .order_by(Event.timestamp.desc())
            .limit(_RECENT_EVENT_SCAN)
        )
    )
    return {
        "last_event_at": latest.timestamp.isoformat() if latest else None,
        "last_event_type": latest.type if latest else None,
        "recent_event_count_24h": int(count_24h or 0),
        "recent_event_types": recent_types,
    }


def _to_read(
    state: CurrentState,
    current_task: Task | None,
    tasks: list[Task],
    plan: Plan | None,
) -> CurrentStateRead:
    return CurrentStateRead(
        user_id=state.user_id,
        version=state.version,
        current_time=state.current_time,
        current_context=state.current_context,
        current_task=TaskRead.model_validate(current_task) if current_task else None,
        pending_tasks=[TaskRead.model_validate(task) for task in tasks],
        current_plan=PlanRead.model_validate(plan) if plan else None,
        recent_state=state.recent_state,
        available_minutes=state.available_minutes,
        updated_at=state.updated_at,
    )
