"""Pending action read face + mutation state machine (D-034, M4-A1/A2).

``active`` = the confirmation queue (PENDING/CONFIRMED/EXECUTING/
FAILED_RETRYABLE) keyed by (created_at, id) — ruling A3; ``history`` =
terminal rows plus the Level 3 auto-dispatch ledger, keyed by
(coalesce(finished_at, updated_at), id).

Mutations (confirm/ignore/retry, A2): optimistic ``expected_version``, a
client ``mutation_id`` whose settled response is cached (lost-HTTP resends
return the same body), PENDING-expiry converged lazily before any decision,
and dispatch through the atomic-claim executor — a racing worker can never
double-execute what the inline path already claimed.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Query
from sqlalchemy import func, select, true

from backend.api.deps import CurrentUser, DBSession
from backend.core.errors import ConflictError, NotFoundError, ValidationError
from backend.db.base import utcnow
from backend.models.agent import PendingAction
from backend.models.enums import AuditActor
from backend.schemas.agent import (
    PendingActionMutation,
    PendingActionRead,
    pending_action_read,
)
from backend.schemas.common import Page
from backend.services.agent_runner import (
    cached_mutation_response,
    dispatch_confirmed_action,
    store_mutation_response,
)
from backend.services.audit import record_audit
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
    action = _lock_or_404(db, action_id, user.id)
    _lazy_expire(db, action)
    return pending_action_read(action)


def _lock_or_404(db, action_id: uuid.UUID, user_id: uuid.UUID) -> PendingAction:
    action = db.execute(
        select(PendingAction)
        .where(PendingAction.id == action_id, PendingAction.user_id == user_id)
        .with_for_update()
    ).scalar_one_or_none()
    if action is None:
        raise NotFoundError("Pending action not found")
    return action


def _lazy_expire(db, action: PendingAction) -> bool:
    """Expiry converges from PENDING on the read/write paths too (§5.1);
    CONFIRMED never expires (ruling A1)."""

    if action.status == "PENDING" and action.expires_at <= utcnow():
        action.status = "EXPIRED"
        action.updated_at = utcnow()
        db.flush()
        record_audit(
            db,
            action="pending_action.expired",
            actor=AuditActor.SYSTEM.value,
            user_id=action.user_id,
            resource_type="pending_action",
            resource_id=str(action.id),
            details={"tool_name": action.tool_name, "status": "EXPIRED"},
        )
        return True
    return False


def _mutation_response(
    db,
    *,
    action: PendingAction,
    payload: PendingActionMutation,
    kind: str,
) -> PendingActionRead:
    read = pending_action_read(action)
    store_mutation_response(
        db,
        pending_action_id=action.id,
        user_id=action.user_id,
        mutation_id=payload.mutation_id,
        kind=kind,
        response=read.model_dump(mode="json"),
    )
    return read


async def _confirm(db, action: PendingAction, payload: PendingActionMutation) -> PendingActionRead:
    _lazy_expire(db, action)
    if action.status == "PENDING":
        if action.version != payload.expected_version:
            raise ConflictError(
                f"Version mismatch: expected {action.version} (current row version)"
            )
        action.status = "CONFIRMED"
        action.confirmed_at = utcnow()
        action.version += 1
        db.flush()
        record_audit(
            db,
            action="pending_action.confirmed",
            actor=AuditActor.USER.value,
            user_id=action.user_id,
            resource_type="pending_action",
            resource_id=str(action.id),
            details={"tool_name": action.tool_name, "status": "CONFIRMED"},
        )
        await dispatch_confirmed_action(db, action_id=action.id)
    elif action.status in ("CONFIRMED", "FAILED_RETRYABLE", "EXECUTING", "SUCCEEDED"):
        # Already advanced by an earlier confirmation: return the current
        # row without re-driving the state machine (contract §5.1). The
        # dispatch claim is atomic, so this can never double-execute.
        if action.status in ("CONFIRMED", "FAILED_RETRYABLE"):
            await dispatch_confirmed_action(db, action_id=action.id)
    else:
        raise ConflictError(
            f"Action in status {action.status} cannot be confirmed",
        )
    return _mutation_response(db, action=action, payload=payload, kind="confirm")


def _ignore(db, action: PendingAction, payload: PendingActionMutation) -> PendingActionRead:
    _lazy_expire(db, action)
    if action.status != "PENDING":
        raise ConflictError(f"Action in status {action.status} cannot be ignored")
    if action.version != payload.expected_version:
        raise ConflictError(f"Version mismatch: expected {action.version} (current row version)")
    action.status = "IGNORED"
    action.ignored_at = utcnow()
    action.version += 1
    db.flush()
    record_audit(
        db,
        action="pending_action.ignored",
        actor=AuditActor.USER.value,
        user_id=action.user_id,
        resource_type="pending_action",
        resource_id=str(action.id),
        details={"tool_name": action.tool_name, "status": "IGNORED"},
    )
    return _mutation_response(db, action=action, payload=payload, kind="ignore")


async def _retry(db, action: PendingAction, payload: PendingActionMutation) -> PendingActionRead:
    if action.status != "FAILED_RETRYABLE":
        raise ConflictError(
            f"Action in status {action.status} is not retryable "
            "(retry keeps the same args/hash/key — only FAILED_RETRYABLE)"
        )
    if action.version != payload.expected_version:
        raise ConflictError(f"Version mismatch: expected {action.version} (current row version)")
    action.status = "CONFIRMED"
    action.version += 1
    db.flush()
    record_audit(
        db,
        action="pending_action.retry",
        actor=AuditActor.USER.value,
        user_id=action.user_id,
        resource_type="pending_action",
        resource_id=str(action.id),
        details={"tool_name": action.tool_name, "attempt": action.attempt_count + 1},
    )
    await dispatch_confirmed_action(db, action_id=action.id)
    return _mutation_response(db, action=action, payload=payload, kind="retry")


@router.post("/{action_id}/confirm", response_model=PendingActionRead)
async def confirm_pending_action(
    action_id: uuid.UUID,
    payload: PendingActionMutation,
    user: CurrentUser,
    db: DBSession,
) -> PendingActionRead:
    cached = cached_mutation_response(
        db, pending_action_id=action_id, mutation_id=payload.mutation_id
    )
    if cached is not None:
        return PendingActionRead.model_validate(cached)
    action = _lock_or_404(db, action_id, user.id)
    result = await _confirm(db, action, payload)
    db.commit()
    return result


@router.post("/{action_id}/ignore", response_model=PendingActionRead)
def ignore_pending_action(
    action_id: uuid.UUID,
    payload: PendingActionMutation,
    user: CurrentUser,
    db: DBSession,
) -> PendingActionRead:
    cached = cached_mutation_response(
        db, pending_action_id=action_id, mutation_id=payload.mutation_id
    )
    if cached is not None:
        return PendingActionRead.model_validate(cached)
    action = _lock_or_404(db, action_id, user.id)
    result = _ignore(db, action, payload)
    db.commit()
    return result


@router.post("/{action_id}/retry", response_model=PendingActionRead)
async def retry_pending_action(
    action_id: uuid.UUID,
    payload: PendingActionMutation,
    user: CurrentUser,
    db: DBSession,
) -> PendingActionRead:
    cached = cached_mutation_response(
        db, pending_action_id=action_id, mutation_id=payload.mutation_id
    )
    if cached is not None:
        return PendingActionRead.model_validate(cached)
    action = _lock_or_404(db, action_id, user.id)
    result = await _retry(db, action, payload)
    db.commit()
    return result
