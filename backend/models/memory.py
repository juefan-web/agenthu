from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from backend.models.enums import MemoryCorrectionStatus, MemoryKind, sa_enum


class Memory(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A traceable memory entry.

    M0 only guarantees reliable storage and CRUD. Automatic extraction,
    embedding/vector retrieval and multi-level cognition are later milestones.
    Every entry keeps its source, confidence and user-correction status so that
    a wrong memory can be corrected, down-weighted or deleted.

    M2 extension (D-031 §3, migration plan in TASKS/m3-memory-schema-migration.md):
    keyed rows aggregate by ``subject_key`` with at most one live row
    (``supersedes_id IS NULL``) per (user, key); corrections supersede instead
    of editing in place; ``evidence`` is the canonical reference list (events,
    memories, document anchors); ``use_count``/``last_used_at`` record only
    "entered a decision context" (planner retrieval / agent context assembly),
    never "was retrieved as a candidate".
    """

    __tablename__ = "memories"
    __table_args__ = (
        # Live-row invariant: at most one non-superseded row per (user, key).
        Index(
            "uq_memories_user_subject_live",
            "user_id",
            "subject_key",
            unique=True,
            postgresql_where=text("subject_key IS NOT NULL AND supersedes_id IS NULL"),
        ),
        # Reverse-chain traversal for the deletion/dependency graph.
        Index(
            "ix_memories_supersedes",
            "supersedes_id",
            postgresql_where=text("supersedes_id IS NOT NULL"),
        ),
        # Lineage enumeration: "which memories cite event/memory/document X".
        Index(
            "ix_memories_evidence",
            "evidence",
            postgresql_using="gin",
            postgresql_ops={"evidence": "jsonb_path_ops"},
        ),
    )

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

    # Stable aggregation key for keyed writers (L2 facts such as
    # "estimate:course:<course>"); append-only rows (L1 episodes) keep NULL.
    subject_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Unlike the other enums, MemoryKind's member NAMES are uppercase while
    # the migration's CHECK constraint (and the client-facing values) are
    # lowercase. SQLAlchemy binds member names unless values_callable says
    # otherwise — without it, create_all-built test databases accept what the
    # migrated ones reject (the E4 first-run failure). Only this enum opts in:
    # the shared helper must stay name-bound for legacy tables whose stored
    # values are the uppercase names (e.g. focus session status).
    kind: Mapped[MemoryKind | None] = mapped_column(
        SAEnum(
            MemoryKind,
            name="memory_kind",
            native_enum=False,
            length=32,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=True,
    )
    # Canonical evidence list: {type:"event", id} | {type:"memory", id} |
    # {type:"document", file_id, checksum_sha256, page, span_start, span_end}.
    # source_event_ids stays as the denormalized event-id subset (D-014).
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Version chain: a correction/aggregation writes a NEW row pointing at the
    # row it replaces; live rows have supersedes_id IS NULL. The FK is
    # DEFERRABLE because the write order is fixed the other way round: the old
    # row must retire (take the pointer) BEFORE the new live row inserts —
    # the partial unique index cannot be deferred, so it demands that order,
    # and the pointer is checked at commit instead (migration plan §3).
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("memories.id", ondelete="SET NULL", deferrable=True, initially="DEFERRED"),
        nullable=True,
    )
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    use_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # M3 slice: 1536-dim embedding for vector recall. Nullable because rows
    # exist before embedding backfill and non-text rows never get one; the
    # writers that fill it arrive with the retrieval slice, not here.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)
