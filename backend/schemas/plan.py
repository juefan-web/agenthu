from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from backend.models.enums import PlanItemStatus, PlanStatus
from backend.schemas.common import ORMModel, UTCDatetime


class PlanItemCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    task_id: uuid.UUID | None = None
    order_index: int = 0
    planned_start: UTCDatetime | None = None
    planned_end: UTCDatetime | None = None
    planned_minutes: int | None = Field(default=None, ge=0, le=60 * 24 * 30)
    notes: str | None = None


class PlanItemUpdate(BaseModel):
    status: PlanItemStatus | None = None
    actual_minutes: int | None = Field(default=None, ge=0, le=60 * 24 * 30)
    result: dict[str, Any] | None = None
    notes: str | None = None


class PlanItemRead(ORMModel):
    id: uuid.UUID
    plan_id: uuid.UUID
    task_id: uuid.UUID | None
    title: str
    order_index: int
    planned_start: datetime | None
    planned_end: datetime | None
    planned_minutes: int | None
    status: PlanItemStatus
    actual_minutes: int | None
    result: dict[str, Any] | None
    notes: str | None


class PlanCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    goal_id: uuid.UUID | None = None
    permission_level: int = Field(default=2, ge=0, le=3)
    basis: dict[str, Any] = Field(default_factory=dict)
    items: list[PlanItemCreate] = Field(default_factory=list)


class PlanGenerateRequest(BaseModel):
    """Deterministic baseline planner input (no LLM in M0)."""

    goal_id: uuid.UUID | None = None
    start_at: UTCDatetime | None = None
    horizon_minutes: int = Field(default=240, ge=15, le=60 * 24 * 7)
    max_tasks: int = Field(default=10, ge=1, le=100)


class PlanReplanRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    horizon_minutes: int = Field(default=240, ge=15, le=60 * 24 * 7)


class PlanRead(ORMModel):
    id: uuid.UUID
    user_id: uuid.UUID
    goal_id: uuid.UUID | None
    replaces_plan_id: uuid.UUID | None
    title: str
    status: PlanStatus
    basis: dict[str, Any]
    permission_level: int
    generated_by: str
    replan_reason: str | None
    execution_result: dict[str, Any] | None
    confirmed_at: datetime | None
    cancelled_at: datetime | None
    completed_at: datetime | None
    items: list[PlanItemRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
