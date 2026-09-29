from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from backend.models.enums import PlanItemStatus, PlanStatus, sa_enum

if TYPE_CHECKING:
    pass


class Plan(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A proposed or confirmed schedule.

    ``basis`` stores the explainability payload (which events/tasks/current-state
    version and goals the plan was derived from). ``permission_level`` records the
    authorization required before the Agent may execute the plan.
    """

    __tablename__ = "plans"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    goal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("goals.id", ondelete="SET NULL"), nullable=True, index=True
    )
    replaces_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("plans.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[PlanStatus] = mapped_column(
        sa_enum(PlanStatus, "plan_status"),
        nullable=False,
        default=PlanStatus.DRAFT,
        index=True,
    )
    basis: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    permission_level: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    generated_by: Mapped[str] = mapped_column(String(50), nullable=False, default="manual")
    replan_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    execution_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    items: Mapped[list[PlanItem]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="PlanItem.order_index",
        lazy="selectin",
    )


class PlanItem(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "plan_items"

    plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    planned_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    planned_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    planned_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[PlanItemStatus] = mapped_column(
        sa_enum(PlanItemStatus, "plan_item_status"),
        nullable=False,
        default=PlanItemStatus.PENDING,
    )
    actual_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    plan: Mapped[Plan] = relationship(back_populates="items")
