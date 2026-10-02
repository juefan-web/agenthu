"""Course-material chunks and per-course grounding consent (D-033).

Two user-scoped tables:

- ``material_chunks`` — per-page text derived from an explicitly uploaded
  file. Rows cascade with the file (D-033 §1: blob + row + chunks +
  embeddings share one lifecycle). ``scanner_version`` records which rule
  set scanned the chunk; ``embedding``/``embedding_model`` are backfilled
  only after the user opted the course in (default-off, D-033 §0.4).
- ``grounding_consents`` — the per-course opt-in switch. ``course_name``
  uses the same bare-course-name key as ``task.extra["course_name"]`` and
  ``estimate:course:<name>`` memory subject keys.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class MaterialChunk(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "material_chunks"
    __table_args__ = (
        UniqueConstraint("file_id", "chunk_index", name="uq_material_chunks_file_index"),
        # The user_id filter is the P0 isolation invariant (D-033 §0.2) —
        # every read path starts from this index, never from a bare file_id.
        Index("ix_material_chunks_user_file", "user_id", "file_id"),
        CheckConstraint(
            "scan_status IN ('clean', 'flagged')",
            name="ck_material_chunks_scan_status",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("file_objects.id", ondelete="CASCADE"), nullable=False
    )
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    scanner_version: Mapped[str] = mapped_column(String(64), nullable=False)
    scan_status: Mapped[str] = mapped_column(String(16), nullable=False, default="clean")
    scan_flags: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(100), nullable=True)

    @property
    def embedding_present(self) -> bool:
        return self.embedding is not None


class GroundingConsent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "grounding_consents"
    __table_args__ = (
        UniqueConstraint("user_id", "course_name", name="uq_grounding_consents_user_course"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    course_name: Mapped[str] = mapped_column(String(300), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Version of the consent text the user last acted on; the API rejects
    # opt-ins carrying a stale version so text updates force re-confirmation.
    consent_text_version: Mapped[str] = mapped_column(String(32), nullable=False)
    consented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
