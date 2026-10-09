"""Persisted focus sessions with an explicit lifecycle.

``running -> paused -> running -> completed`` (or ``abandoned``). Every
transition is driven by an Event with a dedupe key derived from the session
id and a transition ordinal (``focus-session:{id}:{verb}:{n}``): network
retries and duplicate "complete" taps stay idempotent, while repeated
pause/resume rounds each keep their own event. Pause segments are closed
into ``accumulated_pause_seconds``; the default ``actual_minutes`` is the
wall clock minus every closed pause segment (floor 1 minute), so an
overnight pause does not pollute the task's actual duration. An explicit
client ``actual_minutes`` still overrides (user-correction face).
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.core.errors import ConflictError, ValidationError
from backend.db.base import utcnow
from backend.models.enums import DataBarrierScope, FocusSessionStatus, TaskStatus
from backend.models.event import Event
from backend.models.focus_session import FocusSession
from backend.models.task import Task
from backend.schemas.client_contract import FocusSessionUpdate
from backend.schemas.event import EventCreate
from backend.services.events import create_event
from backend.services.write_guards import assert_write_allowed

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


def _transition_ordinal(
    session: Session, *, user_id: uuid.UUID, focus: FocusSession, event_type: str
) -> int:
    """Count this session's prior events of the type (transition ordinal).

    Multi-round transitions of the same verb (a second ``focus.paused``) each
    get their own dedupe key; a concurrent same-key race lands on the dedupe
    unique constraint, which is the correct face for a duplicate transition.
    """

    stmt = (
        select(func.count())
        .select_from(Event)
        .where(
            Event.user_id == user_id,
            Event.type == event_type,
            Event.data["session_id"].as_string() == str(focus.id),
        )
    )
    return session.scalar(stmt) or 0


def _emit(
    session: Session,
    *,
    user_id: uuid.UUID,
    event_type: str,
    focus: FocusSession,
    task: Task,
    extra: dict[str, object] | None = None,
) -> None:
    verb = event_type.split(".")[-1]
    payload = EventCreate(
        type=event_type,
        source="backend",
        data={"task_id": str(task.id), "session_id": str(focus.id), **(extra or {})},
        context={
            "task_title": task.title,
            "estimated_duration_minutes": task.estimated_duration_minutes,
        },
        provenance={"origin": "backend.focus", "focus_session_id": str(focus.id)},
        dedupe_key=(
            f"focus-session:{focus.id}:{verb}:"
            f"{_transition_ordinal(session, user_id=user_id, focus=focus, event_type=event_type)}"
        ),
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
    # Entry guard (A-draft §2.3 names Focus explicitly). Task ids are not in
    # any current barrier's target space (source barriers carry event/file/
    # chat ids), so today this only ever trips on the account barrier — the
    # discipline keeps the check honest if barrier id spaces ever widen.
    assert_write_allowed(
        session, user_id=user_id, scope=DataBarrierScope.SOURCE, target_ids={str(task.id)}
    )
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

    assert_write_allowed(
        session, user_id=user_id, scope=DataBarrierScope.SOURCE, target_ids={str(task.id)}
    )

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
        # Same closure treatment as completion (no actual_minutes, but the
        # pause-ledger state stays consistent): an open pause segment is
        # closed first (live-mine-2 §0).
        now = utcnow()
        _close_open_pause(focus, now)
        focus.status = FocusSessionStatus.ABANDONED
        focus.ended_at = now
        _emit(session, user_id=user_id, event_type="focus.abandoned", focus=focus, task=task)
    elif target == FocusSessionStatus.PAUSED:
        focus.status = FocusSessionStatus.PAUSED
        focus.paused_at = utcnow()
        # Snapshot at pause time: closed-segment total only — this segment is
        # open and carries no duration yet (§0).
        _emit(
            session,
            user_id=user_id,
            event_type="focus.paused",
            focus=focus,
            task=task,
            extra={"accumulated_pause_seconds": focus.accumulated_pause_seconds},
        )
    else:
        # RUNNING, reachable only from PAUSED (transition table).
        segment = _close_open_pause(focus, utcnow())
        focus.status = FocusSessionStatus.RUNNING
        _emit(
            session,
            user_id=user_id,
            event_type="focus.resumed",
            focus=focus,
            task=task,
            extra={
                "pause_seconds": segment,
                "accumulated_pause_seconds": focus.accumulated_pause_seconds,
            },
        )

    session.flush()
    return focus


def _close_open_pause(focus: FocusSession, now: datetime) -> int:
    """Close the open pause segment into the accumulated total.

    Returns the just-closed segment's seconds (0 when no segment is open —
    including legacy PAUSED rows from before the pause columns existed:
    nothing was ever recorded open, so nothing is closable). Direct
    PAUSED→COMPLETED/ABANDONED paths close the segment first (§0).
    """

    if focus.paused_at is None:
        return 0
    segment = max(0, int((now - focus.paused_at).total_seconds()))
    focus.accumulated_pause_seconds += segment
    focus.paused_at = None
    return segment


def _complete(
    session: Session,
    *,
    user_id: uuid.UUID,
    focus: FocusSession,
    task: Task,
    payload: FocusSessionUpdate,
) -> None:
    now = utcnow()
    _close_open_pause(focus, now)
    focus.status = FocusSessionStatus.COMPLETED
    focus.ended_at = now
    focus.actual_minutes = (
        payload.actual_minutes
        if payload.actual_minutes is not None
        else _net_minutes(focus.started_at, now, focus.accumulated_pause_seconds)
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
            # Closed-pause total at completion time, including a segment the
            # direct PAUSED→COMPLETED path just closed; same transaction and
            # source as the column value (§0 snapshot family).
            "accumulated_pause_seconds": focus.accumulated_pause_seconds,
            "completed": not task_was_completed,
            "notes": focus.deviation_note,
        },
    )


def _net_minutes(started_at: datetime, ended_at: datetime, pause_seconds: int) -> int:
    """Wall clock minus closed pause seconds, floored at 1 minute (§0)."""

    seconds = max(0, int((ended_at - started_at).total_seconds()) - max(0, pause_seconds))
    return max(1, seconds // 60)
