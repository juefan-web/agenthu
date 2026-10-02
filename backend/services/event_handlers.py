"""Event -> domain projection registry.

External sources are normalized to Events. Registered handlers turn those facts
into domain changes (Task status, CurrentState, and later Memory). This keeps
projection logic in one place instead of scattering it across adapters.

Handlers run inside the ingestion transaction *before* commit. A failing
handler must not lose the raw Event, so each handler runs inside its own
SAVEPOINT: on failure only the savepoint rolls back, the Event insert and the
rest of the transaction survive, and the failure is logged and audited.
"""

from __future__ import annotations

import fnmatch
import logging
import statistics
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.enums import (
    MemoryCorrectionStatus,
    MemoryKind,
    PlanItemStatus,
    PlanStatus,
    TaskStatus,
)
from backend.models.event import Event
from backend.models.memory import Memory
from backend.models.plan import Plan, PlanItem
from backend.models.task import Task
from backend.services.audit import safe_record_audit
from backend.services.estimates import (
    RATIO_SUBJECT_KEY,
    course_actuals,
    course_subject_key,
    plan_item_ratios,
    round_half_up,
    trimmed_mean,
)
from backend.services.memory_lifecycle import upsert_keyed_memory

logger = logging.getLogger(__name__)

EventHandler = Callable[[Session, Event], None]

_HANDLERS: dict[str, list[EventHandler]] = {}


def register(pattern: str) -> Callable[[EventHandler], EventHandler]:
    """Register a handler for an exact event type or an fnmatch pattern."""

    def decorator(func: EventHandler) -> EventHandler:
        _HANDLERS.setdefault(pattern, []).append(func)
        return func

    return decorator


def handlers_for(event_type: str) -> list[EventHandler]:
    matched: list[EventHandler] = []
    for pattern, handlers in _HANDLERS.items():
        if pattern == event_type or fnmatch.fnmatch(event_type, pattern):
            matched.extend(handlers)
    return matched


def process_event(session: Session, event: Event) -> None:
    for handler in handlers_for(event.type):
        try:
            # A savepoint (not a bare try/except): a DB-level handler failure
            # poisons the transaction, and only rolling back to the savepoint
            # leaves the outer transaction usable for the audit write below.
            with session.begin_nested():
                handler(session, event)
        except Exception:  # pragma: no cover - defensive, audited below
            logger.exception(
                "Event handler failed",
                extra={"event_id": str(event.id), "event_type": event.type},
            )
            safe_record_audit(
                session,
                action="event.handler_failed",
                actor="system",
                user_id=event.user_id,
                resource_type="event",
                resource_id=str(event.id),
                decision="deny",
                details={"event_type": event.type, "handler": handler.__name__},
            )
    session.flush()


def _get_task(session: Session, user_id: uuid.UUID, raw_task_id: Any) -> Task | None:
    if not raw_task_id:
        return None
    try:
        task_id = uuid.UUID(str(raw_task_id))
    except (ValueError, AttributeError):
        return None
    stmt = select(Task).where(Task.id == task_id, Task.user_id == user_id)
    return session.scalar(stmt)


@register("focus.started")
def handle_focus_started(session: Session, event: Event) -> None:
    task = _get_task(session, event.user_id, event.data.get("task_id"))
    if task is not None and task.status == TaskStatus.TODO:
        task.status = TaskStatus.IN_PROGRESS
    _mark_state_dirty(session, event.user_id)


@register("focus.completed")
def handle_focus_completed(session: Session, event: Event) -> None:
    task = _get_task(session, event.user_id, event.data.get("task_id"))
    if task is not None:
        minutes = event.data.get("actual_minutes")
        actual: int | None = None
        if isinstance(minutes, int | float) and minutes >= 0:
            actual = int(minutes)
            # Accumulate: a task worked on across several focus sessions
            # contributes every session's actual time (each session emits its
            # own focus.completed with a per-session dedupe key).
            task.actual_duration_minutes = (task.actual_duration_minutes or 0) + actual
        # COMPLETED is sticky: it is set only by the session that finishes the
        # task (completed=True). Later sessions on an already-completed task
        # add time without regressing status or overwriting completed_at.
        if task.status != TaskStatus.COMPLETED:
            if event.data.get("completed", True):
                task.status = TaskStatus.COMPLETED
                task.completed_at = event.timestamp
            else:
                task.status = TaskStatus.IN_PROGRESS
        _mark_confirmed_plan_items(session, task.id, actual)
    _mark_state_dirty(session, event.user_id)


@register("focus.completed")
def handle_focus_learning(session: Session, event: Event) -> None:
    """The learn step (D-031 §4, migration plan §4) as its OWN handler.

    process_event runs every handler in its own SAVEPOINT: keeping the
    memory writes here means a learning-write failure (schema drift, bad
    payload) rolls back only the memory rows — the task completion from
    ``handle_focus_completed`` survives, exactly the failure shape the E4
    first run exposed. Still synchronous on purpose — the next plan must
    already see this completion (the E4 spec generates right after
    seeding).
    """

    task = _get_task(session, event.user_id, event.data.get("task_id"))
    if task is not None and task.status == TaskStatus.COMPLETED:
        _write_learning_memory(session, event, task)


