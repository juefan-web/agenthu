"""Chat read face + send entry (D-034, M4-A1/A2).

Session/message listing with D-029 keyset pagination;
``decision_basis``/``pending_action_id`` on messages are JOIN projections
over ``agent_run_id`` (ruling A5 — no second stored copy). POST sessions /
messages (A2) create the user message plus a QUEUED run in one transaction
and hand execution to the worker; DELETEs land with the A3 retrieval slice
(deleted_at + FTS invalidation in the same transaction).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import cast

from fastapi import APIRouter, Query, status
from sqlalchemy import select, true

from backend.api.deps import CurrentUser, DBSession
from backend.core.errors import ConflictError, NotFoundError, ValidationError
from backend.models.agent import AgentRun, PendingAction
from backend.models.chat import ChatMessage, ChatSession
from backend.schemas.agent import DecisionBasis
from backend.schemas.chat import (
    ChatMessageRead,
    ChatMessageSend,
    ChatMessageSendResponse,
    ChatSessionCreate,
    ChatSessionRead,
    MessageRole,
)
from backend.schemas.common import Page
from backend.services.agent_runner import RUNNER_VERSION, TOOL_REGISTRY_VERSION, audit_run_queued
from backend.services.context_assembly import PROMPT_VERSION
from backend.services.pagination import count_total, decode_cursor, keyset_page
from backend.worker.queue import get_arq_pool

logger = logging.getLogger(__name__)

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


@router.post("/sessions", response_model=ChatSessionRead, status_code=status.HTTP_201_CREATED)
def create_session(
    payload: ChatSessionCreate,
    user: CurrentUser,
    db: DBSession,
) -> ChatSessionRead:
    """Create a session. ``client_request_id`` is accepted (frozen B1
    request shape) but carries no idempotency here — message-level
    ``client_message_id`` is the dedup key (ruling A2)."""

    session = ChatSession(user_id=user.id, title=(payload.title or "")[:120])
    db.add(session)
    db.flush()
    return ChatSessionRead.model_validate(session)


@router.post(
    "/sessions/{session_id}/messages",
    response_model=ChatMessageSendResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def send_message(
    session_id: uuid.UUID,
    payload: ChatMessageSend,
    user: CurrentUser,
    db: DBSession,
) -> ChatMessageSendResponse:
    """Create the user message + a QUEUED chat run in one transaction.

    Idempotency (ruling A2): ``(session_id, client_message_id)`` is unique,
    and the run's ``client_request_id`` derives server-side as
    ``chat:{session_id}:{client_message_id}`` — a lost-202 resend returns
    the SAME run/message pair (latest attempt under that operation key).
    Execution happens in the worker; the assistant message lands when the
    run reaches a terminal state.
    """

    _session_or_404(session_id, user, db)

    existing = db.scalar(
        select(ChatMessage).where(
            ChatMessage.session_id == session_id,
            ChatMessage.user_id == user.id,
            ChatMessage.client_message_id == payload.client_message_id,
        )
    )
    if existing is not None:
        run = db.scalar(
            select(AgentRun)
            .where(
                AgentRun.user_id == user.id,
                AgentRun.operation_key == f"chat:{session_id}:{payload.client_message_id}",
            )
            .order_by(AgentRun.attempt_no.desc())
            .limit(1)
        )
        # The dedup path must return a run id: the send transaction created
        # one with the message, so a missing row can only mean data loss.
        if run is None:
            if existing.agent_run_id is None:
                raise ConflictError("Dedup hit a message without its agent run")
            run_id: uuid.UUID = existing.agent_run_id
        else:
            run_id = run.id
        return ChatMessageSendResponse(run_id=run_id, user_message_id=existing.id)

    message = ChatMessage(
        session_id=session_id,
        user_id=user.id,
        role="user",
        content=payload.content,
        client_message_id=payload.client_message_id,
    )
    db.add(message)
    db.flush()

    # Deterministic title backfill: truncated first user message, no LLM.
    chat_session = db.get(ChatSession, session_id)
    if chat_session is not None and not chat_session.title:
        chat_session.title = payload.content[:120]

    operation_key = f"chat:{session_id}:{payload.client_message_id}"
    run = AgentRun(
        user_id=user.id,
        status="QUEUED",
        invocation_kind="chat",
        trigger_ref={"kind": "chat", "chat_message_id": str(message.id)},
        operation_key=operation_key,
        attempt_no=1,
        client_request_id=operation_key,
        runner_version=RUNNER_VERSION,
        tool_registry_version=TOOL_REGISTRY_VERSION,
        prompt_version=PROMPT_VERSION,
    )
    db.add(run)
    db.flush()
    audit_run_queued(db, run)
    db.commit()

    await _enqueue_run(run.id)
    db.refresh(message)
    db.refresh(run)
    return ChatMessageSendResponse(run_id=run.id, user_message_id=message.id)


async def _enqueue_run(run_id: uuid.UUID) -> None:
    """Best-effort worker enqueue; the cron sweep is the reliability net
    (claims any QUEUED run whose enqueue was lost)."""

    try:
        pool = await get_arq_pool()
        await pool.enqueue_job("execute_agent_run", str(run_id))
    except Exception:  # pragma: no cover - Redis down must not fail the 202
        logger.warning(
            "Run enqueue failed; cron sweep will pick it up",
            extra={"run_id": str(run_id)},
        )
