"""Notification preference shapes (D-034; mirrors the frozen client Zod).

``budget_date``/``sent_count``/``last_sent_at`` are server-owned (read-only
to the client, ruling B2); the PATCH body therefore accepts only the user
preferences plus ``expected_version`` for optimistic concurrency (409 on
mismatch, latest row returned so two clients never silently overwrite).
"""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime

from pydantic import BaseModel, field_validator

from backend.schemas.common import ORMModel

_HH_MM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class NotificationPreferencesRead(ORMModel):
    id: uuid.UUID
    version: int
    timezone: str
    enabled_categories: list[str] = []
    quiet_hours_start: str | None = None
    quiet_hours_end: str | None = None
    daily_budget: int
    sent_count: int
    budget_date: date
    last_sent_at: datetime | None = None


class NotificationPreferencesPatch(BaseModel):
    expected_version: int
    timezone: str | None = None
    enabled_categories: list[str] | None = None
    quiet_hours_start: str | None = None
    quiet_hours_end: str | None = None
    daily_budget: int | None = None

    @field_validator("quiet_hours_start", "quiet_hours_end")
    @classmethod
    def _validate_hh_mm(cls, value: str | None) -> str | None:
        if value is not None and not _HH_MM.match(value):
            raise ValueError("quiet hours must be local HH:mm strings (e.g. 22:00)")
        return value

    @field_validator("daily_budget")
    @classmethod
    def _validate_budget(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("daily_budget must be >= 0")
        return value
