from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.deps import CurrentUser, DBSession, PaginationDep
from backend.core.errors import NotFoundError
from backend.db.base import utcnow
from backend.models.enums import TaskStatus
from backend.models.event import Event
from backend.models.task import Task
from backend.schemas.client_contract import ClientTask
from backend.schemas.task import TaskCreate, TaskRead, TaskUpdate
from backend.services.client_view import task_to_client
from backend.services.lookup import get_event, get_goal, get_task
from backend.worker.enqueue import mark_user_dirty

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _client(task: Task) -> ClientTask:
    return task_to_client(TaskRead.model_validate(task))


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


@router.post("", response_model=ClientTask, status_code=status.HTTP_201_CREATED)
def create(payload: TaskCreate, user: CurrentUser, db: DBSession) -> ClientTask:
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
    # Manual tasks with near deadlines satisfy the same trigger as derived
    # ones (derived tasks get marked by the event path).
    mark_user_dirty(user.id)
    return _client(task)


@router.get("", response_model=list[ClientTask])
def list_all(
    user: CurrentUser,
    db: DBSession,
    pagination: PaginationDep,
    status_filter: Annotated[TaskStatus | None, Query(alias="status")] = None,
    goal_id: Annotated[uuid.UUID | None, Query()] = None,
    deadline_before: Annotated[datetime | None, Query()] = None,
) -> list[ClientTask]:
    conditions = [Task.user_id == user.id]
    if status_filter is not None:
        conditions.append(Task.status == status_filter)
    if goal_id is not None:
        conditions.append(Task.goal_id == goal_id)
    if deadline_before is not None:
        conditions.append(Task.deadline <= deadline_before)
    stmt = (
        select(Task)
        .where(*conditions)
        .order_by(Task.deadline.asc().nulls_last(), Task.created_at.desc())
        .limit(pagination.limit)
        .offset(pagination.offset)
    )
    return [_client(task) for task in db.scalars(stmt)]


@router.get("/{task_id}", response_model=ClientTask)
def get_one(task_id: uuid.UUID, user: CurrentUser, db: DBSession) -> ClientTask:
    return _client(get_task(db, user_id=user.id, task_id=task_id))


@router.patch("/{task_id}", response_model=ClientTask)
def update(task_id: uuid.UUID, payload: TaskUpdate, user: CurrentUser, db: DBSession) -> ClientTask:
    task = get_task(db, user_id=user.id, task_id=task_id)
    data = payload.model_dump(exclude_unset=True)
    if "goal_id" in data:
        _validate_goal(db, user.id, data["goal_id"])
    for field, value in data.items():
        setattr(task, field, value)
    if "status" in data:
        task.completed_at = utcnow() if data["status"] == TaskStatus.COMPLETED else None
    db.flush()
    return _client(task)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(task_id: uuid.UUID, user: CurrentUser, db: DBSession) -> Response:
    task = get_task(db, user_id=user.id, task_id=task_id)
    db.delete(task)
    db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{task_id}/events/{event_id}", response_model=ClientTask)
def link_event(
    task_id: uuid.UUID, event_id: uuid.UUID, user: CurrentUser, db: DBSession
) -> ClientTask:
    task = get_task(db, user_id=user.id, task_id=task_id)
    event = get_event(db, user_id=user.id, event_id=event_id)
    if all(linked.id != event.id for linked in task.related_events):
        task.related_events.append(event)
        db.flush()
    return _client(task)


@router.delete("/{task_id}/events/{event_id}", response_model=ClientTask)
def unlink_event(
    task_id: uuid.UUID, event_id: uuid.UUID, user: CurrentUser, db: DBSession
) -> ClientTask:
    task = get_task(db, user_id=user.id, task_id=task_id)
    event = get_event(db, user_id=user.id, event_id=event_id)
    task.related_events = [linked for linked in task.related_events if linked.id != event.id]
    db.flush()
    return _client(task)
