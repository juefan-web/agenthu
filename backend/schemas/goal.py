from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from backend.models.enums import GoalStatus
from backend.schemas.common import ORMModel


class GoalCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str | None = None
    category: str = Field(default="general", max_length=50)
    priority: int = 0
    target_date: datetime | None = None


class GoalUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = None
    category: str | None = Field(default=None, max_length=50)
    priority: int | None = None
    target_date: datetime | None = None
    status: GoalStatus | None = None


class GoalRead(ORMModel):
    id: uuid.UUID
    user_id: uuid.UUID
    title: str
    description: str | None
    category: str
    status: GoalStatus
    priority: int
    target_date: datetime | None
    created_at: datetime
    updated_at: datetime
