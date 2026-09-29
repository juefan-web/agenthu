from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class CurrentState(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A queryable projection of the user's *present*.

    This is deliberately not a copy of the Event stream: it is recomputed from
    Tasks, Plans and recent Events via ``CurrentStateService``. ``version`` and
    ``updated_at`` allow clients to sync and detect staleness.
    """

    __tablename__ = "current_states"
    __table_args__ = (UniqueConstraint("user_id", name="uq_current_states_user"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    current_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    current_context: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    current_task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True
    )
    current_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("plans.id", ondelete="SET NULL"), nullable=True
    )
    pending_task_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    recent_state: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    available_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
