"""Event ingestion with per-user idempotency."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.core.sensitive import validate_json_payload
from backend.models.event import Event
from backend.models.task import Task
from backend.schemas.client_contract import EventEnvelope
from backend.schemas.event import EventCreate
from backend.services.current_state import defer_state_recompute, flush_state_recompute
from backend.services.event_handlers import process_event
from backend.worker.enqueue import mark_user_dirty

_ASSIGNMENT_PREFIX = "study.assignment."
# Deadline-bearing fields of assignment payloads that must be timezone-aware
# ISO strings (D-028): naive values are rejected at the ingestion boundary so
# they stay in the client queue instead of becoming permanently
# un-derivable rows.
_ASSIGNMENT_DEADLINE_FIELDS = ("deadline", "late_deadline")


def _parse_iso(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def assignment_payload_rejection(event_type: str, data: dict[str, Any]) -> str | None:
    """Reject assignment events whose deadline fields carry no UTC offset.

    A naive deadline has no correct interpretation on the server (the vendor
    string is Beijing local time; assuming UTC is an 8-hour skew), so the
    envelope is refused at the boundary — the client keeps it queued until it
    sends tz-aware values (D-028 §3a).
    """

    if not event_type.startswith(_ASSIGNMENT_PREFIX):
        return None
    for name in _ASSIGNMENT_DEADLINE_FIELDS:
        if name not in data or data[name] is None:
            continue
        parsed = _parse_iso(data[name])
        if parsed is None:
            return f"{name} is not a valid ISO-8601 datetime"
        if parsed.tzinfo is None:
            return (
                f"{name} must be timezone-aware ISO-8601 (include the UTC "
                "offset, e.g. +08:00); naive values are rejected (D-028)"
            )
    return None


def _escape_dedupe_part(part: str) -> str:
    """Escape the separators exactly as the client's ``eventDedupeKey`` does.

    Ordered ``\\`` before ``:`` so the backslashes it introduces are not
    escaped twice.
    """

    return part.replace("\\", "\\\\").replace(":", "\\:")


def compute_dedupe_key(source: str, provenance: dict[str, Any] | None) -> str | None:
    """Derive the canonical idempotency key: ``source:upstream_id:semantic_version``.

    This mirrors the client contract's ``eventDedupeKey`` byte-for-byte,
    including its ``\\``/``:`` escaping, so a value containing the separator
    cannot collide with a different ``(source, upstream_id, semantic_version)``
    triple (the adapter emits e.g. ``upstream_id="assignment:hw-1"``). It is
    computed on the Backend so a client cannot weaken idempotency by omitting a
    key.
    """

    if not isinstance(provenance, dict):
        return None
    upstream_id = provenance.get("upstream_id")
    semantic_version = provenance.get("semantic_version")
    if upstream_id and semantic_version:
        return ":".join(
            _escape_dedupe_part(str(part)) for part in (source, upstream_id, semantic_version)
        )
    return None


def create_event(
    session: Session,
    *,
    user_id: uuid.UUID,
    payload: EventCreate,
    client_event_id: str | None = None,
) -> tuple[Event, bool]:
    """Persist an Event, processing it through registered handlers.

    Returns ``(event, created)``. When ``dedupe_key`` matches an existing Event
    for the same user, the existing row is returned and ``created`` is False.
    Deduplication is enforced by a unique constraint, so concurrent replays are
    safe.
    """

    dedupe_key = payload.dedupe_key or compute_dedupe_key(payload.source, payload.provenance)
    if dedupe_key:
        existing = find_by_dedupe_key(session, user_id=user_id, dedupe_key=dedupe_key)
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
        dedupe_key=dedupe_key,
        client_event_id=client_event_id,
    )
    try:
        with session.begin_nested():
            session.add(event)
            session.flush()
    except IntegrityError:
        if dedupe_key:
            existing = find_by_dedupe_key(session, user_id=user_id, dedupe_key=dedupe_key)
            if existing is not None:
                return existing, False
        raise

    process_event(session, event)
    session.flush()
    # Single-event path: handlers only marked the user dirty, so the
    # projection must be refreshed here before the request ends. Batch
    # ingestion defers this (defer_state_recompute) and flushes once after
    # its loop (evaluation §4).
    flush_state_recompute(session)
    # New facts may satisfy a replan trigger (focus overrun, schedule change,
    # near-deadline task). Best-effort dirty marker; the worker cron drains it
    # (D-031 §2) — Redis being down must never fail ingestion.
    mark_user_dirty(user_id)
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


@dataclass
class EventBatchOutcome:
    """Result of ingesting a batch of client event envelopes.

    ``accepted`` / ``duplicates`` contain the *client* ``client_event_id`` values
    so the client can clear its local queue (see the desktop sync coordinator).
    """

    accepted: list[str] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)


def ingest_event_batch(
    session: Session,
    *,
    user_id: uuid.UUID,
    envelopes: list[EventEnvelope],
) -> EventBatchOutcome:
    outcome = EventBatchOutcome()
    # Handlers mark the user dirty instead of recomputing inline; the
    # projection is refreshed ONCE below for the whole batch (evaluation §4).
    with defer_state_recompute(session):
        for envelope in envelopes:
            reason = (
                validate_json_payload("data", envelope.data)
                or validate_json_payload("context", envelope.context)
                or validate_json_payload("provenance", envelope.provenance.model_dump())
                or assignment_payload_rejection(envelope.type, envelope.data)
            )
            if reason is not None:
                outcome.rejected.append((envelope.client_event_id, reason))
                continue

            payload = EventCreate(
                type=envelope.type,
                timestamp=envelope.occurred_at,
                source=envelope.source,
                data=envelope.data,
                context=envelope.context,
                provenance=envelope.provenance.model_dump(mode="json"),
            )
            # Envelope-level validation already ran; create and classify.
            _event, created = create_event(
                session,
                user_id=user_id,
                payload=payload,
                client_event_id=envelope.client_event_id,
            )
            if created:
                outcome.accepted.append(envelope.client_event_id)
            else:
                outcome.duplicates.append(envelope.client_event_id)
    flush_state_recompute(session)
    return outcome
