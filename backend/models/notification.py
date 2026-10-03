"""Per-user notification preferences and interruption budget (D-034).

Server-side enforcement surface for the proactive agent (contract §8): the
budget settles atomically per user-local day (``budget_date`` + ``sent_count``
are server-owned; the client reads them but never writes). Quiet hours are
local ``HH:mm`` strings validated against ``timezone``; a window crossing
midnight (e.g. 22:00 -> 07:00) is legal. The A3 slice adds the settlement
logic; this table is the frozen shape it settles against.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class NotificationPreference(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "notification_preferences"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_notification_preferences_user"),
        CheckConstraint("daily_budget >= 0", name="ck_notification_preferences_budget"),
        CheckConstraint(
            "quiet_hours_start IS NULL AND quiet_hours_end IS NULL "
            "OR quiet_hours_start IS NOT NULL AND quiet_hours_end IS NOT NULL",
            name="ck_notification_preferences_quiet_hours_pair",
        ),
        Index("ix_notification_preferences_budget_date", "budget_date"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Optimistic concurrency for PATCH (409 on mismatch).
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Shanghai")
    enabled_categories: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Local HH:mm or NULL when quiet hours are disabled.
    quiet_hours_start: Mapped[str | None] = mapped_column(String(5), nullable=True)
    quiet_hours_end: Mapped[str | None] = mapped_column(String(5), nullable=True)
    daily_budget: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    # Server-owned settlement fields (B2: read-only to the client).
    budget_date: Mapped[date] = mapped_column(
        Date, nullable=False, server_default=func.current_date()
    )
    sent_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
