"""CurrentState projection.

CurrentState answers "what is the user's present?" It is recomputed from Tasks,
Plans and recent Events; it is not a copy of the Event stream. The projection is
persisted with a monotonically increasing ``version`` so clients can sync.

``version`` is the revision of the projection CONTENT, not a recompute counter
(evaluation §4): it moves when the projection signature changes — current task,
current plan, pending set, or the event-derived identity fields of
``recent_state`` — or on the very first computation (``version=0`` means "never
computed"). Display fields whose only drift is the wall clock (``current_time``,
the 24h event count, the available-minutes breakdown) refresh on every recompute
without moving the version, so one batch of events costs one recompute and at
most one version bump instead of one per event.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.db.base import utcnow
from backend.models.current_state import CurrentState
from backend.models.enums import FocusSessionStatus, PlanStatus, TaskStatus
from backend.models.event import Event
from backend.models.focus_session import FocusSession
from backend.models.plan import Plan
from backend.models.task import Task
from backend.schemas.current_state import CurrentStateRead, CurrentStateUpdate
from backend.schemas.plan import PlanRead
from backend.schemas.task import TaskRead
from backend.services.lookup import ensure_owned_tasks
from backend.services.plan_validity import client_invalid_item_exists

_PENDING_STATUSES = (TaskStatus.TODO, TaskStatus.IN_PROGRESS)
_RECENT_WINDOW = timedelta(hours=24)
_RECENT_EVENT_SCAN = 20
# How far back schedule-entry events are still considered for "today": the
# same course row re-collected with a new semantic_version lands as a new
# Event, so the window only bounds how many revisions we rescan.
_SCHEDULE_LOOKBACK = timedelta(days=90)
# A class starting within this window switches the derived context label.
_CONTEXT_UPCOMING_WINDOW = timedelta(minutes=30)
_ACTIVE_FOCUS = (FocusSessionStatus.RUNNING, FocusSessionStatus.PAUSED)


def get_or_create_state(session: Session, user_id: uuid.UUID) -> CurrentState:
    state = session.scalar(select(CurrentState).where(CurrentState.user_id == user_id))
    if state is not None:
        return state

    # Two concurrent first requests can both observe "no state"; without an
    # idempotent insert the loser hits `uq_current_states_user` and the API
    # returns a 500 (merge-1 report D5). On PostgreSQL the INSERT ... ON
    # CONFLICT DO NOTHING makes the race a no-op for the losing request;
    # other dialects fall back to a savepoint + IntegrityError retry.
    if session.get_bind().dialect.name == "postgresql":
        session.execute(
            pg_insert(CurrentState)
            .values(user_id=user_id, version=0, current_time=utcnow())
            .on_conflict_do_nothing(constraint="uq_current_states_user")
        )
    else:
        try:
            with session.begin_nested():
                session.add(CurrentState(user_id=user_id, version=0, current_time=utcnow()))
                session.flush()
        except IntegrityError:
            pass
    state = session.scalar(select(CurrentState).where(CurrentState.user_id == user_id))
    if state is None:  # pragma: no cover - defensive: the row must exist here
        raise RuntimeError("CurrentState row missing after idempotent insert")
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

    Client-invalid plans are excluded too: the current plan is served through
    the frozen client contract, whose ``PlanItemSchema`` requires non-null
    ``task_id``/``start_at``/``end_at`` — serving an invalid plan here would
    break the client's Zod parse instead of degrading gracefully (D-023).
    """

    stmt = (
        select(Plan)
        .where(
            Plan.user_id == user_id,
            Plan.status == PlanStatus.CONFIRMED,
            ~client_invalid_item_exists(),
        )
        .order_by(Plan.confirmed_at.desc().nulls_last(), Plan.created_at.desc())
        .limit(1)
    )
    return session.scalar(stmt)


