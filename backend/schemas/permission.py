from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from backend.schemas.common import ORMModel


class PermissionGrantCreate(BaseModel):
    action: str = Field(min_length=1, max_length=120)
    level: int = Field(default=3, ge=0, le=3)
    scope: dict[str, Any] = Field(default_factory=dict)
    note: str | None = None
    expires_at: datetime | None = None


class PermissionGrantRead(ORMModel):
    id: uuid.UUID
    user_id: uuid.UUID
    action: str
    level: int
    scope: dict[str, Any]
    note: str | None
    granted_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None


class PermissionPolicyEntry(BaseModel):
    action: str
    level: int
    description: str


class PermissionPolicyRead(BaseModel):
    levels: dict[str, str]
    actions: list[PermissionPolicyEntry]


class PermissionCheckRequest(BaseModel):
    action: str = Field(min_length=1, max_length=120)
    required_level: int | None = Field(default=None, ge=0, le=3)


class PermissionCheckResult(BaseModel):
    action: str
    required_level: int
    granted_level: int
    decision: str
    allowed: bool
    requires_confirmation: bool
    reason: str
