"""Preview and confirmation transactions for /v1/data (P0-3 slice 1).

confirm_deletion runs the whole A-draft §2.2 accept transaction: idempotent
replay first (a replay must return the same operation even after the preview
row expired), preview staleness against the FULL digest (graph version +
generation + impact sets + content versions — anything moved is a
preview_stale 409, never a silent scope change), in-progress-scope check,
then the users-row lock (bump_data_generation) that serializes concurrent
same-key confirms (B carry ① on #70), barrier raise, cleanup-item
registration, account deactivation with grant/consent revocation, source
suppression and the one-time receipt capability.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.core.errors import ConflictError, NotFoundError
from backend.db.base import utcnow
from backend.models.consent import ModelContextConsent
from backend.models.data_lifecycle import (
    DataBarrier,
    DataCleanupItem,
    DataOperation,
    DataPreview,
    DataReceipt,
    DataSuppression,
)
from backend.models.enums import (
    CleanupItemAction,
    DataBarrierScope,
    DataOperationKind,
)
from backend.models.event import Event
from backend.models.permission import PermissionGrant
from backend.models.user import User
from backend.schemas.data import (
    DataOperationOut,
    DataSafeError,
    OperationProgress,
)
from backend.services import data_lifecycle as dl
from backend.services.data_closure import ClosureResult, enumerate_closure
from backend.services.data_recovery import (
    deletion_request_digest,
    seal_capability,
)
from backend.services.data_registry import REGISTRY, Store, graph_version

PREVIEW_TTL = timedelta(minutes=10)
RECEIPT_TTL = timedelta(days=90)
# Re-delivery window for a lost first 202 (A-draft §4 proposal: 10 min).
RECEIPT_DELIVERY_TTL = timedelta(minutes=10)

SCHEMA_VERSION = "1.0"
MINIMUM_CLIENT_VERSION = "0.0.0"
SUPPORTED_SOURCE_KINDS = ["event", "file", "chat_session", "chat_message"]

# The literals the account-scope executor clears in Redis (registry-sourced;
# arq-managed keys are library-internal and not listed).
_ACCOUNT_REDIS_LITERALS = tuple(
    entry.notes.removeprefix("literal ")
    for entry in REGISTRY
    if entry.store == Store.REDIS and entry.notes.startswith("literal ")
)


def _canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def preview_digest(
    user_id: uuid.UUID,
    target: dict,
    *,
    graph_ver: str,
    data_generation: int,
    closure: ClosureResult,
) -> str:
    """Bind user + target + graph + generation + impact + content versions.

    Deliberately NOT a hash of row counts (A-draft §2.1): the impact sets
    and per-row updated_at stamps make any drift between preview and confirm
    a preview_stale 409 instead of a silently different deletion scope.
    """

    payload = {
        "user": str(user_id),
        "target": target,
        "graph_version": graph_ver,
        "data_generation": data_generation,
        "impact": [
            [
                impact.resource_type,
                sorted(impact.delete_ids),
                sorted(impact.recompute_ids),
                sorted(impact.redact_ids),
            ]
            for impact in closure.impacts
        ],
        "object_keys": sorted(closure.object_keys),
        "content_versions": sorted(closure.content_versions),
    }
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def create_preview(session: Session, *, user: User, target_model: Any) -> DataPreview:
    """Compute and persist one 10-minute, digest-bound preview (Level 0)."""

    target = target_model.model_dump(mode="json")
    generation = session.scalar(select(User.data_generation).where(User.id == user.id)) or 1
    closure = enumerate_closure(session, user_id=user.id, target=target)
    graph_ver = graph_version()
    digest = preview_digest(
        user.id, target, graph_ver=graph_ver, data_generation=generation, closure=closure
    )
    now = utcnow()
    # Lazy TTL purge keeps the table bounded without a cron dependency.
    session.execute(
        delete(DataPreview).where(DataPreview.user_id == user.id, DataPreview.expires_at <= now)
    )
    row = DataPreview(
        user_id=user.id,
        target=target,
        graph_version=graph_ver,
        data_generation=generation,
        preview_digest=digest,
        effects=[
            {
                "resource_type": impact.resource_type,
                "delete_count": len(impact.delete_ids),
                "redact_count": len(impact.redact_ids),
                "recompute_count": len(impact.recompute_ids),
                "retain_count": 0,
                "reason_code": impact.reason_code,
            }
            for impact in closure.impacts
            if impact.delete_ids or impact.recompute_ids or impact.redact_ids
        ],
        limitations=list(closure.limitations),
        expires_at=now + PREVIEW_TTL,
    )
    session.add(row)
    session.flush()
    return row


def _find_idempotent(
    session: Session, owner_handle: str, client_request_id: str
) -> DataOperation | None:
    return session.scalar(
        select(DataOperation).where(
            DataOperation.owner_handle == owner_handle,
            DataOperation.kind == DataOperationKind.DELETION,
            DataOperation.client_request_id == client_request_id,
        )
    )


def _barrier_shape(target: dict) -> tuple[DataBarrierScope, set[str] | None]:
    kind = target["kind"]
    if kind == "account":
        return DataBarrierScope.ACCOUNT, None
    ids = {str(value) for value in target.get("ids", [])}
    if kind == "source":
        return DataBarrierScope.SOURCE, ids
    return DataBarrierScope.MEMORY, ids


def _impact_payload(closure: ClosureResult) -> dict:
    return {
        "families": [
            {
                "resource_type": impact.resource_type,
                "delete_ids": list(impact.delete_ids),
                "recompute_ids": list(impact.recompute_ids),
                "redact_ids": list(impact.redact_ids),
                "reason_code": impact.reason_code,
            }
            for impact in closure.impacts
        ],
        "object_keys": list(closure.object_keys),
    }


def _cleanup_specs(
    session: Session, user_id: uuid.UUID, target: dict, closure: ClosureResult
) -> list[dl.CleanupItemSpec]:
    """Registry-driven durable work for the slice-2 executor.

    Every relational item carries the exact closure ids — the account scope
    included: id-addressed deletes are order-independent under the FK graph
    (the users-row CASCADE wipes dependent rows either way, and audit redact
    must be id-addressed because audit user_id SET-NULLs away)."""

    specs: list[dl.CleanupItemSpec] = []
    account = target["kind"] == "account"
    for impact in closure.impacts:
        if impact.redact_ids and not impact.delete_ids:
            # Audit family: redact in place, never delete rows (90d TTL);
            # real row ids so the executor can locate rows after the users
            # row is gone (adjudication ②).
            specs.append(
                dl.CleanupItemSpec(
                    impact.resource_type,
                    f"{impact.resource_type}:redact",
                    CleanupItemAction.DELETE_RELATIONAL.value,
                    {"redact": True, "ids": list(impact.redact_ids)},
                )
            )
        elif impact.delete_ids:
            specs.append(
                dl.CleanupItemSpec(
                    impact.resource_type,
                    impact.resource_type,
                    CleanupItemAction.DELETE_RELATIONAL.value,
                    {"ids": list(impact.delete_ids)},
                )
            )
        else:
            continue
        specs.append(
            dl.CleanupItemSpec(
                impact.resource_type,
                impact.resource_type,
                CleanupItemAction.VERIFY_ABSENT.value,
                {"ids": list(impact.delete_ids or impact.redact_ids)},
            )
        )
    for key in closure.object_keys:
        specs.append(
            dl.CleanupItemSpec("file_objects", key, CleanupItemAction.DELETE_OBJECT.value, None)
        )
        # Object erasure needs its OWN verification: only a confirmed 404
        # counts (A-draft §2.5), which row-family VERIFY cannot express.
        specs.append(
            dl.CleanupItemSpec("storage_objects", key, CleanupItemAction.VERIFY_ABSENT.value, None)
        )
    if account:
        # The owner's export staging packages are void with the account
        # (A-draft §3): their objects die with this operation's cleanup.
        from backend.services.data_exports import staging_key

        handle = dl.owner_handle_of(session, user_id)
        export_ops = (
            session.execute(
                select(DataOperation.id).where(
                    DataOperation.owner_handle == handle,
                    DataOperation.kind == DataOperationKind.EXPORT,
                )
            )
            .scalars()
            .all()
        )
        for export_id in export_ops:
            specs.append(
                dl.CleanupItemSpec(
                    "storage_objects",
                    staging_key(handle, export_id),
                    CleanupItemAction.DELETE_OBJECT.value,
                    None,
                )
            )
        for literal in _ACCOUNT_REDIS_LITERALS:
            specs.append(
                dl.CleanupItemSpec(
                    "redis",
                    literal,
                    CleanupItemAction.CLEAR_REDIS.value,
                    {"member": str(user_id)},
                )
            )
    return specs


def _upstream_hmac(source_kind: str, upstream: str) -> str:
    key = get_settings().secret_key.encode("utf-8")
    return hmac.new(key, f"{source_kind}:{upstream}".encode(), hashlib.sha256).hexdigest()


def _register_suppressions(
    session: Session, *, handle: str, target: dict, closure: ClosureResult, generation: int
) -> None:
    """Owner-scoped upstream suppression (A-draft §2.6): re-import blocked."""

    source_kind = target["source_kind"]
    family_of = {
        "event": "events",
        "file": "file_objects",
        "chat_session": "chat_sessions",
        "chat_message": "chat_messages",
    }
    upstreams: list[str] = []
    if source_kind == "event":
        # Prefer the connector-level upstream id; the event id is the
        # fallback anchor when no external identity was recorded.
        provenance_rows = session.execute(
            select(Event.id, Event.provenance).where(
                Event.id.in_([uuid.UUID(value) for value in closure.delete_ids_of("events")])
            )
        ).all()
        upstreams = [str(row[1].get("upstream_id") or row[0]) for row in provenance_rows]
    else:
        family = family_of.get(source_kind) or source_kind
        upstreams = list(closure.delete_ids_of(family))
    if not upstreams:
        return
    pairs = [(source_kind, _upstream_hmac(source_kind, upstream)) for upstream in upstreams]
    existing = {
        (row[0], row[1])
        for row in session.execute(
            select(DataSuppression.source_kind, DataSuppression.upstream_hmac).where(
                DataSuppression.owner_handle == handle,
                DataSuppression.source_kind == source_kind,
            )
        ).all()
    }
    for kind_value, digest_value in pairs:
        if (kind_value, digest_value) in existing:
            continue
        session.add(
            DataSuppression(
                owner_handle=handle,
                source_kind=kind_value,
                upstream_hmac=digest_value,
                raised_generation=generation,
            )
        )


def _issue_receipt(session: Session, *, operation: DataOperation, handle: str) -> str:
    """Random >=128-bit capability; the ledger stores its digest only."""

    token = secrets.token_urlsafe(32)
    now = utcnow()
    nonce, ciphertext = seal_capability(token, receipt_owner=handle, operation_id=operation.id)
    receipt = DataReceipt(
        operation_id=operation.id,
        owner_handle=handle,
        capability_digest=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        issued_at=now,
        expires_at=now + RECEIPT_TTL,
        delivery_nonce=nonce,
        delivery_ciphertext=ciphertext,
        delivery_expires_at=now + RECEIPT_DELIVERY_TTL,
    )
    session.add(receipt)
    session.flush()
    operation.receipt_id = receipt.id
    return token


def confirm_deletion(
    session: Session,
    *,
    user: User,
    preview_id: uuid.UUID,
    preview_digest_value: str,
    client_request_id: str,
    request_body: dict | None = None,
) -> tuple[DataOperation, str | None]:
    """The Level 2 accept transaction; returns (operation, capability?).

    The capability is non-null exactly once — when THIS call creates an
    account-deletion operation. Replays return the operation with no
    capability (lost tokens go through the recover path, slice 2).
    ``request_body`` is the confirm request as received (for the recover
    digest, D-036 §8-2); the route always passes it.
    """

    handle = dl.owner_handle_of(session, user.id)

    # Idempotency first (A-draft §4): a replay must return the same
    # operation even when the preview row is long gone.
    existing = _find_idempotent(session, handle, client_request_id)
    if existing is not None:
        if existing.preview_digest != preview_digest_value:
            raise ConflictError(
                "client_request_id already used with a different preview",
                code="idempotency_conflict",
            )
        return existing, None

    preview = session.get(DataPreview, preview_id)
    if preview is None or preview.user_id != user.id:
        raise NotFoundError("preview not found")
    now = utcnow()
    if preview.expires_at <= now:
        raise ConflictError("preview expired; preview again", code="preview_stale")
    if preview.preview_digest != preview_digest_value:
        raise ConflictError("preview digest mismatch; preview again", code="preview_stale")

    # Scope moved since the preview? Recompute the full closure and compare
    # digests — no silent widening (A-draft §2.2).
    closure = enumerate_closure(session, user_id=user.id, target=preview.target)
    recomputed = preview_digest(
        user.id,
        preview.target,
        graph_ver=preview.graph_version,
        data_generation=preview.data_generation,
        closure=closure,
    )
    if recomputed != preview.preview_digest:
        raise ConflictError(
            "the data changed since this preview; preview again", code="preview_stale"
        )

    scope, barrier_ids = _barrier_shape(preview.target)
    active = dl.matching_barrier(session, handle, scope=scope, target_ids=barrier_ids)
    if active is not None:
        raise ConflictError(
            "a deletion is already in progress for this scope", code="deletion_in_progress"
        )

    # Serialize concurrent same-key confirms on the users row (B carry ① on
    # #70): the bump UPDATE takes the row lock, so the loser waits here and
    # then finds the winner's operation below instead of racing to INSERT.
    generation = dl.bump_data_generation(session, user.id)

    existing = _find_idempotent(session, handle, client_request_id)
    if existing is not None:
        if existing.preview_digest != preview_digest_value:
            raise ConflictError(
                "client_request_id already used with a different preview",
                code="idempotency_conflict",
            )
        return existing, None

    request = dl.OperationRequest(
        kind=DataOperationKind.DELETION,
        client_request_id=client_request_id,
        target=preview.target,
        data_generation=generation,
        preview_digest=preview_digest_value,
        impact=_impact_payload(closure),
    )
    try:
        # Savepoint so an idempotency-unique violation (a confirm that slid
        # past every pre-check) converges instead of poisoning the transaction.
        with session.begin_nested():
            operation, _created = dl.get_or_create_operation(session, handle, request)
    except IntegrityError as error:
        # B carry ① on #70: converge on the winner's operation. By the time
        # PG raises the duplicate, the blocking insert has committed and is
        # visible, so the re-query finds it; a genuinely different input 409s.
        winner = _find_idempotent(session, handle, client_request_id)
        if winner is not None and winner.preview_digest == preview_digest_value:
            return winner, None
        raise ConflictError(
            "client_request_id already used with a different input",
            code="idempotency_conflict",
        ) from error

    # Recover second factor (D-036 §8-2): digest of the canonical request
    # body; stored on create only — replays keep the accepted digest.
    if request_body is not None:
        operation.request_digest = deletion_request_digest(request_body)

    dl.raise_barrier(
        session,
        owner_handle=handle,
        scope=scope,
        raised_generation=generation,
        target=None if scope is DataBarrierScope.ACCOUNT else preview.target,
        operation_id=operation.id,
    )

    capability: str | None = None
    if preview.target["kind"] == "account":
        user.is_active = False
        revoked = {"revoked_at": now}
        session.execute(
            update(PermissionGrant)
            .where(
                PermissionGrant.user_id == user.id,
                PermissionGrant.revoked_at.is_(None),
            )
            .values(revoked)
        )
        session.execute(
            update(ModelContextConsent)
            .where(
                ModelContextConsent.user_id == user.id,
                ModelContextConsent.revoked_at.is_(None),
            )
            .values(revoked)
        )
        capability = _issue_receipt(session, operation=operation, handle=handle)
    elif preview.target["kind"] == "source":
        # Suppression anchors exist for re-importable sources only; a
        # memory-chain deletion has no upstream identity to suppress
        # (A-draft §2.6). Reached here by memory confirms too — they must
        # not read target["source_kind"] (latent KeyError, unfixed until
        # this slice's guard tests confirmed a memory scope).
        _register_suppressions(
            session, handle=handle, target=preview.target, closure=closure, generation=generation
        )

    specs = _cleanup_specs(session, user.id, preview.target, closure)
    dl.enqueue_cleanup_items(session, operation, specs)
    operation.progress_total = len(specs)
    operation.outstanding_count = len(specs)
    session.flush()
    return operation, capability


def operation_for_owner(session: Session, *, handle: str, operation_id: uuid.UUID) -> DataOperation:
    operation = session.scalar(
        select(DataOperation).where(
            DataOperation.id == operation_id, DataOperation.owner_handle == handle
        )
    )
    if operation is None:
        raise NotFoundError("operation not found")
    return operation


def current_generation(session: Session, user_id: uuid.UUID) -> int:
    return session.scalar(select(User.data_generation).where(User.id == user_id)) or 1


def operation_dto(
    operation: DataOperation, *, receipt_capability: str | None = None
) -> DataOperationOut:
    return DataOperationOut(
        id=operation.id,
        kind=operation.kind,
        target=operation.target,
        status=operation.status,
        phase=operation.phase,
        version=operation.version,
        data_generation=operation.data_generation,
        created_at=operation.created_at,
        updated_at=operation.updated_at,
        next_retry_at=operation.next_retry_at,
        expires_at=operation.expires_at,
        progress=OperationProgress(
            processed=operation.progress_processed,
            total=operation.progress_total,
            outstanding_count=operation.outstanding_count,
        ),
        error=(
            DataSafeError(
                code=operation.error_code or "unknown",
                message=operation.error_message or "",
                retryable=operation.error_retryable or False,
            )
            if operation.error_code
            else None
        ),
        receipt_id=operation.receipt_id,
        receipt_capability=receipt_capability,
    )


def barriers_of(session: Session, handle: str) -> list[DataBarrier]:
    return list(
        session.scalars(select(DataBarrier).where(DataBarrier.owner_handle == handle)).all()
    )


def cleanup_items_of(session: Session, operation_id: uuid.UUID) -> list[DataCleanupItem]:
    return list(
        session.scalars(
            select(DataCleanupItem).where(DataCleanupItem.operation_id == operation_id)
        ).all()
    )
