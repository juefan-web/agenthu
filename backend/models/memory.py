from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Float, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from backend.models.enums import MemoryCorrectionStatus, sa_enum


class Memory(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A traceable memory entry.

    M0 only guarantees reliable storage and CRUD. Automatic extraction,
    embedding/vector retrieval and multi-level cognition are later milestones.
    Every entry keeps its source, confidence and user-correction status so that
    a wrong memory can be corrected, down-weighted or deleted.
    """

    __tablename__ = "memories"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=1, index=True)
    domain: Mapped[str] = mapped_column(String(50), nullable=False, default="general", index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    source_event_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    correction_status: Mapped[MemoryCorrectionStatus] = mapped_column(
        sa_enum(MemoryCorrectionStatus, "memory_correction_status"),
        nullable=False,
        default=MemoryCorrectionStatus.UNREVIEWED,
        index=True,
    )
