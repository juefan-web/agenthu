from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.api.deps import CurrentUser, DBSession, PaginationDep
from backend.core.errors import NotFoundError
from backend.db.base import utcnow
from backend.models.enums import TaskStatus
from backend.models.event import Event
from backend.models.task import Task
from backend.schemas.common import Page
from backend.schemas.event import EventRead
from backend.schemas.task import FocusCompleteRequest, TaskCreate, TaskRead, TaskUpdate
from backend.services.focus import emit_focus_completed, emit_focus_started
from backend.services.lookup import get_event, get_goal, get_task

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _load_events(db: Session, user_id: uuid.UUID, event_ids: list[uuid.UUID]) -> list[Event]:
    if not event_ids:
        return []
    stmt = select(Event).where(Event.id.in_(event_ids), Event.user_id == user_id)
    events = list(db.scalars(stmt))
    if len(events) != len(set(event_ids)):
        raise NotFoundError("One or more related events were not found")
    return events


def _validate_goal(db: Session, user_id: uuid.UUID, goal_id: uuid.UUID | None) -> None:
    if goal_id is not None:
        get_goal(db, user_id=user_id, goal_id=goal_id)


@router.post("", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
def create(payload: TaskCreate, user: CurrentUser, db: DBSession) -> Task:
    _validate_goal(db, user.id, payload.goal_id)
    task = Task(
        user_id=user.id,
        title=payload.title,
        description=payload.description,
        source=payload.source,
        status=payload.status,
        deadline=payload.deadline,
        estimated_duration_minutes=payload.estimated_duration_minutes,
        priority=payload.priority,
        goal_id=payload.goal_id,
        extra=payload.extra,
    )
    task.related_events = _load_events(db, user.id, payload.related_event_ids)
    db.add(task)
    db.flush()
    return task


@router.get("", response_model=Page[TaskRead])
def list_all(
    user: CurrentUser,
    db: DBSession,
    pagination: PaginationDep,
    status_filter: Annotated[TaskStatus | None, Query(alias="status")] = None,
    goal_id: Annotated[uuid.UUID | None, Query()] = None,
    deadline_before: Annotated[datetime | None, Query()] = None,
) -> Page[TaskRead]:
    conditions = [Task.user_id == user.id]
    if status_filter is not None:
        conditions.append(Task.status == status_filter)
    if goal_id is not None:
        conditions.append(Task.goal_id == goal_id)
    if deadline_before is not None:
        conditions.append(Task.deadline <= deadline_before)
    total = db.scalar(select(func.count()).select_from(Task).where(*conditions)) or 0
    stmt = (
        select(Task)
        .where(*conditions)
        .order_by(Task.deadline.asc().nulls_last(), Task.created_at.desc())
        .limit(pagination.limit)
        .offset(pagination.offset)
    )
    tasks = list(db.scalars(stmt))
    return Page(
        items=[TaskRead.model_validate(task) for task in tasks],
        total=int(total),
        limit=pagination.limit,
        offset=pagination.offset,
    )


@router.get("/{task_id}", response_model=TaskRead)
def get_one(task_id: uuid.UUID, user: CurrentUser, db: DBSession) -> Task:
    return get_task(db, user_id=user.id, task_id=task_id)


@router.patch("/{task_id}", response_model=TaskRead)
def update(task_id: uuid.UUID, payload: TaskUpdate, user: CurrentUser, db: DBSession) -> Task:
    task = get_task(db, user_id=user.id, task_id=task_id)
    data = payload.model_dump(exclude_unset=True)
    if "goal_id" in data:
        _validate_goal(db, user.id, data["goal_id"])
    for field, value in data.items():
        setattr(task, field, value)
    if "status" in data:
        task.completed_at = utcnow() if data["status"] == TaskStatus.COMPLETED else None
    db.flush()
    return task


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(task_id: uuid.UUID, user: CurrentUser, db: DBSession) -> Response:
    task = get_task(db, user_id=user.id, task_id=task_id)
    db.delete(task)
    db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{task_id}/events/{event_id}", response_model=TaskRead)
def link_event(task_id: uuid.UUID, event_id: uuid.UUID, user: CurrentUser, db: DBSession) -> Task:
    task = get_task(db, user_id=user.id, task_id=task_id)
    event = get_event(db, user_id=user.id, event_id=event_id)
    if all(linked.id != event.id for linked in task.related_events):
        task.related_events.append(event)
        db.flush()
    return task


@router.delete("/{task_id}/events/{event_id}", response_model=TaskRead)
def unlink_event(task_id: uuid.UUID, event_id: uuid.UUID, user: CurrentUser, db: DBSession) -> Task:
    task = get_task(db, user_id=user.id, task_id=task_id)
    event = get_event(db, user_id=user.id, event_id=event_id)
    task.related_events = [linked for linked in task.related_events if linked.id != event.id]
    db.flush()
    return task


@router.post("/{task_id}/focus/start", response_model=EventRead)
def start_focus(task_id: uuid.UUID, user: CurrentUser, db: DBSession) -> Event:
    task = get_task(db, user_id=user.id, task_id=task_id)
    return emit_focus_started(db, user_id=user.id, task=task)


@router.post("/{task_id}/focus/complete", response_model=TaskRead)
def complete_focus(
    task_id: uuid.UUID,
    payload: FocusCompleteRequest,
    user: CurrentUser,
    db: DBSession,
) -> Task:
    task = get_task(db, user_id=user.id, task_id=task_id)
    emit_focus_completed(
        db,
        user_id=user.id,
        task=task,
        actual_minutes=payload.actual_minutes,
        completed=payload.completed,
        notes=payload.notes,
    )
    return task
