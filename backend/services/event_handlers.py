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
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.enums import PlanItemStatus, PlanStatus, TaskStatus
from backend.models.event import Event
from backend.models.plan import Plan, PlanItem
from backend.models.task import Task
from backend.services.audit import safe_record_audit

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
    _recompute(session, event.user_id)


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
    _recompute(session, event.user_id)


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
    _recompute(session, event.user_id)


# --------------------------------------------------------------------------- #
# Assignment derivation (D-028)
# --------------------------------------------------------------------------- #

_ASSIGNMENT_PREFIX = "study.assignment."


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


@register("study.assignment.discovered")
@register("study.assignment.updated")
def handle_assignment_event(session: Session, event: Event) -> None:
    """Derive/refresh a Task from an assignment event (D-028).

    Upsert key is ``(user_id, source, source_upstream_id)``; the event's
    dedupe key embeds semantic_version, so a re-collected assignment with
    changed content lands as a *new* event that updates the existing task
    instead of creating a duplicate. COMPLETED is sticky (C2 semantics).
    """

    upstream = event.provenance.get("upstream_id") if isinstance(event.provenance, dict) else None
    if not isinstance(upstream, str) or not upstream:
        return

    data = event.data if isinstance(event.data, dict) else {}
    task = session.scalar(
        select(Task).where(
            Task.user_id == event.user_id,
            Task.source == event.source,
            Task.source_upstream_id == upstream,
        )
    )
    created = task is None
    if task is None:
        task = Task(
            user_id=event.user_id,
            source=event.source,
            source_upstream_id=upstream,
            status=TaskStatus.TODO,
        )
        session.add(task)

    if isinstance(data.get("title"), str) and data["title"]:
        task.title = data["title"][:300]
    elif created:
        task.title = (upstream)[:300]
    if isinstance(data.get("content"), str) and data["content"]:
        task.description = data["content"]
    deadline = _parse_tzaware(data.get("deadline"))
    if deadline is not None:
        task.deadline = deadline  # type: ignore[assignment]
    task.extra = {
        "assignment_id": data.get("assignment_id"),
        "course_id": data.get("course_id"),
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
    _recompute(session, event.user_id)


def _recompute(session: Session, user_id: uuid.UUID) -> None:
    # Imported lazily to avoid an import cycle (current_state imports schemas).
    from backend.services.current_state import recompute_current_state

    recompute_current_state(session, user_id)