# Batch-end recompute registry (evaluation §4): event handlers no longer
# recompute inline — they mark the user dirty on the session and the
# ingestion entry point flushes once per user. A 103-event sync costs one
# projection rescan instead of 103. Marks live on ``session.info``: they are
# transaction-scoped by construction (a rolled-back request discards them
# with the session) and need no schema.
_DIRTY_KEY = "agenthu_state_dirty_users"
_DEFER_KEY = "agenthu_state_recompute_deferred"


def mark_state_dirty(session: Session, user_id: uuid.UUID) -> None:
    session.info.setdefault(_DIRTY_KEY, set()).add(user_id)


@contextmanager
def defer_state_recompute(session: Session) -> Iterator[None]:
    """Suppress flushing inside ``create_event`` while a batch is running."""

    session.info[_DEFER_KEY] = True
    try:
        yield
    finally:
        session.info[_DEFER_KEY] = False


def flush_state_recompute(session: Session) -> None:
    """Recompute once per user marked since the last flush; no-op if deferred.

    Called at every event-ingestion exit point (``create_event`` for the
    single-event path, ``ingest_event_batch`` after its loop). Marks whose
    request later rolls back vanish with the session — recomputing from the
    final committed state would have been wasted anyway.
    """

    if session.info.get(_DEFER_KEY):
        return
    dirty: set[uuid.UUID] | None = session.info.pop(_DIRTY_KEY, None)
    if not dirty:
        return
    for user_id in sorted(dirty, key=str):
        recompute_current_state(session, user_id)


def recompute_current_state(session: Session, user_id: uuid.UUID) -> CurrentStateRead:
    now = utcnow()
    state = get_or_create_state(session, user_id)
    previous = _projection_signature(state)
    tasks = pending_tasks(session, user_id)

    current_task: Task | None = None
    if state.current_task_id is not None:
        current_task = next((t for t in tasks if t.id == state.current_task_id), None)
    if current_task is None:
        current_task = next((t for t in tasks if t.status == TaskStatus.IN_PROGRESS), None)

    plan = current_plan_for(session, user_id)
    recent = _recent_events_summary(session, user_id)
    schedule = _today_schedule_entries(session, user_id, now)
    available_minutes, breakdown = _available_minutes(now, schedule, current_task, state)
    context_label = _derive_context_label(
        state, schedule, session, user_id, now, current_task, has_pending_tasks=bool(tasks)
    )
    recent["available_minutes_breakdown"] = breakdown

    state.current_time = now
    state.current_task_id = current_task.id if current_task else None
    state.current_plan_id = plan.id if plan else None
    state.pending_task_ids = [str(task.id) for task in tasks]
    state.recent_state = recent
    if state.version == 0 or previous != _projection_signature(state):
        state.version = (state.version or 0) + 1
    session.flush()

    return _to_read(state, current_task, tasks, plan, available_minutes, context_label)


def _projection_signature(state: CurrentState) -> tuple[object, ...]:
    """The change-detector behind ``version``: identity fields only.

    Wall-clock-derived values (``current_time``, ``recent_event_count_24h``,
    ``available_minutes_breakdown``) are deliberately excluded — they drift
    between any two recomputes minutes apart without the state meaningfully
    changing, and counting them would re-create the per-recompute version
    churn the evaluation flagged. ``recent_event_types`` is sorted so a
    display-order tie between same-timestamp events cannot flip the
    signature.
    """

    recent = state.recent_state if isinstance(state.recent_state, dict) else {}
    return (
        state.current_task_id,
        state.current_plan_id,
        tuple(state.pending_task_ids or []),
        recent.get("last_event_at"),
        recent.get("last_event_type"),
        tuple(sorted(recent.get("recent_event_types") or [])),
    )


