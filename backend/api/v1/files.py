from __future__ import annotations

import hashlib
import uuid
from pathlib import PurePosixPath
from typing import Annotated

from fastapi import APIRouter, File, Response, UploadFile, status
from sqlalchemy import func, select
from starlette.concurrency import run_in_threadpool

from backend.api.deps import CurrentUser, DBSession, PaginationDep, StorageDep
from backend.config import get_settings
from backend.core.errors import NotFoundError, ValidationError
from backend.models.file import FileObject
from backend.schemas.common import Page
from backend.schemas.file import FileRead, SignedUrl

router = APIRouter(prefix="/files", tags=["files"])


def _get_file(db: DBSession, user_id: uuid.UUID, file_id: uuid.UUID) -> FileObject:
    obj = db.scalar(
        select(FileObject).where(FileObject.id == file_id, FileObject.user_id == user_id)
    )
    if obj is None:
        raise NotFoundError("File not found")
    return obj


@router.post("", response_model=FileRead, status_code=status.HTTP_201_CREATED)
async def upload(
    user: CurrentUser,
    db: DBSession,
    storage: StorageDep,
    file: Annotated[UploadFile, File()],
) -> FileObject:
    settings = get_settings()
    data = await file.read()
    if not data:
        raise ValidationError("Uploaded file is empty")
    if len(data) > settings.max_upload_bytes:
        raise ValidationError(f"File exceeds the maximum size of {settings.max_upload_bytes} bytes")

    checksum = hashlib.sha256(data).hexdigest()
    suffix = PurePosixPath(file.filename or "").suffix[:16]
    key = f"{user.id}/{uuid.uuid4().hex}{suffix}"
    content_type = file.content_type or "application/octet-stream"

    await run_in_threadpool(storage.put, key, data, content_type)

    obj = FileObject(
        user_id=user.id,
        storage_key=key,
        storage_backend=storage.backend_name,
        filename=file.filename or key,
        content_type=content_type,
        size_bytes=len(data),
        checksum_sha256=checksum,
        file_metadata={"declared_size": len(data)},
    )
    db.add(obj)
    db.flush()
    return obj


@router.get("", response_model=Page[FileRead])
def list_all(user: CurrentUser, db: DBSession, pagination: PaginationDep) -> Page[FileRead]:
    conditions = [FileObject.user_id == user.id]
    total = db.scalar(select(func.count()).select_from(FileObject).where(*conditions)) or 0
    stmt = (
        select(FileObject)
        .where(*conditions)
        .order_by(FileObject.created_at.desc())
        .limit(pagination.limit)
        .offset(pagination.offset)
    )
    files = list(db.scalars(stmt))
    return Page(
        items=[FileRead.model_validate(obj) for obj in files],
        total=int(total),
        limit=pagination.limit,
        offset=pagination.offset,
    )


@router.get("/{file_id}", response_model=FileRead)
def get_one(file_id: uuid.UUID, user: CurrentUser, db: DBSession) -> FileObject:
    return _get_file(db, user.id, file_id)


@router.get("/{file_id}/download")
async def download(
    file_id: uuid.UUID, user: CurrentUser, db: DBSession, storage: StorageDep
) -> Response:
    obj = _get_file(db, user.id, file_id)
    data = await run_in_threadpool(storage.get, obj.storage_key)
    filename = PurePosixPath(obj.filename).name or "download"
    return Response(
        content=data,
        media_type=obj.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(data)),
        },
    )


@router.get("/{file_id}/signed-url", response_model=SignedUrl)
async def signed_url(
    file_id: uuid.UUID, user: CurrentUser, db: DBSession, storage: StorageDep
) -> SignedUrl:
    obj = _get_file(db, user.id, file_id)
    expires_in = get_settings().signed_url_expire_seconds
    url = await run_in_threadpool(storage.signed_url, obj.storage_key, expires_in)
    return SignedUrl(url=url, expires_in=expires_in)


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(
    file_id: uuid.UUID, user: CurrentUser, db: DBSession, storage: StorageDep
) -> Response:
    obj = _get_file(db, user.id, file_id)
    await run_in_threadpool(storage.delete, obj.storage_key)
    db.delete(obj)
    db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
