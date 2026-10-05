"""Independent data-lifecycle ledger tables (D-036 §8-8 / M5 A-draft §4).

Design constraint frozen by D-036: the ledger must survive deletion of the
``users`` row and must not let business queries recover a user identity from
it. Therefore every table here keys on the opaque ``users.owner_handle`` VALUE
with **no foreign key to users** and stores no email / user_id. ``users`` owns
the live ``data_generation``; operations snapshot the generation they were
accepted at so restore replays suppression and generations from this ledger
alone (A-draft §6), never from the users row or an old Redis dump.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from backend.models.enums import (
    CleanupItemAction,
    CleanupItemState,
    DataBarrierScope,
    DataBarrierState,
    DataOperationKind,
    DataOperationPhase,
    DataOperationStatus,
    sa_enum,
)


class DataOperation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One accepted export/deletion request (A-draft §4 DataOperation).

    202 semantics: a row here means "durably accepted", never "cleanup done".
    Idempotency key is (owner_handle, kind, client_request_id); same input
    returns the same operation, different input is the caller's 409
    (idempotency_conflict). ``version`` feeds the retry endpoint's
    expected_version optimistic concurrency (D-036 §8-3).
    """

    __tablename__ = "data_operations"
    __table_args__ = (
        UniqueConstraint(
            "owner_handle",
            "kind",
            "client_request_id",
            name="uq_data_operations_idem",
        ),
        Index("ix_data_operations_owner", "owner_handle"),
        Index("ix_data_operations_status", "status"),
    )

    owner_handle: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[DataOperationKind] = mapped_column(
        sa_enum(DataOperationKind, "data_operation_kind"), nullable=False
    )
    client_request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    # DeleteTarget as accepted (null for exports); snapshots are compared on
    # idempotent replay, so a same-key different-target replay is detectable.
    target: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[DataOperationStatus] = mapped_column(
        sa_enum(DataOperationStatus, "data_operation_status"),
        nullable=False,
        default=DataOperationStatus.QUEUED,
    )
    phase: Mapped[DataOperationPhase | None] = mapped_column(
        sa_enum(DataOperationPhase, "data_operation_phase"), nullable=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    data_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    progress_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outstanding_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # SafeError decomposition (A-draft §4): code + safe message + retryable,
    # never raw provider text or object keys.
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_retryable: Mapped[bool | None] = mapped_column(nullable=True)
    receipt_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DataCleanupItem(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Durable cleanup work queue (A-draft §2.5).

    The relational deletion transaction enqueues these rows in the SAME
    transaction; Redis only wakes the executor. Because membership lives in
    this table, a crash after a Redis pop can no longer lose an object key
    (the r1 failure mode in worker/enqueue.py SPOP). Executors claim rows with
    FOR UPDATE SKIP LOCKED (M4 lease pattern); failures walk the frozen
    backoff ladder 5/30/120/300/900s within a 24h automatic-retry window,
    then park as FAILED with a safe error summary.
    """

    __tablename__ = "data_cleanup_items"
    __table_args__ = (
        UniqueConstraint(
            "operation_id",
            "resource_type",
            "item_ref",
            "action",
            name="uq_data_cleanup_items_item",
        ),
        Index("ix_data_cleanup_items_claim", "state", "next_retry_at"),
        Index("ix_data_cleanup_items_operation", "operation_id"),
    )

    operation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("data_operations.id", ondelete="CASCADE"), nullable=False
    )
    # Denormalized so owner-scoped scans never need a join through operations.
    owner_handle: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False)
    # Executor-meaningful reference: storage object key, "table:pk" for
    # relational rows, or a Redis key pattern instance.
    item_ref: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[CleanupItemAction] = mapped_column(
        sa_enum(CleanupItemAction, "data_cleanup_action"), nullable=False
    )
    state: Mapped[CleanupItemState] = mapped_column(
        sa_enum(CleanupItemState, "data_cleanup_state"),
        nullable=False,
        default=CleanupItemState.PENDING,
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # RETRY_WAIT gate: null = immediately claimable; set by fail_cleanup_item
    # per the frozen backoff ladder.
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Safe summary only (SafeError semantics); no provider payloads or keys
    # beyond item_ref itself, which is the work reference, not content.
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class DataBarrier(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Owner barrier rows (A-draft §2.2).

    The confirm transaction takes row locks on the owner's barrier rows
    (lock_owner_barriers), registers the operation + cleanup items and bumps
    data_generation in ONE transaction. Rules frozen in the contract and
    enforced by services/data_lifecycle.release_barrier: FAILED never lifts a
    barrier; account barriers are never auto-released; source/memory barriers
    release only with a COMPLETED operation (target suppression persists
    separately, with the deletion slice).
    """

    __tablename__ = "data_barriers"
    __table_args__ = (Index("ix_data_barriers_owner_state", "owner_handle", "state"),)

    owner_handle: Mapped[str] = mapped_column(String(32), nullable=False)
    scope: Mapped[DataBarrierScope] = mapped_column(
        sa_enum(DataBarrierScope, "data_barrier_scope"), nullable=False
    )
    # source/memory: {"kind": ..., "ids": [...]}; account: null. Writers match
    # their target identity against this (assert_writable).
    target: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    state: Mapped[DataBarrierState] = mapped_column(
        sa_enum(DataBarrierState, "data_barrier_state"),
        nullable=False,
        default=DataBarrierState.ACTIVE,
    )
    raised_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    operation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("data_operations.id", ondelete="SET NULL"), nullable=True
    )
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
