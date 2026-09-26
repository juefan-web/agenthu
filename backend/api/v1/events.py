from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import select

from backend.api.deps import CurrentUser, DBSession, PaginationDep
from backend.core.errors import NotFoundError
from backend.models.event import Event
from backend.schemas.common import Page
from backend.schemas.event import EventCreate, EventRead
from backend.services.events import create_event, list_events

router = APIRouter(prefix="/events", tags=["events"])


@router.post("", response_model=EventRead)
def create(
    payload: EventCreate,
    response: Response,
    user: CurrentUser,
    db: DBSession,
) -> Event:
    event, created = create_event(db, user_id=user.id, payload=payload)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    response.headers["X-Deduplicated"] = "false" if created else "true"
    return event


@router.get("", response_model=Page[EventRead])
def list_all(
    user: CurrentUser,
    db: DBSession,
    pagination: PaginationDep,
    event_type: Annotated[str | None, Query(alias="type")] = None,
    source: Annotated[str | None, Query()] = None,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
) -> Page[EventRead]:
    events, total = list_events(
        db,
        user_id=user.id,
        event_type=event_type,
        source=source,
        since=since,
        until=until,
        limit=pagination.limit,
        offset=pagination.offset,
    )
    return Page(
        items=[EventRead.model_validate(event) for event in events],
        total=total,
        limit=pagination.limit,
        offset=pagination.offset,
    )


@router.get("/{event_id}", response_model=EventRead)
def get_one(event_id: uuid.UUID, user: CurrentUser, db: DBSession) -> Event:
    event = db.scalar(select(Event).where(Event.id == event_id, Event.user_id == user.id))
    if event is None:
        raise NotFoundError("Event not found")
    return event


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(event_id: uuid.UUID, user: CurrentUser, db: DBSession) -> Response:
    event = db.scalar(select(Event).where(Event.id == event_id, Event.user_id == user.id))
    if event is None:
        raise NotFoundError("Event not found")
    db.delete(event)
    db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
