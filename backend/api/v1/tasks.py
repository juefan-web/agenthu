from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from backend.api.deps import CurrentUser, DBSession, PaginationDep
from backend.core.errors import NotFoundError, ValidationError
from backend.db.base import utcnow
from backend.models.enums import TaskStatus
from backend.models.event import Event
from backend.models.task import Task
from backend.schemas.client_contract import ClientTask
from backend.schemas.task import TaskCreate, TaskRead, TaskUpdate
from backend.services.client_view import task_to_client
from backend.services.lookup import get_event, get_goal, get_task
from backend.services.pagination import decode_cursor, keyset_page
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


@router.get(
    "",
    response_model=list[ClientTask],
    responses={
        200: {
            "headers": {
                "X-Next-Cursor": {
                    "description": (
                        "Opaque keyset cursor (D-029) for the next page; "
                        "absent when this is the last page. Present only on "
                        "the keyset path (no offset parameter)."
                    ),
                    "schema": {"type": "string"},
                }
            }
        }
    },
)
def list_all(
    user: CurrentUser,
    db: DBSession,
    response: Response,
    pagination: PaginationDep,
    # Presence detector for the D-029 "cursor + offset -> 422" rule: the
    # shared PaginationDep cannot distinguish an absent offset from 0.
    offset_param: Annotated[int | None, Query(alias="offset", ge=0)] = None,
    cursor: Annotated[str | None, Query()] = None,
    status_filter: Annotated[TaskStatus | None, Query(alias="status")] = None,
    goal_id: Annotated[uuid.UUID | None, Query()] = None,
    deadline_before: Annotated[datetime | None, Query()] = None,
) -> list[ClientTask]:
    if cursor is not None and offset_param is not None:
        raise ValidationError("cursor and offset are mutually exclusive (D-029)")

    conditions = [Task.user_id == user.id]
    if status_filter is not None:
        conditions.append(Task.status == status_filter)
    if goal_id is not None:
        conditions.append(Task.goal_id == goal_id)
    if deadline_before is not None:
        conditions.append(Task.deadline <= deadline_before)

    # Keyset order (D-029: the cursor key IS the sort key): deadline first
    # (the client-visible ordering, nulls last), then created_at/id as the
    # tiebreak. Tasks with identical (deadline, created_at) — e.g. one sync
    # batch — are ordered by id, deterministically.
    order_by = (Task.deadline.asc().nulls_last(), Task.created_at.desc(), Task.id.desc())
    use_keyset = cursor is not None or offset_param is None
    if use_keyset:
        stmt: Any = select(Task).where(*conditions).order_by(*order_by)
        if cursor is not None:
            stmt = stmt.where(_after_task_cursor(cursor))
        page, next_cursor = keyset_page(
            db,
            stmt,
            limit=pagination.limit,
            after=True,
            key_of=lambda t: (
                t.deadline.isoformat() if t.deadline is not None else None,
                t.created_at.isoformat(),
                str(t.id),
            ),
        )
        if next_cursor is not None:
            response.headers["X-Next-Cursor"] = next_cursor
        return [_client(task) for task in page]

    # Deprecated offset path (D-029): kept for compatibility, no cursor.
    stmt = select(Task).where(*conditions).order_by(*order_by)
    return [_client(task) for task in db.scalars(stmt.limit(pagination.limit).offset(offset_param))]


def _after_task_cursor(cursor: str) -> Any:
    """Rows strictly AFTER the cursor row in the keyset order.

    deadline ASC with NULLS LAST: rows with a null deadline sort after
    every non-null one, so the predicate branches on whether the cursor row
    itself had a deadline; within one deadline, "later" means the
    (created_at, id) pair decreases (both DESC).
    """

    deadline_raw, created_raw, id_raw = decode_cursor(cursor, 3)
    try:
        cursor_deadline = datetime.fromisoformat(deadline_raw) if deadline_raw is not None else None
        if created_raw is None or id_raw is None:
            raise ValueError("created_at/id must be present")
        cursor_created = datetime.fromisoformat(created_raw)
        cursor_id = uuid.UUID(id_raw)
    except ValueError as exc:
        raise ValidationError("Invalid pagination cursor") from exc
    tiebreak = or_(
        Task.created_at < cursor_created,
        and_(Task.created_at == cursor_created, Task.id < cursor_id),
    )
    if cursor_deadline is not None:
        return or_(
            Task.deadline.is_(None),
            Task.deadline > cursor_deadline,
            and_(Task.deadline == cursor_deadline, tiebreak),
        )
    return and_(Task.deadline.is_(None), tiebreak)


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
