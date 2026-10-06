"""Chat read face + send/delete/search entries (D-034, M4-A1/A2/A3; D-035).

Session/message listing with D-029 keyset pagination;
``decision_basis``/``pending_action_id`` on messages are JOIN projections
over ``agent_run_id`` (ruling A5 — no second stored copy). POST sessions /
messages (A2) create the user message plus a QUEUED run in one transaction
and hand execution to the worker. A3 adds the DELETEs (soft, idempotent-204
like the grant revoke; a session archive cascades message soft-deletes in
the same transaction so retrieval eligibility drops atomically). D-035
collapses search into ONE global face — ``GET /chat/search`` with optional
``session_id`` scoping (the A3 in-session sub-path never shipped a
consumer and is removed) — with pg_trgm-accelerated substring matching
(sub-3-character queries degrade to an unindexed but correct filter,
D-034) and per-hit session titles for one-render deep links.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import cast

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import select, true, update

from backend.api.deps import CurrentUser, DBSession
from backend.core.errors import ConflictError, NotFoundError, ValidationError
from backend.db.base import utcnow
from backend.models.agent import AgentRun, PendingAction
from backend.models.chat import ChatMessage, ChatSession
from backend.models.enums import DataBarrierScope
from backend.schemas.agent import DecisionBasis
from backend.schemas.chat import (
    ChatMessageRead,
    ChatMessageSend,
    ChatMessageSendResponse,
    ChatSearchItem,
    ChatSessionCreate,
    ChatSessionRead,
    MessageRole,
)
from backend.schemas.common import Page
from backend.services.agent_runner import RUNNER_VERSION, TOOL_REGISTRY_VERSION, audit_run_queued
from backend.services.context_assembly import PROMPT_VERSION
from backend.services.pagination import count_total, decode_cursor, keyset_page
from backend.services.reference_invalidation import invalidate_chat_message_references
from backend.services.write_guards import assert_write_allowed
from backend.worker.queue import get_arq_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


def chat_operation_key(session_id: uuid.UUID, client_message_id: str) -> str:
    """Ruling-A2 client_request_id formula — one definition for the dedup
    lookup and the run creation (202 review note: no duplicated literal)."""

    return f"chat:{session_id}:{client_message_id}"


def _session_or_404(session_id: uuid.UUID, user, db) -> ChatSession:
    """Read/send face lookup: an archived session is gone from the user's
    view (DELETE is idempotent-204 and uses its own unfiltered lookup)."""

    row = db.scalar(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == user.id,
            ChatSession.archived_at.is_(None),
        )
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
        session_id=message.session_id,
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
    conditions = [ChatSession.user_id == user.id, ChatSession.archived_at.is_(None)]
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

    # Entry guard (A-draft §2.3): writing into a session that is itself a
    # deletion target must fail closed while the barrier is up — the message
    # would die with the executor's relational delete anyway, and blocking
    # here keeps the client from queueing into a dying conversation.
    assert_write_allowed(
        db, user_id=user.id, scope=DataBarrierScope.SOURCE, target_ids={str(session_id)}
    )

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
                AgentRun.operation_key == chat_operation_key(session_id, payload.client_message_id),
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

    operation_key = chat_operation_key(session_id, payload.client_message_id)
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


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(session_id: uuid.UUID, user: CurrentUser, db: DBSession) -> Response:
    """Archive the session and soft-delete its live messages in ONE
    transaction (A3): retrieval eligibility (reads, search, agent history
    faces) drops atomically with the user-visible deletion. Idempotent-204
    like the grant revoke; rows remain for audit lineage — the runs and
    pending actions that cite these messages keep resolving."""

    session = db.scalar(
        select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == user.id)
    )
    if session is None:
        raise NotFoundError("Chat session not found")
    if session.archived_at is None:
        now = utcnow()
        session.archived_at = now
        session.updated_at = now
        live_ids = set(
            db.scalars(
                select(ChatMessage.id).where(
                    ChatMessage.session_id == session_id,
                    ChatMessage.user_id == user.id,
                    ChatMessage.deleted_at.is_(None),
                )
            )
        )
        db.execute(
            update(ChatMessage)
            .where(
                ChatMessage.session_id == session_id,
                ChatMessage.user_id == user.id,
                ChatMessage.deleted_at.is_(None),
            )
            .values(deleted_at=now)
        )
        # B contract §5: references citing the cascaded messages flip to
        # source_deleted in the same transaction, not on next render.
        invalidate_chat_message_references(db, user_id=user.id, message_ids=live_ids)
        db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/messages/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_message(message_id: uuid.UUID, user: CurrentUser, db: DBSession) -> Response:
    """Soft-delete one message; reads and search exclude it from this
    transaction on (no separate FTS index to invalidate — eligibility is a
    WHERE clause over ``deleted_at``). Idempotent-204."""

    message = db.scalar(
        select(ChatMessage).where(
            ChatMessage.id == message_id,
            ChatMessage.user_id == user.id,
        )
    )
    if message is None:
        raise NotFoundError("Chat message not found")
    if message.deleted_at is None:
        message.deleted_at = utcnow()
        # B contract §5: stored references citing this message flip to
        # source_deleted atomically with the deletion.
        invalidate_chat_message_references(db, user_id=user.id, message_ids={message.id})
        db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/search", response_model=Page[ChatSearchItem])
def search_chat(
    user: CurrentUser,
    db: DBSession,
    q: str = Query(min_length=1, max_length=200),
    session_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
) -> Page[ChatSearchItem]:
    """Cross-session chat search (D-035): ONE retrieval face over the
    whole history, optionally scoped to a single live session via
    ``session_id`` (unknown / other-user's / archived sessions are a 404,
    the same discipline as the message flow — this replaces A3's in-session
    sub-path, which never shipped a consumer).

    Matching is A3-identical: a case-insensitive literal substring filter
    (``%needle%`` with autoescaped wildcards). The pg_trgm GIN index
    accelerates needles of 3+ characters; shorter needles form no trigram
    and degrade to an unindexed filter that still returns correct results.
    Results are newest-first on the same ``(created_at, id)`` keyset as the
    session listing, so pagination stays stable across edits. Soft-deleted
    messages and archived sessions never match. Each hit carries its
    session's CURRENT title so the client renders "title · time" and
    deep-links without a second fetch.
    """

    if session_id is not None:
        _session_or_404(session_id, user, db)
        scope = ChatMessage.session_id == session_id
    else:
        # Global scope: the user's live (non-archived) sessions only. A
        # subquery (not a join) keeps the P0 isolation invariant — every
        # message filter carries user_id on its own table.
        scope = ChatMessage.session_id.in_(
            select(ChatSession.id).where(
                ChatSession.user_id == user.id,
                ChatSession.archived_at.is_(None),
            )
        )
    needle = q.strip()
    if not needle:
        raise ValidationError("q must contain non-whitespace characters")
    conditions = [
        ChatMessage.user_id == user.id,
        ChatMessage.deleted_at.is_(None),
        ChatMessage.content.icontains(needle, autoescape=True),
        scope,
    ]
    if cursor is not None:
        created_raw, id_raw = decode_cursor(cursor, 2)
        if created_raw is None or id_raw is None:
            raise ValidationError("created_at/id must be present in the cursor")
        anchor = datetime.fromisoformat(created_raw)
        row_id = uuid.UUID(id_raw)
        conditions.append(
            (ChatMessage.created_at < anchor)
            | ((ChatMessage.created_at == anchor) & (ChatMessage.id < row_id))
        )
    stmt = (
        select(ChatMessage)
        .where(*conditions)
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
    )
    rows, next_cursor = keyset_page(
        db,
        stmt,
        limit=limit,
        after=true(),
        key_of=lambda row: (row.created_at, str(row.id)),
    )
    titles: dict[uuid.UUID, str] = {}
    if rows:
        titles = dict(
            db.execute(
                select(ChatSession.id, ChatSession.title).where(
                    ChatSession.id.in_({row.session_id for row in rows})
                )
            ).all()
        )
    items = [
        ChatSearchItem(
            **_message_read(db, row).model_dump(),
            session_title=titles[row.session_id],
        )
        for row in rows
    ]
    return Page(
        items=items,
        total=count_total(db, stmt) if cursor is None else None,
        limit=limit,
        offset=0,
        next_cursor=next_cursor,
    )


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
