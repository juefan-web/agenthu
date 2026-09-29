"""Client-facing contract schemas.

These mirror ``packages/contracts`` in the desktop client exactly. The desktop
client is the authoritative consumer for these shapes; the Backend must not
diverge. Additional Backend-only fields are allowed because the client validates
with Zod, which strips unknown keys — but every field the client declares must be
present with the declared name and type.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EventProvenance(BaseModel):
    model_config = ConfigDict(extra="allow")

    connector: str = Field(min_length=1)
    connector_version: str = Field(min_length=1)
    upstream_id: str = Field(min_length=1)
    semantic_version: str = Field(min_length=1)
    fetched_at: datetime
    endpoint: str | None = None

    @field_validator("fetched_at")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        return value if value.tzinfo else value.replace(tzinfo=UTC)


class EventEnvelope(BaseModel):
    client_event_id: str = Field(min_length=1, max_length=255)
    type: str = Field(min_length=1, max_length=100)
    occurred_at: datetime
    source: str = Field(min_length=1, max_length=50)
    data: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    provenance: EventProvenance

    @field_validator("occurred_at")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        return value if value.tzinfo else value.replace(tzinfo=UTC)


class EventBatchRequest(BaseModel):
    events: list[EventEnvelope] = Field(min_length=1, max_length=500)
    client_cursor: str | None = None


class EventBatchRejection(BaseModel):
    client_event_id: str
    reason: str


class EventBatchResponse(BaseModel):
    accepted_event_ids: list[str] = Field(default_factory=list)
    duplicate_event_ids: list[str] = Field(default_factory=list)
    rejected: list[EventBatchRejection] = Field(default_factory=list)
    # Deprecated placeholder: it echoes the request's client_cursor back and
    # carries no server-side sync state (see DECISIONS.md D-022). The client
    # owns cursor progress; do not build new behavior on this field.
    next_cursor: str | None = Field(default=None, deprecated=True)


class ClientTask(BaseModel):
    id: uuid.UUID
    title: str
    due_at: datetime | None
    estimate_minutes: int | None
    status: str  # client enum: todo | in_progress | done | cancelled
    source_event_ids: list[uuid.UUID] = Field(default_factory=list)

    # Backend-only additions (stripped by the client's Zod schema).
    description: str | None = None
    goal_id: uuid.UUID | None = None
    actual_duration_minutes: int | None = None
    priority: int = 0
    completed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ClientPlanItem(BaseModel):
    task_id: uuid.UUID | None
    start_at: datetime | None
    end_at: datetime | None
    reason: str

    # Backend-only additions.
    id: uuid.UUID
    title: str
    order_index: int
    planned_minutes: int | None = None
    status: str
    actual_minutes: int | None = None


class ClientPlan(BaseModel):
    id: uuid.UUID
    generated_at: datetime
    items: list[ClientPlanItem] = Field(default_factory=list)
    confirmation_required: bool
    status: str  # client enum

    # Backend-only additions.
    title: str | None = None
    goal_id: uuid.UUID | None = None
    basis: dict[str, Any] = Field(default_factory=dict)
    permission_level: int = 2
    replan_reason: str | None = None
    confirmed_at: datetime | None = None
    cancelled_at: datetime | None = None
    completed_at: datetime | None = None


class ClientCurrentState(BaseModel):
    version: int
    updated_at: datetime | None
    now: datetime
    context: str | None
    tasks: list[ClientTask] = Field(default_factory=list)
    available_minutes: int | None

    # Backend-only additions.
    current_context: dict[str, Any] = Field(default_factory=dict)
    current_task: ClientTask | None = None
    pending_tasks: list[ClientTask] = Field(default_factory=list)
    current_plan: ClientPlan | None = None
    recent_state: dict[str, Any] = Field(default_factory=dict)
    current_time: datetime | None = None


class ClientFocusSession(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    started_at: datetime
    ended_at: datetime | None
    actual_minutes: int | None
    status: str  # running | paused | completed | abandoned
    deviation_note: str | None

    # Backend-only additions.
    user_id: uuid.UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class FocusSessionCreate(BaseModel):
    task_id: uuid.UUID


class FocusSessionUpdate(BaseModel):
    status: str | None = None
    actual_minutes: int | None = Field(default=None, ge=0, le=60 * 24 * 7)
    deviation_note: str | None = Field(default=None, max_length=2000)
