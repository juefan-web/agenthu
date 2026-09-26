"""Event ingestion with per-user idempotency."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.models.event import Event
from backend.models.task import Task
from backend.schemas.event import EventCreate
from backend.services.event_handlers import process_event


def create_event(
    session: Session,
    *,
    user_id: uuid.UUID,
    payload: EventCreate,
) -> tuple[Event, bool]:
    """Persist an Event, processing it through registered handlers.

    Returns ``(event, created)``. When ``dedupe_key`` matches an existing Event
    for the same user, the existing row is returned and ``created`` is False.
    Deduplication is enforced by a unique constraint, so concurrent replays are
    safe.
    """

    if payload.dedupe_key:
        existing = find_by_dedupe_key(session, user_id=user_id, dedupe_key=payload.dedupe_key)
        if existing is not None:
            return existing, False

    event = Event(
        user_id=user_id,
        type=payload.type,
        timestamp=payload.timestamp,
        source=payload.source,
        data=payload.data,
        context=payload.context,
        provenance=payload.provenance,
        dedupe_key=payload.dedupe_key,
    )
    try:
        with session.begin_nested():
            session.add(event)
            session.flush()
    except IntegrityError:
        if payload.dedupe_key:
            existing = find_by_dedupe_key(session, user_id=user_id, dedupe_key=payload.dedupe_key)
            if existing is not None:
                return existing, False
        raise

    process_event(session, event)
    session.flush()
    return event, True


def find_by_dedupe_key(session: Session, *, user_id: uuid.UUID, dedupe_key: str) -> Event | None:
    stmt = select(Event).where(Event.user_id == user_id, Event.dedupe_key == dedupe_key)
    return session.scalar(stmt)


def get_event(session: Session, *, user_id: uuid.UUID, event_id: uuid.UUID) -> Event | None:
    stmt = select(Event).where(Event.id == event_id, Event.user_id == user_id)
    return session.scalar(stmt)


def list_events(
    session: Session,
    *,
    user_id: uuid.UUID,
    event_type: str | None = None,
    source: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
    descending: bool = True,
) -> tuple[list[Event], int]:
    conditions = [Event.user_id == user_id]
    if event_type:
        conditions.append(Event.type == event_type)
    if source:
        conditions.append(Event.source == source)
    if since:
        conditions.append(Event.timestamp >= since)
    if until:
        conditions.append(Event.timestamp <= until)

    total = session.scalar(select(func.count()).select_from(Event).where(*conditions)) or 0
    order = Event.timestamp.desc() if descending else Event.timestamp.asc()
    stmt = select(Event).where(*conditions).order_by(order).limit(limit).offset(offset)
    return list(session.scalars(stmt)), int(total)


def list_events_for_task(session: Session, task: Task) -> list[Event]:
    return list(task.related_events)
