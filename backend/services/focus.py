"""Persisted focus sessions with an explicit lifecycle.

``running -> paused -> running -> completed`` (or ``abandoned``). Every
transition is driven by an Event with a stable dedupe key derived from the
session id, so network retries and duplicate "complete" taps are idempotent:
the task's actual duration is not accumulated twice.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.core.errors import ConflictError, ValidationError
from backend.db.base import utcnow
from backend.models.enums import FocusSessionStatus, TaskStatus
from backend.models.focus_session import FocusSession
from backend.models.task import Task
from backend.schemas.client_contract import FocusSessionUpdate
from backend.schemas.event import EventCreate
from backend.services.events import create_event

_ALLOWED_TRANSITIONS: dict[FocusSessionStatus, set[FocusSessionStatus]] = {
    FocusSessionStatus.RUNNING: {
        FocusSessionStatus.PAUSED,
        FocusSessionStatus.COMPLETED,
        FocusSessionStatus.ABANDONED,
    },
    FocusSessionStatus.PAUSED: {
        FocusSessionStatus.RUNNING,
        FocusSessionStatus.COMPLETED,
        FocusSessionStatus.ABANDONED,
    },
    FocusSessionStatus.COMPLETED: set(),
    FocusSessionStatus.ABANDONED: set(),
}

_TERMINAL = {FocusSessionStatus.COMPLETED, FocusSessionStatus.ABANDONED}
_ACTIVE = {FocusSessionStatus.RUNNING, FocusSessionStatus.PAUSED}


def _emit(
    session: Session,
    *,
    user_id: uuid.UUID,
    event_type: str,
    focus: FocusSession,
    task: Task,
    extra: dict[str, object] | None = None,
) -> None:
    payload = EventCreate(
        type=event_type,
        source="backend",
        data={"task_id": str(task.id), "session_id": str(focus.id), **(extra or {})},
        context={
            "task_title": task.title,
            "estimated_duration_minutes": task.estimated_duration_minutes,
        },
        provenance={"origin": "backend.focus", "focus_session_id": str(focus.id)},
        dedupe_key=f"focus-session:{focus.id}:{event_type.split('.')[-1]}",
    )
    create_event(session, user_id=user_id, payload=payload)


def active_session_for_task(
    session: Session, *, user_id: uuid.UUID, task_id: uuid.UUID
) -> FocusSession | None:
    stmt = (
        select(FocusSession)
        .where(
            FocusSession.user_id == user_id,
            FocusSession.task_id == task_id,
            FocusSession.status.in_(_ACTIVE),
        )
        .order_by(FocusSession.created_at.desc())
    )
    return session.scalar(stmt)


def _focus_lock_key(user_id: uuid.UUID, task_id: uuid.UUID) -> int:
    """Return a stable PostgreSQL advisory-lock key for one active task."""

    material = f"focus:{user_id}:{task_id}".encode()
    return int.from_bytes(hashlib.blake2b(material, digest_size=8).digest(), "big", signed=True)


def lock_focus_start(session: Session, *, user_id: uuid.UUID, task_id: uuid.UUID) -> None:
    """Serialize active-session lookup and creation for one user/task pair."""

    if session.get_bind().dialect.name != "postgresql":
        return
    session.execute(select(func.pg_advisory_xact_lock(_focus_lock_key(user_id, task_id))))


def create_focus_session(session: Session, *, user_id: uuid.UUID, task: Task) -> FocusSession:
    lock_focus_start(session, user_id=user_id, task_id=task.id)
    existing = active_session_for_task(session, user_id=user_id, task_id=task.id)
    if existing is not None:
        # Starting a task that already has an active session is idempotent.
        return existing

    focus = FocusSession(
        user_id=user_id,
        task_id=task.id,
        status=FocusSessionStatus.RUNNING,
        started_at=utcnow(),
    )
    session.add(focus)
    session.flush()
    _emit(session, user_id=user_id, event_type="focus.started", focus=focus, task=task)
    return focus


def update_focus_session(
    session: Session,
    *,
    user_id: uuid.UUID,
    focus: FocusSession,
    task: Task,
    payload: FocusSessionUpdate,
) -> FocusSession:
    if focus.status in _TERMINAL:
        # Completion/abandonment is idempotent: return the stored result.
        return focus

    if payload.deviation_note is not None:
        focus.deviation_note = payload.deviation_note

    if payload.status is None:
        session.flush()
        return focus

    try:
        target = FocusSessionStatus(payload.status)
    except ValueError as exc:
        raise ValidationError(
            f"Unknown focus status '{payload.status}'",
            details={"allowed": [status.value for status in FocusSessionStatus]},
        ) from exc

    if target not in _ALLOWED_TRANSITIONS[focus.status]:
        raise ConflictError(
            f"Cannot transition focus session from {focus.status.value} to {target.value}"
        )

    if target == FocusSessionStatus.COMPLETED:
        _complete(session, user_id=user_id, focus=focus, task=task, payload=payload)
    elif target == FocusSessionStatus.ABANDONED:
        focus.status = FocusSessionStatus.ABANDONED
        focus.ended_at = utcnow()
        _emit(session, user_id=user_id, event_type="focus.abandoned", focus=focus, task=task)
    else:
        focus.status = target

    session.flush()
    return focus


def _complete(
    session: Session,
    *,
    user_id: uuid.UUID,
    focus: FocusSession,
    task: Task,
    payload: FocusSessionUpdate,
) -> None:
    now = utcnow()
    focus.status = FocusSessionStatus.COMPLETED
    focus.ended_at = now
    focus.actual_minutes = (
        payload.actual_minutes
        if payload.actual_minutes is not None
        else _elapsed_minutes(focus.started_at, now)
    )
    # Always emit: a task worked on across several sessions must accumulate
    # every session's time. `completed` marks the session that finishes the
    # task; later sessions on an already-completed task contribute time only
    # (the handler never regresses status or rewrites completed_at). Duplicate
    # "complete" taps on the *same* session stay deduplicated by the terminal
    # early-return above plus the per-session event dedupe key.
    task_was_completed = task.status == TaskStatus.COMPLETED
    _emit(
        session,
        user_id=user_id,
        event_type="focus.completed",
        focus=focus,
        task=task,
        extra={
            "actual_minutes": focus.actual_minutes,
            "completed": not task_was_completed,
            "notes": focus.deviation_note,
        },
    )


def _elapsed_minutes(started_at: datetime, ended_at: datetime) -> int:
    seconds = max(0, int((ended_at - started_at).total_seconds()))
    return max(1, seconds // 60)