_EPISODE_EVIDENCE_LIMIT = 20


def _write_learning_memory(session: Session, event: Event, task: Task) -> None:
    course = task.extra.get("course_name") if isinstance(task.extra, dict) else None
    course_name = course if isinstance(course, str) and course else None
    planned = _planned_minutes_for(session, task)
    actual = task.actual_duration_minutes
    note = event.data.get("notes")
    note_text = note.strip() if isinstance(note, str) and note.strip() else None

    parts = [f"完成「{task.title}」"]
    if planned is not None:
        parts.append(f"计划 {planned} 分钟；实际 {actual} 分钟")
    else:
        parts.append(f"实际 {actual} 分钟（未在计划中）")
    if course_name:
        parts.append(f"课程：{course_name}")
    if note_text:
        parts.append(f"偏差说明：{note_text}")
    content = "；".join(parts) + f"。时段 {event.timestamp:%H:%M}"

    derived_ids = [str(event_id) for event_id in task.related_event_ids]
    episode = Memory(
        user_id=event.user_id,
        level=1,
        domain="study",
        content=content,
        source={
            "task_id": str(task.id),
            "course_name": course_name,
            "planned_minutes": planned,
            "actual_minutes": actual,
            "deviation_note": note_text,
        },
        source_event_ids=[str(event.id), *derived_ids],
        confidence=1.0,
        correction_status=MemoryCorrectionStatus.CONFIRMED,
        kind=MemoryKind.EPISODE,
        evidence=[
            {"type": "event", "id": str(event.id)},
            *[{"type": "event", "id": event_id} for event_id in derived_ids],
        ],
    )
    session.add(episode)
    session.flush()  # episode.id feeds the L2 evidence lineage

    recent_episodes = _recent_episode_ids(session, user_id=event.user_id, course_name=course_name)
    if course_name:
        actuals = course_actuals(session, user_id=event.user_id, course=course_name)
        if actuals:
            median = round_half_up(statistics.median(actuals))
            upsert_keyed_memory(
                session,
                user_id=event.user_id,
                subject_key=course_subject_key(course_name),
                level=2,
                kind=MemoryKind.FACT,
                domain="study",
                content=(
                    f"「{course_name}」作业实际用时中位数约 {median} 分钟"
                    f"（近 {len(actuals)} 次完成）"
                ),
                source={
                    "metric": "median_actual_minutes",
                    "value": median,
                    "sample_count": len(actuals),
                    "unit": "minutes",
                    "course_name": course_name,
                },
                confidence=min(0.9, len(actuals) / 10),
                evidence=[{"type": "memory", "id": episode_id} for episode_id in recent_episodes],
            )

    ratios = plan_item_ratios(session, user_id=event.user_id)
    if ratios:
        value = trimmed_mean(ratios)
        upsert_keyed_memory(
            session,
            user_id=event.user_id,
            subject_key=RATIO_SUBJECT_KEY,
            level=2,
            kind=MemoryKind.FACT,
            domain="study",
            content=f"个人估时校准比约 {value:.2f} 倍（实际 ÷ 计划；近 {len(ratios)} 次计划执行）",
            source={
                "metric": "trimmed_mean_ratio",
                "value": round(value, 3),
                "sample_count": len(ratios),
                "planned_source": "plan_item",
            },
            confidence=min(0.9, len(ratios) / 10),
            evidence=[{"type": "memory", "id": episode_id} for episode_id in recent_episodes],
        )


def _planned_minutes_for(session: Session, task: Task) -> int | None:
    """The planned minutes the task was last executed under (any live-ish
    plan), for the episode record; None when it was never planned."""

    stmt = (
        select(PlanItem.planned_minutes)
        .where(PlanItem.task_id == task.id)
        .order_by(PlanItem.created_at.desc())
        .limit(1)
    )
    return session.scalar(stmt)


def _recent_episode_ids(
    session: Session, *, user_id: uuid.UUID, course_name: str | None
) -> list[str]:
    """L1 episode ids as L2 evidence lineage (per course, or across courses
    for the user-level ratio row)."""

    conditions = [
        Memory.user_id == user_id,
        Memory.kind == MemoryKind.EPISODE,
        Memory.supersedes_id.is_(None),
    ]
    if course_name is not None:
        conditions.append(Memory.source["course_name"].as_string() == course_name)
    rows = session.execute(
        select(Memory.id)
        .where(*conditions)
        .order_by(Memory.created_at.desc())
        .limit(_EPISODE_EVIDENCE_LIMIT)
    ).all()
    return [str(row_id) for (row_id,) in rows]


