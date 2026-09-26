from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from backend.models.enums import TaskStatus
from backend.schemas.common import ORMModel


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str | None = None
    source: str = Field(default="manual", max_length=50)
    status: TaskStatus = TaskStatus.TODO
    deadline: datetime | None = None
    estimated_duration_minutes: int | None = Field(default=None, ge=0, le=60 * 24 * 30)
    priority: int = 0
    goal_id: uuid.UUID | None = None
    related_event_ids: list[uuid.UUID] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = None
    status: TaskStatus | None = None
    deadline: datetime | None = None
    estimated_duration_minutes: int | None = Field(default=None, ge=0, le=60 * 24 * 30)
    actual_duration_minutes: int | None = Field(default=None, ge=0, le=60 * 24 * 30)
    priority: int | None = None
    goal_id: uuid.UUID | None = None
    extra: dict[str, Any] | None = None


class FocusCompleteRequest(BaseModel):
    actual_minutes: int = Field(ge=1, le=60 * 24 * 7)
    completed: bool = True
    notes: str | None = Field(default=None, max_length=2000)


class TaskRead(ORMModel):
    id: uuid.UUID
    user_id: uuid.UUID
    goal_id: uuid.UUID | None
    title: str
    description: str | None
    source: str
    status: TaskStatus
    deadline: datetime | None
    estimated_duration_minutes: int | None
    actual_duration_minutes: int | None
    priority: int
    completed_at: datetime | None
    extra: dict[str, Any]
    related_event_ids: list[uuid.UUID] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
