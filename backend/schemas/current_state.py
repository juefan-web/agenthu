from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from backend.schemas.plan import PlanRead
from backend.schemas.task import TaskRead


class CurrentStateRead(BaseModel):
    """Projection of the user's present.

    Built explicitly by ``CurrentStateService`` (not ``from_attributes``) because
    it joins Tasks, Plans, and recent Events.
    """

    user_id: uuid.UUID
    version: int
    current_time: datetime
    current_context: dict[str, Any] = Field(default_factory=dict)
    current_task: TaskRead | None = None
    pending_tasks: list[TaskRead] = Field(default_factory=list)
    current_plan: PlanRead | None = None
    recent_state: dict[str, Any] = Field(default_factory=dict)
    available_minutes: int | None = None
    # Effective context label: user override first, otherwise derived from the
    # schedule/focus/task chain (D-027). Internal field — the client contract
    # consumes it via client_view, it is not exposed in OpenAPI directly.
    context_label: str | None = None
    updated_at: datetime | None = None


class CurrentStateUpdate(BaseModel):
    """User-controlled overrides applied before the next projection."""

    current_context: dict[str, Any] | None = None
    current_task_id: uuid.UUID | None = None
    available_minutes: int | None = Field(default=None, ge=0, le=60 * 24 * 30)
