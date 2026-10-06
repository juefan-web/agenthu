"""Durable object-deletion ledger for the plain file-delete path (§2.5).

The D-033 delete order keeps relational deletion transactional and the
object delete best-effort. P0-3 slice 3 replaces the best-effort Redis
marker (SADD/SPOP — a destructive pop that loses keys on a crash) with a
work row registered in the SAME transaction as the relational delete:
membership lives in the database, the worker cron claims due rows with the
M4 lease pattern, and success deletes the row. Redis no longer
participates in this flow at all — the cron's cadence is the wake.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.orm import Session

from backend.db.base import utcnow
from backend.models.data_lifecycle import StorageOrphanKey
from backend.models.enums import CleanupItemState
from backend.services.data_lifecycle import (
    CLEANUP_BACKOFF_LADDER_S,
    CLEANUP_CLAIM_LEASE,
    CLEANUP_MAX_ATTEMPTS,
)

#: Same ladder/lease shape as data_cleanup_items (frozen §2 values); a
#: FAILED row parks with its safe summary for operator follow-up instead
#: of retrying forever.
ORPHAN_MAX_ATTEMPTS = CLEANUP_MAX_ATTEMPTS


def register_storage_orphan(session: Session, storage_key: str) -> None:
    """Record the pending object delete in the caller's transaction.

    Call this BEFORE the commit that deletes the relational rows: the work
    record and the row deletion become atomic, so a crash anywhere after
    that commit leaves a claimable marker. Idempotent — a key is only ever
    registered once (keys embed a uuid and are never reused).
    """

    existing = session.scalar(
        select(StorageOrphanKey.id).where(StorageOrphanKey.storage_key == storage_key)
    )
    if existing is not None:
        return
    session.add(StorageOrphanKey(storage_key=storage_key, state=CleanupItemState.PENDING))
    session.flush()


def release_storage_orphan(session: Session, storage_key: str) -> None:
    """Drop the work row once the object delete is confirmed (or the key
    demonstrably belongs to a live row — keys are never reused, so that
    marker would otherwise loop forever)."""

    session.execute(delete(StorageOrphanKey).where(StorageOrphanKey.storage_key == storage_key))


def claim_due_storage_orphans(
    session: Session, *, limit: int = 100, now: datetime | None = None
) -> list[StorageOrphanKey]:
    """Claim due rows FOR UPDATE SKIP LOCKED (M4 lease pattern).

    Due = PENDING past its backoff gate, or CLAIMED whose lease lapsed.
    Claiming increments ``attempts`` so a crashed try still counts against
    the ladder; two workers never hold the same key.
    """

    if now is None:
        now = utcnow()
    lease_deadline = now - CLEANUP_CLAIM_LEASE
    rows = (
        session.execute(
            select(StorageOrphanKey)
            .where(
                or_(
                    and_(
                        StorageOrphanKey.state == CleanupItemState.PENDING,
                        or_(
                            StorageOrphanKey.next_retry_at.is_(None),
                            StorageOrphanKey.next_retry_at <= now,
                        ),
                    ),
                    and_(
                        StorageOrphanKey.state == CleanupItemState.CLAIMED,
                        StorageOrphanKey.claimed_at.is_not(None),
                        StorageOrphanKey.claimed_at <= lease_deadline,
                    ),
                )
            )
            .order_by(StorageOrphanKey.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        .scalars()
        .all()
    )
    for row in rows:
        row.state = CleanupItemState.CLAIMED
        row.claimed_at = now
        row.attempts += 1
    session.flush()
    return list(rows)


def fail_storage_orphan(
    session: Session,
    orphan_id: uuid.UUID,
    *,
    error_summary: str,
    now: datetime | None = None,
) -> StorageOrphanKey:
    """Walk the frozen backoff ladder; park as FAILED when exhausted."""

    row = session.get(StorageOrphanKey, orphan_id)
    if row is None:
        raise ValueError(f"storage orphan {orphan_id} not found")
    if now is None:
        now = utcnow()
    row.last_error = error_summary
    if row.attempts >= ORPHAN_MAX_ATTEMPTS:
        row.state = CleanupItemState.FAILED
        row.next_retry_at = None
    else:
        row.state = CleanupItemState.PENDING
        row.next_retry_at = now + timedelta(
            seconds=CLEANUP_BACKOFF_LADDER_S[min(row.attempts - 1, ORPHAN_MAX_ATTEMPTS - 1)]
        )
    session.flush()
    return row
