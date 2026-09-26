from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from backend.core.sensitive import validate_json_payload
from backend.db.base import utcnow
from backend.schemas.common import ORMModel

# Lower-case, dot/underscore/colon/dash separated identifiers: "assignment.created",
# "focus.completed", "onethu.course.updated".
_IDENTIFIER = r"^[a-z0-9]+(?:[._:-][a-z0-9]+)*$"

EventType = Annotated[str, Field(min_length=1, max_length=100, pattern=_IDENTIFIER)]
EventSourceName = Annotated[str, Field(min_length=1, max_length=50, pattern=_IDENTIFIER)]


class EventCreate(BaseModel):
    # Accept both the internal name and the client contract name.
    model_config = ConfigDict(populate_by_name=True)

    type: EventType
    timestamp: datetime = Field(
        default_factory=utcnow,
        validation_alias=AliasChoices("timestamp", "occurred_at"),
    )
    source: EventSourceName = "manual"
    data: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)
    dedupe_key: str | None = Field(default=None, max_length=255)

    @field_validator("timestamp")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value

    @field_validator("data", "context", "provenance")
    @classmethod
    def _reject_sensitive_payload(
        cls, value: dict[str, Any], info: ValidationInfo
    ) -> dict[str, Any]:
        error = validate_json_payload(info.field_name or "payload", value)
        if error is not None:
            raise ValueError(error)
        return value


class EventRead(ORMModel):
    id: uuid.UUID
    user_id: uuid.UUID
    type: str
    timestamp: datetime
    occurred_at: datetime
    source: str
    data: dict[str, Any]
    context: dict[str, Any]
    provenance: dict[str, Any]
    dedupe_key: str | None
    client_event_id: str | None
    ingested_at: datetime
    created_at: datetime
    updated_at: datetime
