"""Chat read shapes (D-034; mirrors the frozen client Zod).

``decision_basis`` / ``pending_action_id`` on messages are JOIN projections
over ``agent_run_id`` (ruling A5: no second stored copy) — the API layer
fills them, the columns do not exist on ``chat_messages``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

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
    id: uuid.UUID
    role: MessageRole
    content: str
    created_at: datetime
    agent_run_id: uuid.UUID | None = None
    decision_basis: DecisionBasis | None = None
    pending_action_id: uuid.UUID | None = None
