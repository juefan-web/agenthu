"""Data lifecycle API schemas (M5 P0-3, A-draft §4 frozen r2).

/v1/data serves previews, deletion confirmation and operation status for the
user-control surface. Requests never carry a trusted user id (the auth
context is the identity), enums are strict, unknown fields are rejected, and
every count is non-negative.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.models.enums import DataOperationKind, DataOperationPhase, DataOperationStatus
from backend.schemas.common import ORMModel

SourceKind = Literal["event", "file", "chat_session", "chat_message"]

_SUPPORTED_SOURCE_KINDS: list[str] = ["event", "file", "chat_session", "chat_message"]

IdList = Annotated[list[uuid.UUID], Field(min_length=1, max_length=100)]


class AccountTarget(BaseModel):
    """DeleteTarget variant: the whole account and everything derived."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["account"]


class SourceTarget(BaseModel):
    """DeleteTarget variant: one source batch and its derivation closure."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["source"]
    source_kind: SourceKind
    ids: IdList


class MemoryTarget(BaseModel):
    """DeleteTarget variant: whole memory chains (history is always included)."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["memory"]
    ids: IdList
    # Literal[True]: forgetting a memory means its whole version chain; the
    # field exists so clients must say so explicitly, and cannot be false.
    include_history: Literal[True]


DeleteTargetIn = Annotated[AccountTarget | SourceTarget | MemoryTarget, Field(discriminator="kind")]


class DataCapabilities(BaseModel):
    schema_version: str
    graph_version: str
    export_enabled: bool
    deletion_enabled: bool
    supported_source_kinds: list[str]
    minimum_client_version: str


class DataEffect(BaseModel):
    """One family's outcome counts; never carries titles or content."""

    resource_type: str
    delete_count: int = Field(ge=0)
    redact_count: int = Field(ge=0)
    recompute_count: int = Field(ge=0)
    retain_count: int = Field(ge=0)
    reason_code: str


class DataPreviewOut(BaseModel):
    id: uuid.UUID
    target: dict[str, object]
    graph_version: str
    data_generation: int
    preview_digest: str
    expires_at: datetime
    effects: list[DataEffect]
    limitations: list[str]


class DeletionConfirmRequest(BaseModel):
    """Level 2 confirmation: references the exact preview the user saw."""

    model_config = ConfigDict(extra="forbid")

    preview_id: uuid.UUID
    preview_digest: str = Field(min_length=64, max_length=64)
    client_request_id: str = Field(min_length=8, max_length=128)
    confirmed: Literal[True]


class OperationProgress(BaseModel):
    processed: int = Field(ge=0)
    total: int | None = None
    outstanding_count: int = Field(ge=0)


class DataSafeError(BaseModel):
    """Sanitized failure info: no raw text, object keys or credentials."""

    code: str
    message: str
    retryable: bool


class DataOperationOut(ORMModel):
    id: uuid.UUID
    kind: DataOperationKind
    target: dict[str, object] | None
    status: DataOperationStatus
    phase: DataOperationPhase | None
    version: int
    data_generation: int
    created_at: datetime
    updated_at: datetime
    next_retry_at: datetime | None = None
    expires_at: datetime | None = None
    progress: OperationProgress
    error: DataSafeError | None = None
    receipt_id: uuid.UUID | None = None
    # Returned exactly once, on the accepting response of an account
    # deletion; every later read exposes receipt_id only.
    receipt_capability: str | None = None
