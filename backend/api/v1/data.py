"""Data lifecycle endpoints (P0-3): capabilities, previews, deletion confirm,
exports, operation read/download/retry, recover and receipts (slice 2).

Level 0: capabilities, previews, operation reads, exports (the owner's own
portable copy) and receipt reads. Level 2: the deletion confirm, which
returns 202 = durably accepted, never "cleanup done". Every route derives
identity from the auth context; no trusted user id is ever accepted from a
request body. Anti-enumeration (A-draft §4): recover and receipt reads
answer every negative outcome with one uniform 404, rate-limited per
identity AND per IP on the recover path.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import Response as PlainResponse

from backend.api.deps import CurrentIdentity, CurrentUser, DBSession
from backend.core.errors import NotFoundError, RateLimitError
from backend.core.proxy import client_ip
from backend.core.rate_limit import RateLimiter
from backend.models.data_lifecycle import DataOperation
from backend.models.enums import DataOperationStatus
from backend.schemas.data import (
    DataCapabilities,
    DataEffect,
    DataOperationOut,
    DataPreviewOut,
    DataReceiptOut,
    DeleteTargetIn,
    DeletionConfirmRequest,
    DeletionRecoverRequest,
    ExportCreateRequest,
    OperationRetryRequest,
)
from backend.services import data_exports as exports
from backend.services import data_lifecycle as dl
from backend.services import data_operations as ops
from backend.services import data_recovery as recovery
from backend.services.data_executor import requeue_account_operation, retry_cleanup_operation
from backend.services.data_registry import graph_version
from backend.services.storage import get_storage

router = APIRouter(prefix="/data", tags=["data"])

# Recover is the one route a deactivated identity may call, so it carries
# its own throttle: per identity and per IP, both sliding windows
# (A-draft §4 double rate limit; the Redis-shared swap is the §6 seam).
_RECOVER_LIMITS = (
    RateLimiter(max_requests=3, window_seconds=600.0),
    RateLimiter(max_requests=10, window_seconds=600.0),
)

#: Backup retention window reported on receipts (D-036 §8-2: 30 days).
_BACKUP_TTL = timedelta(days=30)

_RECEIPT_PROVIDER_LIMITATIONS = (
    "Encrypted DB/object backups roll for at most 30 days.",
    "Provider-side retention follows the provider's policy.",
)


@router.get("/capabilities", response_model=DataCapabilities)
def capabilities(user: CurrentUser) -> DataCapabilities:
    return DataCapabilities(
        schema_version=ops.SCHEMA_VERSION,
        graph_version=graph_version(),
        export_enabled=True,
        deletion_enabled=True,
        supported_source_kinds=ops.SUPPORTED_SOURCE_KINDS,
        minimum_client_version=ops.MINIMUM_CLIENT_VERSION,
    )


@router.post("/previews", response_model=DataPreviewOut, status_code=status.HTTP_201_CREATED)
def create_preview(target: DeleteTargetIn, user: CurrentUser, db: DBSession) -> DataPreviewOut:
    row = ops.create_preview(db, user=user, target_model=target)
    return DataPreviewOut(
        id=row.id,
        target=row.target,
        graph_version=row.graph_version,
        data_generation=row.data_generation,
        preview_digest=row.preview_digest,
        expires_at=row.expires_at,
        effects=row.effects,
        limitations=row.limitations,
    )


@router.post("/deletions", response_model=DataOperationOut, status_code=status.HTTP_202_ACCEPTED)
def confirm_deletion(
    request: DeletionConfirmRequest, user: CurrentUser, db: DBSession
) -> DataOperationOut:
    operation, capability = ops.confirm_deletion(
        db,
        user=user,
        preview_id=request.preview_id,
        preview_digest_value=request.preview_digest,
        client_request_id=request.client_request_id,
        request_body=request.model_dump(mode="json"),
    )
    return ops.operation_dto(operation, receipt_capability=capability)


@router.post("/exports", response_model=DataOperationOut, status_code=status.HTTP_202_ACCEPTED)
def create_export(
    request: ExportCreateRequest, user: CurrentUser, db: DBSession
) -> DataOperationOut:
    operation, _created = exports.create_export(
        db,
        user=user,
        client_request_id=request.client_request_id,
        include_files=request.include_files,
    )
    return ops.operation_dto(operation)


@router.get("/operations/{operation_id}", response_model=DataOperationOut)
def get_operation(
    operation_id: uuid.UUID, user: CurrentUser, db: DBSession, response: Response
) -> DataOperationOut:
    handle = dl.owner_handle_of(db, user.id)
    operation = ops.operation_for_owner(db, handle=handle, operation_id=operation_id)
    # In-flight writers compare against this; readers see the live value.
    response.headers["X-Data-Generation"] = str(ops.current_generation(db, user.id))
    return ops.operation_dto(operation)


@router.get("/operations/{operation_id}/download")
def download_operation(operation_id: uuid.UUID, user: CurrentUser, db: DBSession) -> PlainResponse:
    handle = dl.owner_handle_of(db, user.id)
    operation = ops.operation_for_owner(db, handle=handle, operation_id=operation_id)
    package = exports.download_package(db, operation, storage=get_storage())
    return PlainResponse(
        content=package,
        media_type="application/zip",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/operations/{operation_id}/retry", response_model=DataOperationOut)
def retry_operation(
    operation_id: uuid.UUID,
    request: OperationRetryRequest,
    user: CurrentUser,
    db: DBSession,
) -> DataOperationOut:
    handle = dl.owner_handle_of(db, user.id)
    operation = ops.operation_for_owner(db, handle=handle, operation_id=operation_id)
    operation = retry_cleanup_operation(db, operation, expected_version=request.expected_version)
    return ops.operation_dto(operation)


@router.post(
    "/deletions/recover",
    response_model=DataOperationOut,
    status_code=status.HTTP_200_OK,
)
def recover_deletion(
    request: DeletionRecoverRequest,
    http_request: Request,
    identity: CurrentIdentity,
    db: DBSession,
) -> DataOperationOut:
    source_ip = client_ip(http_request)
    for limiter, key in (
        (_RECOVER_LIMITS[0], f"recover:id:{identity.id}"),
        (_RECOVER_LIMITS[1], f"recover:ip:{source_ip}"),
    ):
        if not limiter.hit(key):
            raise RateLimitError(
                "too many recover attempts; retry later",
                code="rate_limited",
                headers={"Retry-After": str(limiter.retry_after(key))},
            )
    handle = dl.owner_handle_of(db, identity.id)
    result = recovery.recover_deletion(
        db,
        owner_handle=handle,
        client_request_id=request.client_request_id,
        request_digest=request.request_digest,
    )
    if result is None:
        # Uniform 404: no such request / wrong digest / outside the 10-minute
        # window / already re-delivered are indistinguishable (A-draft §4).
        raise NotFoundError("recover unavailable")
    operation, capability = result
    return ops.operation_dto(operation, receipt_capability=capability)


@router.get("/receipts/{receipt_id}", response_model=DataReceiptOut)
def read_receipt(receipt_id: uuid.UUID, http_request: Request, db: DBSession) -> DataReceiptOut:
    # The capability travels in the Authorization header, never the URL
    # (A-draft §4); it is the ONLY auth for this route and works after the
    # account is deactivated.
    header = http_request.headers.get("Authorization") or ""
    token = header.removeprefix("Bearer ").strip()
    if not token:
        # Invalid capability == unknown receipt: the uniform 404.
        raise NotFoundError("receipt not found")
    receipt = recovery.receipt_view(db, receipt_id=receipt_id, capability=token)
    if receipt is None:
        raise NotFoundError("receipt not found")
    operation = db.get(DataOperation, receipt.operation_id)
    impact: dict = dict(operation.impact or {}) if operation is not None else {}
    effects = [
        DataEffect(
            resource_type=family.get("resource_type", ""),
            delete_count=len(family.get("delete_ids") or []),
            redact_count=len(family.get("redact_ids") or []),
            recompute_count=len(family.get("recompute_ids") or []),
            retain_count=0,
            reason_code=family.get("reason_code", "accepted_closure"),
        )
        for family in impact.get("families", [])
    ]
    completed = (
        operation.updated_at
        if operation is not None and operation.status == DataOperationStatus.COMPLETED
        else None
    )
    return DataReceiptOut(
        id=receipt.id,
        operation_id=receipt.operation_id,
        completed_at=completed,
        completion_scope="controlled_live",
        effects=effects,
        outstanding_count=operation.outstanding_count if operation is not None else 0,
        operation_status=operation.status.value if operation is not None else "unknown",
        operation_version=operation.version if operation is not None else 1,
        backup_expires_at=None if completed is None else completed + _BACKUP_TTL,
        provider_limitations=list(_RECEIPT_PROVIDER_LIMITATIONS),
        local_cleanup_required=True,
        audit_receipt_version=ops.SCHEMA_VERSION,
    )


@router.post("/receipts/{receipt_id}/requeue", response_model=DataOperationOut)
def requeue_failed_account_deletion(
    receipt_id: uuid.UUID,
    request: OperationRetryRequest,
    http_request: Request,
    db: DBSession,
) -> DataOperationOut:
    """The account arm of the manual retry (external review #7; task doc
    §3 pre-ruling).

    The confirm-time deactivation stays, so the login cannot reach the
    authed retry route — the receipt capability (this narrow path's only
    key, Authorization header, never the URL) drives the SAME ladder reset
    as source/memory retries. Anti-enumeration matches the receipt read: a
    missing or wrong capability is the uniform 404; a valid one gets the
    honest state answers (409 version_conflict / not_retryable)."""

    header = http_request.headers.get("Authorization") or ""
    token = header.removeprefix("Bearer ").strip()
    if not token:
        raise NotFoundError("receipt not found")
    receipt = recovery.receipt_view(db, receipt_id=receipt_id, capability=token)
    if receipt is None:
        raise NotFoundError("receipt not found")
    operation = requeue_account_operation(db, receipt, expected_version=request.expected_version)
    return ops.operation_dto(operation)
