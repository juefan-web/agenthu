from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from backend.models.enums import FocusSessionStatus, sa_enum


class FocusSession(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A persisted focus session with an explicit lifecycle.

    States: running -> paused -> running -> completed / abandoned. Completion is
    idempotent: repeating a completion returns the same session and does not add
    to the task's actual duration again (guarded by an event dedupe key).
    """

    __tablename__ = "focus_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[FocusSessionStatus] = mapped_column(
        sa_enum(FocusSessionStatus, "focus_session_status"),
        nullable=False,
        default=FocusSessionStatus.RUNNING,
        index=True,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    actual_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deviation_note: Mapped[str | None] = mapped_column(Text, nullable=True)
