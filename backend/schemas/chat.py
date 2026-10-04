"""Chat read shapes (D-034; mirrors the frozen client Zod; D-035 adds
``session_id`` and the search result item).

``decision_basis`` / ``pending_action_id`` on messages are JOIN projections
over ``agent_run_id`` (ruling A5: no second stored copy) — the API layer
fills them, the columns do not exist on ``chat_messages``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from backend.schemas.agent import DecisionBasis
from backend.schemas.common import ORMModel

MessageRole = Literal["user", "assistant"]


class ChatSessionRead(ORMModel):
    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None


class ChatMessageRead(ORMModel):
    # session_id is required and server-always-set (D-035): a message
    # carries its own session location so search hits and deep links never
    # depend on out-of-band context. Additive for existing consumers — the
    # client Zod strips unknown keys until its mirror lands.
    session_id: uuid.UUID
    id: uuid.UUID
    role: MessageRole
    content: str
    created_at: datetime
    agent_run_id: uuid.UUID | None = None
    decision_basis: DecisionBasis | None = None
    pending_action_id: uuid.UUID | None = None


class ChatSearchItem(ChatMessageRead):
    """Chat search hit (D-035): the message plus its session's CURRENT
    title — flat on purpose. A nested ChatSessionRead would repeat four
    constant fields per hit for zero gain; the client renders
    "title · time" and deep-links from this one row."""

    session_title: str


class ChatSessionCreate(BaseModel):
    """Frozen create request (B1 Zod mirror). The title is optional; an
    empty title is backfilled deterministically from the first user message
    (truncation, no LLM)."""

    title: str | None = Field(default=None, max_length=120)
    client_request_id: str | None = Field(default=None, max_length=120)


class ChatMessageSend(BaseModel):
    """Frozen send request (B1 Zod mirror): ``client_message_id`` is
    REQUIRED — message-level idempotency (ruling A2) rides on it."""

    content: str = Field(min_length=1, max_length=8000)
    client_message_id: str = Field(min_length=1, max_length=64)


class ChatMessageSendResponse(BaseModel):
    """202 body (B1 Zod mirror): poll the run or the session for the
    assistant reply."""

    run_id: uuid.UUID
    user_message_id: uuid.UUID