def update_overrides(
    session: Session, user_id: uuid.UUID, payload: CurrentStateUpdate
) -> CurrentStateRead:
    state = get_or_create_state(session, user_id)
    applied = False
    if payload.current_context is not None:
        state.current_context = payload.current_context
        applied = True
    if payload.available_minutes is not None:
        state.available_minutes = payload.available_minutes
        applied = True
    if payload.current_task_id is not None:
        ensure_owned_tasks(session, user_id=user_id, task_ids=[payload.current_task_id])
        state.current_task_id = payload.current_task_id
        applied = True
    if applied:
        # User intent changed stored fields that recompute does not derive
        # (context/available-minutes overrides) — move the version so other
        # clients resync even when the derived projection is unchanged. A
        # current_task_id override that changes the structure bumps again in
        # recompute; versions are monotonic, skipped numbers are fine.
        state.version = (state.version or 0) + 1
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
        # Normalized to UTC at write time: the same event reads back with a
        # different isoformat offset depending on whether the ORM object came
        # from the wire (original offset) or from a UTC database session —
        # an unnormalized string made the version gate see a change where
        # only the representation had flipped.
        "last_event_at": latest.timestamp.astimezone(UTC).isoformat() if latest else None,
        "last_event_type": latest.type if latest else None,
        "recent_event_count_24h": int(count_24h or 0),
        "recent_event_types": recent_types,
    }


def _to_read(
    state: CurrentState,
    current_task: Task | None,
    tasks: list[Task],
    plan: Plan | None,
    available_minutes: int | None,
    context_label: str | None,
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
        # Override (persisted in the column) wins over the derived value; the
        # projection output semantics are frozen in DECISIONS.md D-027.
        available_minutes=state.available_minutes
        if state.available_minutes is not None
        else available_minutes,
        context_label=context_label,
        updated_at=state.updated_at,
    )


# --------------------------------------------------------------------------- #
# Schedule-derived inputs (D-027)
# --------------------------------------------------------------------------- #


def _parse_hhmm(value: object) -> time | None:
    if not isinstance(value, str):
        return None
    parts = value.strip().split(":")
    if len(parts) not in (2, 3):
        return None
    try:
        hour, minute = int(parts[0]), int(parts[1])
        second = int(parts[2]) if len(parts) == 3 else 0
    except ValueError:
        return None
    if not (0 <= hour < 24 and 0 <= minute < 60 and 0 <= second < 60):
        return None
    return time(hour, minute, second)


def _entry_bounds(
    data: dict[str, Any], timezone: ZoneInfo, today: date
) -> tuple[datetime, datetime] | None:
    """Combine a schedule entry's naive local date/time strings into UTC bounds."""

    raw_date = data.get("date")
    try:
        entry_date = date.fromisoformat(str(raw_date)) if raw_date else today
    except ValueError:
        return None
    start_clock = _parse_hhmm(data.get("start_time"))
    end_clock = _parse_hhmm(data.get("end_time"))
    if start_clock is None or end_clock is None or end_clock <= start_clock:
        return None
    start = datetime.combine(entry_date, start_clock, tzinfo=timezone).astimezone(UTC)
    end = datetime.combine(entry_date, end_clock, tzinfo=timezone).astimezone(UTC)
    return start, end


def _today_schedule_entries(
    session: Session, user_id: uuid.UUID, now: datetime
) -> list[tuple[datetime, datetime, str, str | None]]:
    """Today's schedule intervals from `time.schedule.entry` events.

    The dedupe key embeds semantic_version, so a re-collected course row lands
    as a *new* Event; grouping by ``provenance.upstream_id`` and keeping the
    latest revision means changed or moved classes replace their old rows
    instead of double-counting. Entries that fail to parse are skipped: the
    projection must stay usable with imperfect vendor payloads.
    """

    timezone = ZoneInfo(get_settings().default_timezone)
    today = now.astimezone(timezone).date()
    window_start = now - _SCHEDULE_LOOKBACK
    rows = session.execute(
        select(Event.provenance, Event.data, Event.timestamp)
        .where(
            Event.user_id == user_id,
            Event.type == "time.schedule.entry",
            Event.timestamp >= window_start,
        )
        .order_by(Event.timestamp.desc())
    ).all()

    latest_by_upstream: dict[str, tuple[datetime, datetime, str, str | None]] = {}
    for provenance, data, _ts in rows:
        upstream = provenance.get("upstream_id") if isinstance(provenance, dict) else None
        if not isinstance(upstream, str) or upstream in latest_by_upstream:
            continue
        if not isinstance(data, dict):
            continue
        bounds = _entry_bounds(data, timezone, today)
        if bounds is None:
            continue
        course = str(data.get("course_name") or "课程")
        location = data.get("location")
        latest_by_upstream[upstream] = (*bounds, course, str(location) if location else None)

    return [
        entry
        for entry in latest_by_upstream.values()
        if entry[0].astimezone(timezone).date() == today
    ]


