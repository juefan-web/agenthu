"""Declarative base and shared model mixins.

Conventions (frozen for M0):
- UUID primary keys generated in Python (``uuid4``).
- Timezone-aware timestamps in UTC. ``DateTime(timezone=True)`` maps to
  ``timestamptz`` on PostgreSQL.
- ``created_at`` / ``updated_at`` are managed by the database where possible.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    """Timezone-aware current UTC time."""

    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Shared SQLAlchemy declarative base."""


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
