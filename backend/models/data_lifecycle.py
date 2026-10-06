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
    # The preview digest this confirmation was bound to; replay comparison is
    # (key, preview_digest) so a same-key different-preview resend is a 409.
    preview_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Exact closure snapshot at accept time: {resource_type: {"delete_ids":
    # [...], "recompute_ids": [...]}} plus "object_keys". The slice-2 executor
    # deletes by these ids, so previews never need to be recomputed later.
    impact: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # SHA-256 of the canonical confirm request body (D-036 §8-2): the recover
    # path's high-entropy second factor, transitively content-binding because
    # the body carries preview_digest. Null for exports.
    request_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # The only export input beyond the idempotency key; replay comparison
    # covers it (same key + different include_files is an idempotency 409).
    export_include_files: Mapped[bool | None] = mapped_column(nullable=True)
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
    # Action parameters the executor needs beyond the ref: for scoped
    # relational deletes the exact row ids ({"ids": [...]}); account deletes
    # can omit it (owner-scoped sweep).
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
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


class DataPreview(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A persisted preview (A-draft §2.1): 10-minute, digest-bound.

    The digest binds user, target, graph_version, data_generation, the exact
    impact sets AND per-row content versions (updated_at) — not row counts,
    so any drift between preview and confirm is a 409 preview_stale instead
    of a silent scope change. Unlike the ledger tables this one is plain
    user data: transient, 10-minute TTL, cascade with the account.
    """

    __tablename__ = "data_previews"
    __table_args__ = (Index("ix_data_previews_user_expires", "user_id", "expires_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    target: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    graph_version: Mapped[str] = mapped_column(String(64), nullable=False)
    data_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    preview_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    effects: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    limitations: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DataReceipt(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """The 90-day recovery receipt for an account deletion (A-draft §4).

    Ledger rules apply (owner_handle VALUE, no users FK): the receipt must
    outlive the users row. Only the SHA-256 digest of the capability token
    is stored — the token itself is returned exactly once, on the accepting
    202, and never re-issued (lost tokens go through the recover path).
    """

    __tablename__ = "data_receipts"

    operation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("data_operations.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    owner_handle: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    capability_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Short-lived re-delivery cache for a lost first 202 (A-draft §4): the
    # capability encrypted under a per-receipt nonce with an HMAC-SHA256
    # keystream derived from the server secret; one use, 10 minutes, then
    # it can never be re-delivered (recover outside the window is a 404).
    delivery_nonce: Mapped[str | None] = mapped_column(String(64), nullable=True)
    delivery_ciphertext: Mapped[str | None] = mapped_column(String(256), nullable=True)
    delivery_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class DataSuppression(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Owner-scoped upstream suppression (A-draft §2.6).

    A deleted source must not resurrect under a fresh client_event_id: the
    upstream identity is HMAC'd with the server secret (no title/content),
    kept until explicit re-consent or account deletion, and stored in the
    same value-keyed, no-users-FK ledger shape so restore replays it from
    this table alone.
    """

    __tablename__ = "data_suppressions"
    __table_args__ = (
        UniqueConstraint(
            "owner_handle", "source_kind", "upstream_hmac", name="uq_data_suppressions_key"
        ),
    )

    owner_handle: Mapped[str] = mapped_column(String(32), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    upstream_hmac: Mapped[str] = mapped_column(String(64), nullable=False)
    raised_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StorageOrphanKey(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Durable object-deletion work record (A-draft §2.5; P0-3 slice 3).

    The plain file-delete path (D-033 §5 order) registers the object key in
    the SAME transaction as the relational delete; the post-commit object
    delete removes the row on success. Membership therefore never leaves
    the database — the r1 failure mode (a crash after the destructive Redis
    SPOP forgetting the object) is structurally gone. State machine reuses
    the cleanup-item states (PENDING/CLAIMED/DONE/FAILED — the DONE value
    exists for enum symmetry; success DELETES the row, outbox-style).
    Lifecycle operations keep their own queue (data_cleanup_items); this
    table is the same pattern for the non-operation delete path.
    """

    __tablename__ = "storage_orphan_keys"
    __table_args__ = (
        UniqueConstraint("storage_key", name="uq_storage_orphan_keys_key"),
        Index("ix_storage_orphan_keys_due", "state", "next_retry_at"),
    )

    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[CleanupItemState] = mapped_column(
        sa_enum(CleanupItemState, "data_cleanup_state"),
        nullable=False,
        default=CleanupItemState.PENDING,
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Safe summary only; the key itself is the work reference, not content.
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
