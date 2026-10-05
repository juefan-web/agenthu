"""Data-lifecycle ledger, barrier and generation primitives (D-036 §8-8).

This module is the durable substrate the deletion/export API (P0-3) sits on:
idempotent operation records, a transactional cleanup-item queue, owner
barriers and the ``data_generation`` counter. Nothing here is wired into
business write paths yet — P0-3 calls ``assert_writable`` at the entry and
final-write points listed in the A-draft §2.3 checklist; this slice ships the
primitives plus the rules frozen in the contract:

- the ledger keys on ``users.owner_handle`` with no FK, so deleting the users
  row cannot CASCADE it away and it never stores an identity (A-draft §4);
- failures walk the 5/30/120/300/900s backoff ladder inside a 24h automatic
  window, then park as FAILED (A-draft §2);
- FAILED never lifts a barrier; account barriers are never auto-released;
  source/memory barriers release only on a COMPLETED operation (§2.2).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from backend.db.base import utcnow
from backend.models.data_lifecycle import DataBarrier, DataCleanupItem, DataOperation
from backend.models.enums import (
    CleanupItemState,
    DataBarrierScope,
    DataBarrierState,
    DataOperationKind,
    DataOperationStatus,
)
from backend.models.user import User

#: Frozen automatic-retry backoff ladder (seconds), one step per retry
#: (A-draft §2): 5 attempts max, 24h total automatic window. A claim lease
#: bounds how long a crashed executor's hold delays re-claiming.
CLEANUP_BACKOFF_LADDER_S = (5, 30, 120, 300, 900)
CLEANUP_MAX_ATTEMPTS = len(CLEANUP_BACKOFF_LADDER_S)
CLEANUP_AUTO_RETRY_WINDOW = timedelta(hours=24)
CLEANUP_CLAIM_LEASE = timedelta(minutes=5)


class LifecycleError(Exception):
    """Base class for lifecycle primitive failures."""


class IdempotencyConflict(LifecycleError):
    """Same (owner, kind, client_request_id) replayed with different input.

    P0-3 maps this to 409 idempotency_conflict (A-draft §4).
    """


class BarrierConflict(LifecycleError):
    """A write hits an ACTIVE owner barrier (A-draft §2.2).

    P0-3 maps this per entry point (account deletion → 401/404 family;
    source/memory deletion scope → rejection without silent widening).
    """

    def __init__(self, barrier: DataBarrier) -> None:
        self.barrier = barrier
        super().__init__(f"active {barrier.scope.value} barrier blocks this write")


class GenerationStale(LifecycleError):
    """Observed generation no longer matches the live one (A-draft §2.3)."""


# --- owner handle / generation -------------------------------------------------


def owner_handle_of(session: Session, user_id: uuid.UUID) -> str:
    """Resolve the opaque ledger handle for a user (raises if missing)."""

    handle = session.scalar(select(User.owner_handle).where(User.id == user_id))
    if handle is None:
        raise LifecycleError(f"user {user_id} has no owner handle")
    return handle


def bump_data_generation(session: Session, user_id: uuid.UUID) -> int:
    """Atomically raise the user's data generation and return the new value.

    The row UPDATE takes the lock the confirm transaction holds while it
    registers the operation, enqueues cleanup items and raises the barrier —
    in-flight writers comparing generations serialize behind it.
    """

    new_generation = session.execute(
        update(User)
        .where(User.id == user_id)
        .values(data_generation=User.data_generation + 1)
        .returning(User.data_generation)
    ).scalar_one()
    return int(new_generation)


def assert_generation_current(
    session: Session, user_id: uuid.UUID, observed_generation: int
) -> None:
    """Reject work accepted under an older generation (final-write check)."""

    current = session.scalar(select(User.data_generation).where(User.id == user_id))
    if current is None:
        raise LifecycleError(f"user {user_id} not found")
    if int(current) != observed_generation:
        raise GenerationStale(f"data generation moved from {observed_generation} to {current}")


# --- operations ledger ---------------------------------------------------------


@dataclass(frozen=True)
class OperationRequest:
    """Input snapshot used for idempotency comparison on replay."""

    kind: DataOperationKind
    client_request_id: str
    target: dict | None
    data_generation: int


def get_or_create_operation(
    session: Session, owner_handle: str, request: OperationRequest
) -> tuple[DataOperation, bool]:
    """Idempotent operation accept (A-draft §4).

    Returns (operation, created). Same key + same input → the SAME row and
    ``created=False``; same key + different input → :class:`IdempotencyConflict`
    (never silently widens or re-runs). Callers run this inside the confirm
    transaction that also locks barriers and bumps the generation.
    """

    existing = session.scalar(
        select(DataOperation).where(
            DataOperation.owner_handle == owner_handle,
            DataOperation.kind == request.kind,
            DataOperation.client_request_id == request.client_request_id,
        )
    )
    if existing is not None:
        # Compared input is client-visible only (kind/key/target snapshot,
        # which carries the preview digest at P0-3). The server-side
        # generation snapshot is NOT part of the comparison: replaying the
        # same request after its own confirm bumped the generation must
        # return the same operation, not a false 409.
        if existing.target != request.target:
            raise IdempotencyConflict(
                f"client_request_id {request.client_request_id!r} already used with different input"
            )
        return existing, False
    operation = DataOperation(
        owner_handle=owner_handle,
        kind=request.kind,
        client_request_id=request.client_request_id,
        target=request.target,
        status=DataOperationStatus.QUEUED,
        data_generation=request.data_generation,
    )
    session.add(operation)
    session.flush()
    return operation, True


# --- durable cleanup queue -----------------------------------------------------


@dataclass(frozen=True)
class CleanupItemSpec:
    resource_type: str
    item_ref: str
    action: str


def enqueue_cleanup_items(
    session: Session,
    operation: DataOperation,
    specs: list[CleanupItemSpec],
) -> list[DataCleanupItem]:
    """Register cleanup work in the SAME transaction as the relational delete.

    Rows dedupe on (operation, resource_type, item_ref, action) — re-enqueueing
    an already-registered item is a no-op, and membership living here is what
    makes "Redis only wakes the executor" safe (A-draft §2.5: a crash after a
    Redis pop can no longer lose the object). Returns every item now
    registered for the given specs (pre-existing + newly inserted).
    """

    def _key(spec: CleanupItemSpec) -> tuple[str, str, str]:
        return (spec.resource_type, spec.item_ref, spec.action)

    registered_rows = session.execute(
        select(
            DataCleanupItem.id,
            DataCleanupItem.resource_type,
            DataCleanupItem.item_ref,
            DataCleanupItem.action,
        ).where(DataCleanupItem.operation_id == operation.id)
    ).all()
    existing_keys = {(r[1], r[2], str(r[3])) for r in registered_rows}
    for spec in dict.fromkeys(specs):  # de-dup the input, keep order
        if _key(spec) in existing_keys:
            continue
        session.add(
            DataCleanupItem(
                operation_id=operation.id,
                owner_handle=operation.owner_handle,
                resource_type=spec.resource_type,
                item_ref=spec.item_ref,
                action=spec.action,
                state=CleanupItemState.PENDING,
            )
        )
        existing_keys.add(_key(spec))
    session.flush()
    return list(
        session.scalars(select(DataCleanupItem).where(DataCleanupItem.operation_id == operation.id))
    )


def claim_cleanup_items(
    session: Session, *, limit: int = 100, now: datetime | None = None
) -> list[DataCleanupItem]:
    """Claim due items FOR UPDATE SKIP LOCKED (M4 lease pattern).

    Due = PENDING past its backoff gate, or CLAIMED whose lease lapsed (a
    crashed executor self-heals on a later pass). Two executors never hold
    the same item; claiming increments ``attempts`` so a crashed attempt
    still counts against the frozen ladder.
    """

    if now is None:
        now = utcnow()
    lease_deadline = now - CLEANUP_CLAIM_LEASE
    rows = (
        session.execute(
            select(DataCleanupItem)
            .where(
                or_(
                    and_(
                        DataCleanupItem.state == CleanupItemState.PENDING,
                        or_(
                            DataCleanupItem.next_retry_at.is_(None),
                            DataCleanupItem.next_retry_at <= now,
                        ),
                    ),
                    and_(
                        DataCleanupItem.state == CleanupItemState.CLAIMED,
                        DataCleanupItem.claimed_at.is_not(None),
                        DataCleanupItem.claimed_at <= lease_deadline,
                    ),
                )
            )
            .order_by(DataCleanupItem.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        .scalars()
        .all()
    )
    claimed: list[DataCleanupItem] = []
    for item in rows:
        item.state = CleanupItemState.CLAIMED
        item.claimed_at = now
        item.attempts += 1
        claimed.append(item)
    session.flush()
    return claimed


def complete_cleanup_item(
    session: Session, item_id: uuid.UUID, *, now: datetime | None = None
) -> DataCleanupItem | None:
    """Mark a claimed item DONE; ``None`` means it was not claimable."""

    item = session.get(DataCleanupItem, item_id)
    if item is None or item.state != CleanupItemState.CLAIMED:
        return None
    if now is None:
        now = utcnow()
    item.state = CleanupItemState.DONE
    item.done_at = now
    item.next_retry_at = None
    item.last_error = None
    session.flush()
    return item


def fail_cleanup_item(
    session: Session,
    item_id: uuid.UUID,
    *,
    error_summary: str,
    now: datetime | None = None,
) -> DataCleanupItem:
    """Walk the frozen backoff ladder; park as FAILED when exhausted.

    Ladder (A-draft §2): one 5/30/120/300/900s step per retry, at most 5
    automatic attempts inside a 24h window from item creation. FAILED keeps
    the safe error summary for audit — it never silently disappears.
    """

    item = session.get(DataCleanupItem, item_id)
    if item is None:
        raise LifecycleError(f"cleanup item {item_id} not found")
    if now is None:
        now = utcnow()
    item.last_error = error_summary
    ladder_exhausted = item.attempts >= CLEANUP_MAX_ATTEMPTS
    window_exhausted = now - item.created_at >= CLEANUP_AUTO_RETRY_WINDOW
    if ladder_exhausted or window_exhausted:
        item.state = CleanupItemState.FAILED
        item.next_retry_at = None
    else:
        item.state = CleanupItemState.PENDING
        item.next_retry_at = now + timedelta(
            seconds=CLEANUP_BACKOFF_LADDER_S[min(item.attempts - 1, CLEANUP_MAX_ATTEMPTS - 1)]
        )
    session.flush()
    return item


# --- owner barriers ------------------------------------------------------------


def raise_barrier(
    session: Session,
    *,
    owner_handle: str,
    scope: DataBarrierScope,
    raised_generation: int,
    target: dict | None = None,
    operation_id: uuid.UUID | None = None,
) -> DataBarrier:
    """Insert an ACTIVE barrier (call inside the confirm transaction)."""

    barrier = DataBarrier(
        owner_handle=owner_handle,
        scope=scope,
        target=target,
        state=DataBarrierState.ACTIVE,
        raised_generation=raised_generation,
        operation_id=operation_id,
    )
    session.add(barrier)
    session.flush()
    return barrier


def lock_owner_barriers(session: Session, owner_handle: str) -> list[DataBarrier]:
    """Row-lock every barrier of an owner (confirm-transaction fence).

    SELECT ... FOR UPDATE in the confirm transaction serializes concurrent
    destructive confirms for the same owner against barrier checks.
    """

    return list(
        session.execute(
            select(DataBarrier)
            .where(DataBarrier.owner_handle == owner_handle)
            .order_by(DataBarrier.created_at)
            .with_for_update()
        ).scalars()
    )


def matching_barrier(
    session: Session,
    owner_handle: str,
    *,
    scope: DataBarrierScope,
    target_ids: set[str] | None = None,
) -> DataBarrier | None:
    """The ACTIVE barrier this write conflicts with, or None.

    account scope conflicts with EVERYTHING for the owner; source/memory
    barriers conflict when the write touches one of the barred target ids
    (target identity matching per family arrives with the P0-3 registry;
    here the caller passes the ids it is about to write).
    """

    barriers = session.scalars(
        select(DataBarrier).where(
            DataBarrier.owner_handle == owner_handle,
            DataBarrier.state == DataBarrierState.ACTIVE,
        )
    )
    for barrier in barriers:
        if barrier.scope == DataBarrierScope.ACCOUNT and scope is not None:
            return barrier
        if barrier.scope == scope and target_ids is not None:
            barred = {str(value) for value in (barrier.target or {}).get("ids", [])}
            if barred & target_ids:
                return barrier
    return None


def assert_writable(
    session: Session,
    *,
    owner_handle: str,
    scope: DataBarrierScope,
    target_ids: set[str] | None = None,
    observed_generation: int | None = None,
    user_id: uuid.UUID | None = None,
) -> None:
    """Entry / final-write check primitive (A-draft §2.3; wired by P0-3).

    Raises :class:`BarrierConflict` when an ACTIVE barrier covers the write
    and :class:`GenerationStale` when in-flight work carries an older
    generation than the live one.
    """

    barrier = matching_barrier(session, owner_handle, scope=scope, target_ids=target_ids)
    if barrier is not None:
        raise BarrierConflict(barrier)
    if observed_generation is not None and user_id is not None:
        assert_generation_current(session, user_id, observed_generation)


def release_barrier(
    session: Session,
    barrier_id: uuid.UUID,
    *,
    completed_operation: DataOperation,
    now: datetime | None = None,
) -> DataBarrier:
    """Release a source/memory barrier, only against a COMPLETED operation.

    Frozen rules (A-draft §2.2): FAILED (or any non-COMPLETED status) never
    releases a barrier; account barriers are never auto-released — they lift
    only with the account itself. Target suppression outlives the barrier and
    is tracked separately with the deletion slice.
    """

    barrier = session.get(DataBarrier, barrier_id)
    if barrier is None:
        raise LifecycleError(f"barrier {barrier_id} not found")
    if barrier.scope == DataBarrierScope.ACCOUNT:
        raise LifecycleError("account barriers are never auto-released")
    if completed_operation.status != DataOperationStatus.COMPLETED:
        raise LifecycleError("only a COMPLETED operation may release a source/memory barrier")
    if barrier.state != DataBarrierState.ACTIVE:
        raise LifecycleError(f"barrier {barrier_id} is not ACTIVE")
    if now is None:
        now = utcnow()
    barrier.state = DataBarrierState.RELEASED
    barrier.released_at = now
    session.flush()
    return barrier