def _overlap_minutes(
    schedule: list[tuple[datetime, datetime, str, str | None]], now: datetime, day_end: datetime
) -> int:
    total = 0
    for start, end, _course, _location in schedule:
        overlap_start, overlap_end = max(start, now), min(end, day_end)
        if overlap_end > overlap_start:
            total += int((overlap_end - overlap_start).total_seconds() // 60)
    return total


def _task_remaining_minutes(task: Task | None) -> int:
    if task is None:
        return 0
    estimated = task.estimated_duration_minutes or 0
    actual = task.actual_duration_minutes or 0
    return max(0, estimated - actual)


def _available_minutes(
    now: datetime,
    schedule: list[tuple[datetime, datetime, str, str | None]],
    current_task: Task | None,
    state: CurrentState,
) -> tuple[int | None, dict[str, object]]:
    """Derived available minutes plus the breakdown recorded for auditability."""

    timezone = ZoneInfo(get_settings().default_timezone)
    today = now.astimezone(timezone).date()
    day_end = datetime.combine(today + timedelta(days=1), time(0, 0), tzinfo=timezone).astimezone(
        UTC
    )
    day_remaining = max(0, int((day_end - now).total_seconds() // 60))
    class_minutes = _overlap_minutes(schedule, now, day_end)
    task_remaining = _task_remaining_minutes(current_task)
    if state.available_minutes is not None:
        return None, {"source": "override", "override_minutes": state.available_minutes}
    derived = max(0, day_remaining - class_minutes - task_remaining)
    return derived, {
        "source": "derived",
        "day_remaining_minutes": day_remaining,
        "class_minutes": class_minutes,
        "current_task_remaining_minutes": task_remaining,
        "rest_reserve_minutes": 0,
    }


def _derive_context_label(
    state: CurrentState,
    schedule: list[tuple[datetime, datetime, str, str | None]],
    session: Session,
    user_id: uuid.UUID,
    now: datetime,
    current_task: Task | None,
    has_pending_tasks: bool,
) -> str | None:
    """Priority chain frozen in D-027: override > class > focus > task > upcoming > idle."""

    override = state.current_context.get("label") if state.current_context else None
    if isinstance(override, str) and override:
        return override

    for start, end, course, location in schedule:
        if start <= now < end:
            where = f"@{location}" if location else ""
            return f"在课：{course}{where}"

    focus_row = session.execute(
        select(FocusSession.id, FocusSession.task_id)
        .where(FocusSession.user_id == user_id, FocusSession.status.in_(_ACTIVE_FOCUS))
        .order_by(FocusSession.created_at.desc())
        .limit(1)
    ).first()
    if focus_row is not None:
        title = session.scalar(select(Task.title).where(Task.id == focus_row.task_id))
        return f"专注中：{title or '任务'}"

    if current_task is not None and current_task.status == TaskStatus.IN_PROGRESS:
        return f"进行中：{current_task.title}"

    upcoming = sorted((start, course) for start, _end, course, _location in schedule if start > now)
    if upcoming:
        next_start, course = upcoming[0]
        if next_start - now <= _CONTEXT_UPCOMING_WINDOW:
            return f"即将上课：{course}（{int((next_start - now).total_seconds() // 60)} 分钟后）"

    if has_pending_tasks:
        return "空闲"
    return None