def _mark_confirmed_plan_items(
    session: Session, task_id: object, actual_minutes: int | None
) -> None:
    stmt = (
        select(PlanItem)
        .join(Plan, PlanItem.plan_id == Plan.id)
        .where(PlanItem.task_id == task_id, Plan.status == PlanStatus.CONFIRMED)
    )
    for item in session.scalars(stmt):
        item.status = PlanItemStatus.COMPLETED
        if actual_minutes is not None:
            # Accumulated, mirroring Task.actual_duration_minutes so the plan
            # item and the task never disagree about time spent.
            item.actual_minutes = (item.actual_minutes or 0) + actual_minutes


@register("task.*")
def handle_task_event(session: Session, event: Event) -> None:
    # Any task lifecycle event can change the projection.
    _mark_state_dirty(session, event.user_id)


# --------------------------------------------------------------------------- #
# Assignment derivation (D-028)
# --------------------------------------------------------------------------- #

_ASSIGNMENT_PREFIX = "study.assignment."
# Upstream marks deadline-less assignments with a year-2099 placeholder; real
# coursework never spans more than a semester, so anything further out than
# this is a sentinel and is not derived (D-028 round-5 appendix, L5).
_SENTINEL_HORIZON = timedelta(days=365 * 2)


def _parse_tzaware(value: object) -> object:
    """Pass through tz-aware ISO strings; anything else becomes None.

    The ingestion boundary already rejects naive assignment deadlines
    (D-028 §3a), so unparseable values here mean the field was absent or
    null — leaving the task's deadline unset rather than guessing.
    """

    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _derived_assignment_title(data: dict[str, Any], upstream: str) -> str:
    """``{course_name}：{title}`` when the course is known, else the raw title.

    Vendor assignment titles are bare homework names ("Homework 2"); without
    the course prefix, same-named assignments across courses are
    indistinguishable in the task list (round-5 L3). The client adapter
    forwards ``course_name`` when available; older payloads keep the plain
    title.
    """

    title = data.get("title") if isinstance(data.get("title"), str) else ""
    course = data.get("course_name") if isinstance(data.get("course_name"), str) else ""
    if not title:
        title = course or upstream
    elif course:
        title = f"{course}：{title}"
    return title[:300]


@register("study.assignment.discovered")
@register("study.assignment.updated")
def handle_assignment_event(session: Session, event: Event) -> None:
    """Derive/refresh a Task from an assignment event (D-028).

    Upsert key is ``(user_id, source, source_upstream_id)``; the event's
    dedupe key embeds semantic_version, so a re-collected assignment with
    changed content lands as a *new* event that updates the existing task
    instead of creating a duplicate. COMPLETED is sticky (C2 semantics).
    Sentinel assignments (deadline beyond the 2-year horizon, e.g. the
    upstream year-2099 placeholder) are ingested as events but not derived
    (round-5 L5).
    """

    upstream = event.provenance.get("upstream_id") if isinstance(event.provenance, dict) else None
    if not isinstance(upstream, str) or not upstream:
        return

    data = event.data if isinstance(event.data, dict) else {}
    deadline = _parse_tzaware(data.get("deadline"))
    if isinstance(deadline, datetime) and deadline - event.timestamp > _SENTINEL_HORIZON:
        # Sentinel: keep the event (facts layer), skip the derived task.
        return

    task = session.scalar(
        select(Task).where(
            Task.user_id == event.user_id,
            Task.source == event.source,
            Task.source_upstream_id == upstream,
        )
    )
    if task is None:
        task = Task(
            user_id=event.user_id,
            source=event.source,
            source_upstream_id=upstream,
            status=TaskStatus.TODO,
        )
        session.add(task)

    task.title = _derived_assignment_title(data, upstream)
    if isinstance(data.get("content"), str) and data["content"]:
        task.description = data["content"]
    if deadline is not None:
        task.deadline = deadline  # type: ignore[assignment]
    task.extra = {
        "assignment_id": data.get("assignment_id"),
        "course_id": data.get("course_id"),
        "course_name": data.get("course_name"),
        "url": data.get("url"),
        "deadline_raw": data.get("deadline_raw"),
        "late_deadline": data.get("late_deadline"),
        "late_deadline_raw": data.get("late_deadline_raw"),
        "publish_time": data.get("publish_time"),
        "last_derived_event_id": str(event.id),
    }

    submitted = bool(data.get("submitted")) or bool(data.get("graded"))
    if submitted and task.status != TaskStatus.COMPLETED:
        task.status = TaskStatus.COMPLETED
        task.completed_at = event.timestamp
    session.flush()
    _mark_state_dirty(session, event.user_id)


def _mark_state_dirty(session: Session, user_id: uuid.UUID) -> None:
    """Defer the projection recompute to the ingestion exit point.

    Handlers used to call ``recompute_current_state`` inline, so a 103-event
    sync rescanned the projection 103 times and bumped its version 103 times
    (evaluation §4). Handlers now only mark the user dirty;
    ``create_event`` flushes once for the single-event path and
    ``ingest_event_batch`` once per batch. Imported lazily to avoid an
    import cycle (current_state imports schemas).
    """

    from backend.services.current_state import mark_state_dirty

    mark_state_dirty(session, user_id)
