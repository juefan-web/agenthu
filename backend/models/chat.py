"""Chat sessions and messages (D-034, M4-A1 contract slice).

Chat is one entry to the same agent, persisted as its own data — never
stuffed into AuditLog. Messages are immutable once written (no edit path);
``deleted_at`` soft-deletes a message and the FTS/retrieval eligibility drops
in the same transaction (the trigram index itself arrives with the A3
retrieval slice). ``agent_run_id`` links an assistant message to the run that
produced it (SET NULL: deleting history keeps the run's audit record without
resurrecting content — the run row stores references, never chat originals).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, utcnow


class ChatSession(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "chat_sessions"
    __table_args__ = (Index("ix_chat_sessions_user_updated", "user_id", "updated_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Deterministic by default: truncated first user message. A client MAY
    # pass an explicit title at creation (contract §8); no LLM involved.
    title: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ChatMessage(Base, UUIDPrimaryKeyMixin):
    """Immutable chat message; ``updated_at`` deliberately absent."""

    __tablename__ = "chat_messages"
    __table_args__ = (
        Index("ix_chat_messages_session_created", "session_id", "created_at"),
        Index("ix_chat_messages_user_created", "user_id", "created_at"),
        CheckConstraint("role IN ('user', 'assistant')", name="ck_chat_messages_role"),
    )

    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False
    )
    # Redundant with the session's owner so every retrieval path filters by
    # user without a join (P0 isolation invariant).
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True
    )
    # Python-side default (microsecond resolution) alongside the server
    # default: a user message and its assistant reply are written in ONE
    # transaction, where the transaction-stable ``now()`` would tie and leave
    # the (created_at, id) keyset ordered by random uuid4s — bubbles could
    # swap. Client-side stamps keep same-transaction writes ordered.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=func.now(),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
