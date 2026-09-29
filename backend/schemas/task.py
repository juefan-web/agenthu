from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from backend.models.enums import TaskStatus
from backend.schemas.common import ORMModel, UTCDatetime

# Accept both the internal enum names and the client contract values.
_CLIENT_TASK_STATUS = {
    "todo": TaskStatus.TODO,
    "in_progress": TaskStatus.IN_PROGRESS,
    "done": TaskStatus.COMPLETED,
    "cancelled": TaskStatus.CANCELLED,
}


def _normalize_task_status(value: object) -> object:
    if isinstance(value, str):
        return _CLIENT_TASK_STATUS.get(value.lower(), value.upper())
    return value


class TaskCreate(BaseModel):
    # Accept both internal names and the client contract names.
    model_config = ConfigDict(populate_by_name=True)

    title: str = Field(min_length=1, max_length=300)
    description: str | None = None
    source: str = Field(default="manual", max_length=50)
    status: TaskStatus = TaskStatus.TODO
    deadline: UTCDatetime | None = Field(
        default=None, validation_alias=AliasChoices("deadline", "due_at")
    )
    estimated_duration_minutes: int | None = Field(
        default=None,
        ge=0,
        le=60 * 24 * 30,
        validation_alias=AliasChoices("estimated_duration_minutes", "estimate_minutes"),
    )
    priority: int = 0
    goal_id: uuid.UUID | None = None
    related_event_ids: list[uuid.UUID] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)

    @field_validator("status", mode="before")
    @classmethod
    def _normalize_status(cls, value: object) -> object:
        return _normalize_task_status(value)


class TaskUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = None
    status: TaskStatus | None = None
    deadline: UTCDatetime | None = Field(
        default=None, validation_alias=AliasChoices("deadline", "due_at")
    )
    estimated_duration_minutes: int | None = Field(
        default=None,
        ge=0,
        le=60 * 24 * 30,
        validation_alias=AliasChoices("estimated_duration_minutes", "estimate_minutes"),
    )
    actual_duration_minutes: int | None = Field(default=None, ge=0, le=60 * 24 * 30)
    priority: int | None = None
    goal_id: uuid.UUID | None = None
    extra: dict[str, Any] | None = None

    @field_validator("status", mode="before")
    @classmethod
    def _normalize_status(cls, value: object) -> object:
        return _normalize_task_status(value)


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
