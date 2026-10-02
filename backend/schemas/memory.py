from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from backend.models.enums import MemoryCorrectionStatus, MemoryKind
from backend.schemas.common import ORMModel


class EventEvidence(BaseModel):
    """A citation of a stored Event by id."""

    type: Literal["event"]
    id: uuid.UUID


class MemoryEvidence(BaseModel):
    """A citation of another memory row (e.g. L2 facts citing their L1 base)."""

    type: Literal["memory"]
    id: uuid.UUID


class DocumentEvidence(BaseModel):
    """A citation pinned to an exact document version (M3 grounding tuple)."""

    type: Literal["document"]
    file_id: uuid.UUID
    checksum_sha256: str = Field(min_length=8, max_length=64)
    page: int = Field(ge=0)
    span_start: int = Field(ge=0)
    span_end: int = Field(ge=0)


Evidence = Annotated[
    EventEvidence | MemoryEvidence | DocumentEvidence,
    Field(discriminator="type"),
]


class MemoryCreate(BaseModel):
    content: str = Field(min_length=1, max_length=10_000)
    level: int = Field(default=1, ge=0, le=3)
    domain: str = Field(default="general", max_length=50)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    # correction_status is NOT settable here: every memory enters as
    # UNREVIEWED (or CONFIRMED via a server writer) and moves through the
    # semantic endpoints only (D-032 ruling: direct fills bypass the
    # version chain).
    source: dict[str, Any] = Field(default_factory=dict)
    source_event_ids: list[uuid.UUID] = Field(default_factory=list)
    # M2 extension (D-031 §3). subject_key/evidence are writable; the version
    # chain pointer and the decision-telemetry columns are server-managed and
    # intentionally absent here (they appear in MemoryRead only).
    kind: MemoryKind | None = None
    subject_key: str | None = Field(default=None, max_length=255)
    evidence: list[Evidence] = Field(default_factory=list, max_length=100)
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class MemoryUpdate(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=10_000)
    level: int | None = Field(default=None, ge=0, le=3)
    domain: str | None = Field(default=None, max_length=50)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    # No correction_status: semantic endpoint only (confirm/correct/reject);
    # a direct fill here would bypass the version chain (D-032 ruling). The
    # key is silently ignored on the wire, same as any unknown key.
    source: dict[str, Any] | None = None
    source_event_ids: list[uuid.UUID] | None = None
    kind: MemoryKind | None = None
    subject_key: str | None = Field(default=None, max_length=255)
    evidence: list[Evidence] | None = Field(default=None, max_length=100)
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class MemoryCorrectRequest(BaseModel):
    """User correction payload for POST /memory/{id}/correct.

    Content is the corrected text; confidence optionally overrides (the old
    row's value carries over when absent). The new version is CONFIRMED by
    definition — the user wrote it.
    """

    content: str = Field(min_length=1, max_length=10_000)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class MemoryRead(ORMModel):
    id: uuid.UUID
    user_id: uuid.UUID
    level: int
    domain: str
    content: str
    source: dict[str, Any]
    source_event_ids: list[uuid.UUID]
    confidence: float
    correction_status: MemoryCorrectionStatus
    # Stored evidence stays loose on read (forward-compatible with new
    # element types); writers are validated by the discriminated union above.
    evidence: list[dict[str, Any]]
    kind: MemoryKind | None
    subject_key: str | None
    supersedes_id: uuid.UUID | None
    valid_from: datetime | None
    valid_to: datetime | None
    use_count: int
    last_used_at: datetime | None
    # Read-only (M3 pgvector slice): embeddings are produced by server writers;
    # MemoryCreate/Update never accept one. None until the retrieval slice
    # backfills it.
    embedding: list[float] | None
    created_at: datetime
    updated_at: datetime
