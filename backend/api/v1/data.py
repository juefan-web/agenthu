"""Data lifecycle endpoints: capabilities, previews, deletion confirm (P0-3).

Level 0: capabilities and previews (no execution). Level 2: the deletion
confirm, which returns 202 = durably accepted, never "cleanup done". Every
route derives identity from the auth context; no trusted user id is ever
accepted from the request body.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status

from backend.api.deps import CurrentUser, DBSession
from backend.schemas.data import (
    DataCapabilities,
    DataOperationOut,
    DataPreviewOut,
    DeleteTargetIn,
    DeletionConfirmRequest,
)
from backend.services import data_lifecycle as dl
from backend.services import data_operations as ops
from backend.services.data_registry import graph_version

router = APIRouter(prefix="/data", tags=["data"])


@router.get("/capabilities", response_model=DataCapabilities)
def capabilities(user: CurrentUser) -> DataCapabilities:
    return DataCapabilities(
        schema_version=ops.SCHEMA_VERSION,
        graph_version=graph_version(),
        # export_enabled flips on when the export pipeline lands (slice 2);
        # capabilities must not advertise what is not callable yet.
        export_enabled=False,
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
    )
    return ops.operation_dto(operation, receipt_capability=capability)


@router.get("/operations/{operation_id}", response_model=DataOperationOut)
def get_operation(
    operation_id: uuid.UUID, user: CurrentUser, db: DBSession, response: Response
) -> DataOperationOut:
    handle = dl.owner_handle_of(db, user.id)
    operation = ops.operation_for_owner(db, handle=handle, operation_id=operation_id)
    # In-flight writers compare against this; readers see the live value.
    response.headers["X-Data-Generation"] = str(ops.current_generation(db, user.id))
    return ops.operation_dto(operation)
