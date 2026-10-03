"""Agent run read face (D-034, M4-A1).

Level 0 surface for the "why" panel and audit review: list/get with the
D-029 events-style keyset pagination (``Page.next_cursor``). The response
never carries prompts, chat/material originals, tool argument bodies or
chain-of-thought — the audit-join condition (review point 6) is met by
``tool_calls[]`` plus ``pending_action_ids``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import cast

from fastapi import APIRouter, Query
from sqlalchemy import and_, or_, select, true

from backend.api.deps import CurrentUser, DBSession
from backend.core.errors import NotFoundError, ValidationError
from backend.models.agent import AgentRun, PendingAction
from backend.schemas.agent import (
    AgentRunRead,
    AgentRunToolCallRead,
    DecisionBasis,
    InvocationKind,
    ProviderInfo,
    RunFailure,
    RunResult,
    RunStatus,
    RunUsage,
    TriggerRef,
)
from backend.schemas.common import Page
from backend.services.pagination import count_total, decode_cursor, keyset_page

router = APIRouter(prefix="/agent/runs", tags=["agent"])


def _tool_call_reads(tool_calls: list) -> list[AgentRunToolCallRead]:
    return [
        AgentRunToolCallRead(
            call_id=call.get("call_id", ""),
            tool_name=call.get("tool_name", ""),
            tool_version=call.get("tool_version", ""),
            status=call.get("status", ""),
            started_at=call.get("started_at"),
            ended_at=call.get("ended_at"),
            error_code=call.get("error_code"),
        )
        for call in tool_calls
        if isinstance(call, dict)
    ]


def _pending_action_ids(db, run_id: uuid.UUID, user_id: uuid.UUID) -> list[str]:
    stmt = select(PendingAction.id).where(
        PendingAction.agent_run_id == run_id, PendingAction.user_id == user_id
    )
    return [str(row) for row in db.scalars(stmt)]


def agent_run_read(db, run: AgentRun) -> AgentRunRead:
    return AgentRunRead(
        id=run.id,
        status=cast(RunStatus, run.status),
        invocation_kind=cast(InvocationKind, run.invocation_kind),
        trigger_ref=TriggerRef.model_validate(run.trigger_ref or {"kind": ""}),
        provider=ProviderInfo.model_validate(
            run.provider or {"name": "", "model": "", "capability": "none"}
        ),
        created_at=run.created_at,
        updated_at=run.updated_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        tool_calls=_tool_call_reads(run.tool_calls),
        decision_basis=DecisionBasis.model_validate(run.decision_basis)
        if run.decision_basis
        else None,
        pending_action_ids=_pending_action_ids(db, run.id, run.user_id),
        usage=RunUsage.model_validate(run.usage) if run.usage else None,
        result=RunResult.model_validate(run.result) if run.result else None,
        failure=RunFailure.model_validate(run.failure) if run.failure else None,
    )


def _keyset_conditions(cursor: str | None, created_col, id_col):
    """Strictly-after predicate for the (created_at DESC, id DESC) keyset."""

    if cursor is None:
        return []
    created_raw, id_raw = decode_cursor(cursor, 2)
    if created_raw is None or id_raw is None:
        raise ValidationError("created_at/id must be present in the cursor")
    created = datetime.fromisoformat(created_raw)
    row_id = uuid.UUID(id_raw)
    return [
        or_(
            created_col < created,
            and_(created_col == created, id_col < row_id),
        )
    ]


@router.get("", response_model=Page[AgentRunRead])
def list_runs(
    user: CurrentUser,
    db: DBSession,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
) -> Page[AgentRunRead]:
    conditions = [
        AgentRun.user_id == user.id,
        *_keyset_conditions(cursor, AgentRun.created_at, AgentRun.id),
    ]
    stmt = (
        select(AgentRun).where(*conditions).order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
    )
    rows, next_cursor = keyset_page(
        db,
        stmt,
        limit=limit,
        after=true(),
        key_of=lambda row: (row.created_at, str(row.id)),
    )
    return Page(
        items=[agent_run_read(db, row) for row in rows],
        # D-029: the first (cursorless) page keeps the real COUNT, cursor
        # pages skip it.
        total=count_total(db, stmt) if cursor is None else None,
        limit=limit,
        offset=0,
        next_cursor=next_cursor,
    )


@router.get("/{run_id}", response_model=AgentRunRead)
def get_run(run_id: uuid.UUID, user: CurrentUser, db: DBSession) -> AgentRunRead:
    run = db.scalar(select(AgentRun).where(AgentRun.id == run_id, AgentRun.user_id == user.id))
    if run is None:
        raise NotFoundError("Agent run not found")
    return agent_run_read(db, run)
