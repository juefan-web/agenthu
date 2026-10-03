"""Pending action read face (D-034, M4-A1).

``active`` = the confirmation queue (PENDING/CONFIRMED/EXECUTING/
FAILED_RETRYABLE) keyed by (created_at, id) — ruling A3; ``history`` =
terminal rows plus the Level 3 auto-dispatch ledger, keyed by
(coalesce(finished_at, updated_at), id). Mutations (confirm/ignore/retry)
land with the A2 state machine, not this slice.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Query
from sqlalchemy import func, select, true

from backend.api.deps import CurrentUser, DBSession
from backend.core.errors import NotFoundError, ValidationError
from backend.models.agent import PendingAction
from backend.schemas.agent import PendingActionRead, pending_action_read
from backend.schemas.common import Page
from backend.services.pagination import count_total, decode_cursor, keyset_page

router = APIRouter(prefix="/pending-actions", tags=["agent"])

ACTIVE_STATUSES = ("PENDING", "CONFIRMED", "EXECUTING", "FAILED_RETRYABLE")
HISTORY_STATUSES = ("SUCCEEDED", "FAILED", "IGNORED", "EXPIRED")


def _history_key(row: PendingAction) -> datetime:
    return row.finished_at or row.updated_at


def _history_key_column():
    return func.coalesce(PendingAction.finished_at, PendingAction.updated_at)


def _strictly_after(cursor: str, key_column, id_column, parse_key):
    key_raw, id_raw = decode_cursor(cursor, 2)
    if key_raw is None or id_raw is None:
        raise ValidationError("cursor must carry both sort-key parts")
    return (key_column < parse_key(key_raw)) | (
        (key_column == parse_key(key_raw)) & (id_column < uuid.UUID(id_raw))
    )


@router.get("", response_model=Page[PendingActionRead])
def list_pending_actions(
    user: CurrentUser,
    db: DBSession,
    status: str = Query(default="active", pattern="^(active|history)$"),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
) -> Page[PendingActionRead]:
    if status == "active":
        conditions = [
            PendingAction.user_id == user.id,
            PendingAction.status.in_(ACTIVE_STATUSES),
        ]
        order = (PendingAction.created_at.desc(), PendingAction.id.desc())
        if cursor is not None:
            conditions.append(
                _strictly_after(
                    cursor,
                    PendingAction.created_at,
                    PendingAction.id,
                    datetime.fromisoformat,
                )
            )

        def key_of(row: PendingAction) -> tuple[datetime, str]:
            return row.created_at, str(row.id)

    else:
        key_column = _history_key_column()
        conditions = [
            PendingAction.user_id == user.id,
            PendingAction.status.in_(HISTORY_STATUSES),
        ]
        order = (key_column.desc(), PendingAction.id.desc())
        if cursor is not None:
            conditions.append(
                _strictly_after(cursor, key_column, PendingAction.id, datetime.fromisoformat)
            )

        def key_of(row: PendingAction) -> tuple[datetime, str]:
            return _history_key(row), str(row.id)

    stmt = select(PendingAction).where(*conditions).order_by(*order)
    rows, next_cursor = keyset_page(db, stmt, limit=limit, after=true(), key_of=key_of)
    return Page(
        items=[pending_action_read(row) for row in rows],
        # D-029: cursorless first page keeps the real COUNT.
        total=count_total(db, stmt) if cursor is None else None,
        limit=limit,
        offset=0,
        next_cursor=next_cursor,
    )


@router.get("/{action_id}", response_model=PendingActionRead)
def get_pending_action(action_id: uuid.UUID, user: CurrentUser, db: DBSession) -> PendingActionRead:
    action = db.scalar(
        select(PendingAction).where(PendingAction.id == action_id, PendingAction.user_id == user.id)
    )
    if action is None:
        raise NotFoundError("Pending action not found")
    return pending_action_read(action)
