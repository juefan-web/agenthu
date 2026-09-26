"""Event -> domain projection registry.

External sources are normalized to Events. Registered handlers turn those facts
into domain changes (Task status, CurrentState, and later Memory). This keeps
projection logic in one place instead of scattering it across adapters.

Handlers run inside the ingestion transaction *before* commit. A failing
handler must not lose the raw Event, so failures are logged and audited rather
than propagated.
"""

from __future__ import annotations

import fnmatch
import logging
import uuid
from collections.abc import Callable
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
            task.actual_duration_minutes = (task.actual_duration_minutes or 0) + actual
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
            item.actual_minutes = actual_minutes


@register("task.*")
def handle_task_event(session: Session, event: Event) -> None:
    # Any task lifecycle event can change the projection.
    _recompute(session, event.user_id)


def _recompute(session: Session, user_id: uuid.UUID) -> None:
    # Imported lazily to avoid an import cycle (current_state imports schemas).
    from backend.services.current_state import recompute_current_state

    recompute_current_state(session, user_id)
