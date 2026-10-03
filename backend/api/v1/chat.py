"""Chat read face (D-034, M4-A1).

Read-only session/message listing with D-029 keyset pagination. Writes
(POST sessions/messages, DELETE) land with the A2 runner and A3 retrieval
slices; ``decision_basis``/``pending_action_id`` on messages are JOIN
projections over ``agent_run_id`` (ruling A5 — no second stored copy).
Deleted messages (``deleted_at`` set) are excluded from reads; their FTS
removal arrives with the A3 index in the same transaction as the delete.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import cast

from fastapi import APIRouter, Query
from sqlalchemy import select, true

from backend.api.deps import CurrentUser, DBSession
from backend.core.errors import NotFoundError, ValidationError
from backend.models.agent import AgentRun, PendingAction
from backend.models.chat import ChatMessage, ChatSession
from backend.schemas.agent import DecisionBasis
from backend.schemas.chat import ChatMessageRead, ChatSessionRead, MessageRole
from backend.schemas.common import Page
from backend.services.pagination import count_total, decode_cursor, keyset_page

router = APIRouter(prefix="/chat", tags=["chat"])


def _session_or_404(session_id: uuid.UUID, user, db) -> ChatSession:
    row = db.scalar(
        select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == user.id)
    )
    if row is None:
        raise NotFoundError("Chat session not found")
    return row


def _message_read(db, message: ChatMessage) -> ChatMessageRead:
    decision_basis = None
    pending_action_id = None
    if message.agent_run_id is not None:
        # A5 projections: joined from the run, never stored twice. A dangling
        # agent_run_id cannot normally occur (FK is SET NULL), so a missing
        # run simply renders without projections.
        run = db.scalar(
            select(AgentRun).where(
                AgentRun.id == message.agent_run_id,
                AgentRun.user_id == message.user_id,
            )
        )
        if run is not None:
            if run.decision_basis:
                decision_basis = DecisionBasis.model_validate(run.decision_basis)
            pending_action_id = db.scalar(
                select(PendingAction.id)
                .where(
                    PendingAction.agent_run_id == run.id,
                    PendingAction.user_id == message.user_id,
                )
                .limit(1)
            )
    return ChatMessageRead(
        id=message.id,
        role=cast(MessageRole, message.role),
        content=message.content,
        created_at=message.created_at,
        agent_run_id=message.agent_run_id,
        decision_basis=decision_basis,
        pending_action_id=pending_action_id,
    )


@router.get("/sessions", response_model=Page[ChatSessionRead])
def list_sessions(
    user: CurrentUser,
    db: DBSession,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
) -> Page[ChatSessionRead]:
    conditions = [ChatSession.user_id == user.id]
    if cursor is not None:
        updated_raw, id_raw = decode_cursor(cursor, 2)
        if updated_raw is None or id_raw is None:
            raise ValidationError("updated_at/id must be present in the cursor")
        anchor = datetime.fromisoformat(updated_raw)
        row_id = uuid.UUID(id_raw)
        conditions.append(
            (ChatSession.updated_at < anchor)
            | ((ChatSession.updated_at == anchor) & (ChatSession.id < row_id))
        )
    stmt = (
        select(ChatSession)
        .where(*conditions)
        .order_by(ChatSession.updated_at.desc(), ChatSession.id.desc())
    )
    rows, next_cursor = keyset_page(
        db,
        stmt,
        limit=limit,
        after=true(),
        key_of=lambda row: (row.updated_at, str(row.id)),
    )
    return Page(
        items=[ChatSessionRead.model_validate(row) for row in rows],
        total=count_total(db, stmt) if cursor is None else None,
        limit=limit,
        offset=0,
        next_cursor=next_cursor,
    )


@router.get("/sessions/{session_id}", response_model=ChatSessionRead)
def get_session(session_id: uuid.UUID, user: CurrentUser, db: DBSession) -> ChatSessionRead:
    return ChatSessionRead.model_validate(_session_or_404(session_id, user, db))


@router.get("/sessions/{session_id}/messages", response_model=Page[ChatMessageRead])
def list_messages(
    session_id: uuid.UUID,
    user: CurrentUser,
    db: DBSession,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
) -> Page[ChatMessageRead]:
    _session_or_404(session_id, user, db)
    conditions = [
        ChatMessage.session_id == session_id,
        ChatMessage.user_id == user.id,
        ChatMessage.deleted_at.is_(None),
    ]
    # Messages page oldest-first so the chat view appends naturally.
    if cursor is not None:
        created_raw, id_raw = decode_cursor(cursor, 2)
        if created_raw is None or id_raw is None:
            raise ValidationError("created_at/id must be present in the cursor")
        anchor = datetime.fromisoformat(created_raw)
        row_id = uuid.UUID(id_raw)
        conditions.append(
            (ChatMessage.created_at > anchor)
            | ((ChatMessage.created_at == anchor) & (ChatMessage.id > row_id))
        )
    stmt = (
        select(ChatMessage)
        .where(*conditions)
        .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
    )
    rows, next_cursor = keyset_page(
        db,
        stmt,
        limit=limit,
        after=true(),
        key_of=lambda row: (row.created_at, str(row.id)),
    )
    return Page(
        items=[_message_read(db, row) for row in rows],
        total=count_total(db, stmt) if cursor is None else None,
        limit=limit,
        offset=0,
        next_cursor=next_cursor,
    )
