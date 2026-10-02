from __future__ import annotations

import hashlib
import logging
import uuid
from pathlib import PurePosixPath
from typing import Annotated

from fastapi import APIRouter, File, Form, Response, UploadFile, status
from sqlalchemy import func, select
from starlette.concurrency import run_in_threadpool

from backend.api.deps import CurrentUser, DBSession, PaginationDep, StorageDep
from backend.config import get_settings
from backend.core.errors import NotFoundError, PayloadTooLargeError, ValidationError
from backend.models.file import FileObject
from backend.models.material import MaterialChunk
from backend.schemas.common import Page
from backend.schemas.file import FileRead, SignedUrl
from backend.schemas.material import MaterialChunkRead
from backend.worker.enqueue import mark_storage_orphan
from backend.worker.queue import get_arq_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/files", tags=["files"])

_CHUNK_SIZE = 1024 * 1024


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
    course_name: Annotated[str | None, Form(max_length=300)] = None,
) -> FileObject:
    settings = get_settings()
    # Stream in chunks and enforce the size limit during the read so an
    # oversized upload never has to be fully buffered in memory.
    hasher = hashlib.sha256()
    buffer = bytearray()
    total = 0
    while True:
        chunk = await file.read(_CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > settings.max_upload_bytes:
            raise PayloadTooLargeError(
                f"File exceeds the maximum size of {settings.max_upload_bytes} bytes"
            )
        hasher.update(chunk)
        buffer.extend(chunk)

    if total == 0:
        raise ValidationError("Uploaded file is empty")

    data = bytes(buffer)
    checksum = hasher.hexdigest()
    suffix = PurePosixPath(file.filename or "").suffix[:16]
    # User-scoped prefix is mandatory (D-033 §4): object-layer isolation on
    # top of row-level auth, even though keys are globally unique anyway.
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
        course_name=course_name,
        status="uploaded" if course_name else "active",
        file_metadata={"declared_size": len(data)},
    )
    try:
        db.add(obj)
        db.flush()
    except Exception:
        # Compensating delete: never leave an orphan object when metadata fails.
        await run_in_threadpool(storage.delete, key)
        raise

    if course_name:
        # Explicit user action started this (D-033 §0.1) — extraction must
        # not vanish with a Redis blip; enqueue best-effort, cron sweeps
        # whatever is still "uploaded" after the grace window.
        try:
            pool = await get_arq_pool()
            await pool.enqueue_job("extract_material", str(obj.id))
        except Exception:
            logger.warning(
                "Extraction enqueue failed; cron sweep will retry",
                extra={"file_id": str(obj.id)},
            )
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


@router.get("/{file_id}/chunks", response_model=Page[MaterialChunkRead])
def list_chunks(
    file_id: uuid.UUID,
    user: CurrentUser,
    db: DBSession,
    pagination: PaginationDep,
) -> Page[MaterialChunkRead]:
    """Extracted chunks of one file (D-033), always user-scoped."""

    _get_file(db, user.id, file_id)
    conditions = [MaterialChunk.user_id == user.id, MaterialChunk.file_id == file_id]
    total = db.scalar(select(func.count()).select_from(MaterialChunk).where(*conditions)) or 0
    stmt = (
        select(MaterialChunk)
        .where(*conditions)
        .order_by(MaterialChunk.chunk_index.asc())
        .limit(pagination.limit)
        .offset(pagination.offset)
    )
    chunks = list(db.scalars(stmt))
    return Page(
        items=[MaterialChunkRead.model_validate(chunk) for chunk in chunks],
        total=int(total),
        limit=pagination.limit,
        offset=pagination.offset,
    )


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(
    file_id: uuid.UUID, user: CurrentUser, db: DBSession, storage: StorageDep
) -> Response:
    obj = _get_file(db, user.id, file_id)
    key = obj.storage_key
    # Deletion order (D-033 §5): relational rows first — material_chunks
    # cascade with the file row — committed before the object delete runs.
    # The old order (object first, rows maybe-never) could leave chunks
    # retrievable against a deleted blob. Object deletion stays best-effort:
    # failures land in the orphan set and the worker cron retries them.
    db.delete(obj)
    db.commit()
    try:
        await run_in_threadpool(storage.delete, key)
    except Exception:
        logger.warning("Object delete failed for %r; marked orphan", key, exc_info=True)
        mark_storage_orphan(key)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
