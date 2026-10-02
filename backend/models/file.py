from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class FileObject(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Metadata for an object stored in S3-compatible storage.

    Raw bytes (PDF/PPT/audio/transcripts) live in object storage, never in the
    relational database. The row keeps provenance and lifecycle metadata.
    """

    __tablename__ = "file_objects"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    storage_backend: Mapped[str] = mapped_column(String(50), nullable=False, default="minio")
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[str] = mapped_column(
        String(200), nullable=False, default="application/octet-stream"
    )
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")
    # Bare course name (same key as task.extra["course_name"]); only files
    # uploaded with a course enter the grounding ingestion pipeline.
    course_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    file_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
