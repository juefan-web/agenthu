"""Focus session helpers.

Focus is modeled as Events plus projection handlers, never as ad-hoc state:
starting/completing a focus session emits ``focus.started`` / ``focus.completed``
events, and the registered handlers update the Task, actual duration and
CurrentState. This keeps the loop (plan -> focus -> result -> re-plan) auditable.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from backend.db.base import utcnow
from backend.models.event import Event
from backend.models.task import Task
from backend.schemas.event import EventCreate
from backend.services.events import create_event


def emit_focus_started(session: Session, *, user_id: uuid.UUID, task: Task) -> Event:
    payload = EventCreate(
        type="focus.started",
        source="backend",
        data={"task_id": str(task.id)},
        context={"task_title": task.title},
        provenance={"origin": "backend.focus.start"},
        dedupe_key=None,
    )
    event, _ = create_event(session, user_id=user_id, payload=payload)
    return event


def emit_focus_completed(
    session: Session,
    *,
    user_id: uuid.UUID,
    task: Task,
    actual_minutes: int,
    completed: bool = True,
    notes: str | None = None,
    timestamp: datetime | None = None,
) -> Event:
    payload = EventCreate(
        type="focus.completed",
        source="backend",
        data={
            "task_id": str(task.id),
            "actual_minutes": actual_minutes,
            "completed": completed,
            "notes": notes,
        },
        context={
            "task_title": task.title,
            "estimated_duration_minutes": task.estimated_duration_minutes,
        },
        provenance={"origin": "backend.focus.complete"},
        timestamp=timestamp or utcnow(),
    )
    event, _ = create_event(session, user_id=user_id, payload=payload)
    return event
