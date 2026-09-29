from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from backend.models.enums import MemoryCorrectionStatus
from backend.schemas.common import ORMModel


class MemoryCreate(BaseModel):
    content: str = Field(min_length=1, max_length=10_000)
    level: int = Field(default=1, ge=0, le=3)
    domain: str = Field(default="general", max_length=50)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    correction_status: MemoryCorrectionStatus = MemoryCorrectionStatus.UNREVIEWED
    source: dict[str, Any] = Field(default_factory=dict)
    source_event_ids: list[uuid.UUID] = Field(default_factory=list)


class MemoryUpdate(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=10_000)
    level: int | None = Field(default=None, ge=0, le=3)
    domain: str | None = Field(default=None, max_length=50)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    correction_status: MemoryCorrectionStatus | None = None
    source: dict[str, Any] | None = None
    source_event_ids: list[uuid.UUID] | None = None


class MemoryRead(ORMModel):
    id: uuid.UUID
    user_id: uuid.UUID
    level: int
    domain: str
    content: str
    source: dict[str, Any]
    source_event_ids: list[uuid.UUID]
    confidence: float
    correction_status: MemoryCorrectionStatus
    created_at: datetime
    updated_at: datetime
