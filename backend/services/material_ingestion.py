"""Ingestion orchestration for course materials (D-033 first slice).

Pure-DB/business half of the pipeline; the arq tasks in ``worker/tasks.py``
drive it. Two invariants live here:

- **Consent gate (fail-closed, D-033 §0.4)**: provider calls happen only for
  courses the user explicitly enabled, and the consent is re-checked *at call
  time* — a stale enqueued backfill job after revocation must find the gate
  closed. Un-consented courses never touch the provider, embeddings or not.
- **Idempotent re-extraction**: reruns delete the file's chunks and rebuild
  them (fresh scanner version / chunker). Embeddings follow as a separate
  backfill step; a rerun therefore re-embeds, which is correct — the chunks
  it produced before no longer exist.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.adapters.model_provider.base import EmbeddingResult, ModelProvider
from backend.models.file import FileObject
from backend.models.material import GroundingConsent, MaterialChunk
from backend.services.content_scanner import scan_text
from backend.services.material_extraction import (
    UnsupportedContentTypeError,
    chunk_pages,
    extract_pages,
)
from backend.services.storage import ObjectStorage

logger = logging.getLogger(__name__)

# Files whose extraction is retried by the drain cron when the initial
# enqueue was lost (worker down / Redis blip). "uploaded" is the post-upload
# state; a file stuck there past the grace window needs a retry.
RETRYABLE_STATUSES = ("uploaded", "extraction_failed")


def consent_enabled(session: Session, user_id: uuid.UUID, course_name: str) -> bool:
    row = session.scalar(
        select(GroundingConsent).where(
            GroundingConsent.user_id == user_id,
            GroundingConsent.course_name == course_name,
        )
    )
    return row is not None and row.enabled


def run_extraction(session: Session, file_id: uuid.UUID, storage: ObjectStorage) -> dict:
    """Extract, scan and persist chunks for one file. Idempotent (rebuild)."""

    obj = session.scalar(select(FileObject).where(FileObject.id == file_id).with_for_update())
    if obj is None:
        return {"file_id": str(file_id), "skipped": "file_not_found"}
    if obj.course_name is None:
        # Non-course files never enter the pipeline (upload path guarantees
        # this); guard anyway so a mis-enqueued job is a no-op, not a scan.
        return {"file_id": str(file_id), "skipped": "not_a_course_file"}
    if obj.status not in RETRYABLE_STATUSES and obj.status != "extracted":
        return {"file_id": str(file_id), "skipped": f"status_{obj.status}"}

    try:
        data = storage.get(obj.storage_key)
    except Exception:
        obj.status = "extraction_failed"
        session.flush()
        raise

    # Rebuild semantics: drop previous chunks so a rerun reflects the current
    # scanner version rather than appending duplicates.
    deleted = (
        session.query(MaterialChunk)
        .filter(MaterialChunk.file_id == file_id)
        .delete(synchronize_session=False)
    )

    stats = {"clean": 0, "flagged": 0, "blocked": 0, "replaced": deleted}
    try:
        pages = extract_pages(data, obj.content_type, obj.filename)
    except UnsupportedContentTypeError as exc:
        obj.status = "unsupported_type"
        obj.file_metadata = {
            **obj.file_metadata,
            "extraction_note": str(exc),
            "blocked_chunk_count": 0,
        }
        session.flush()
        return {"file_id": str(file_id), **stats, "status": "unsupported_type"}

    for raw in chunk_pages(pages):
        outcome = scan_text(raw.text)
        if outcome.status == "blocked":
            # D-033 §5: hard-blocked chunks are NOT stored; the file records
            # the count so the UI can say "N 个片段因安全策略被拒绝".
            stats["blocked"] += 1
            continue
        session.add(
            MaterialChunk(
                user_id=obj.user_id,
                file_id=obj.id,
                page=raw.page,
                chunk_index=raw.chunk_index,
                content=outcome.content,
                char_count=len(outcome.content),
                scanner_version=outcome.scanner_version,
                scan_status=outcome.status,
                scan_flags=list(outcome.flags),
            )
        )
        stats[outcome.status] += 1

    if stats["clean"] + stats["flagged"] + stats["blocked"] == 0:
        # Every page extracted empty (scanned PDF?) — call it unsupported
        # instead of "extracted with nothing", so the UI doesn't show a
        # silently empty file.
        obj.status = "unsupported_type"
        obj.file_metadata = {
            **obj.file_metadata,
            "extraction_note": "no text layer extracted",
            "blocked_chunk_count": 0,
        }
    else:
        obj.status = "extracted"
        obj.file_metadata = {
            **obj.file_metadata,
            "chunk_counts": {
                "clean": stats["clean"],
                "flagged": stats["flagged"],
                "blocked": stats["blocked"],
            },
        }
    session.flush()
    logger.info(
        "Material extraction finished",
        extra={"file_id": str(file_id), **stats, "status": obj.status},
    )
    return {"file_id": str(file_id), **stats, "status": obj.status}


def _pending_chunks_query(file_id: uuid.UUID | None, user_id: uuid.UUID, course_name: str):
    stmt = (
        select(MaterialChunk, FileObject)
        .join(FileObject, MaterialChunk.file_id == FileObject.id)
        .where(
            MaterialChunk.user_id == user_id,
            MaterialChunk.embedding.is_(None),
            MaterialChunk.scan_status == "clean",
            FileObject.course_name == course_name,
        )
        .order_by(MaterialChunk.file_id, MaterialChunk.chunk_index)
    )
    if file_id is not None:
        stmt = stmt.where(MaterialChunk.file_id == file_id)
    return stmt


async def embed_pending_chunks(
    session: Session,
    provider: ModelProvider,
    user_id: uuid.UUID,
    course_name: str,
    file_id: uuid.UUID | None = None,
) -> dict:
    """Embed clean, not-yet-embedded chunks of one course (or one file).

    Flagged chunks are deliberately not embedded: they stay retrievable as
    text but never travel to the provider (better fewer than fake-safe).
    Consent is checked at call time — revocation closes the gate for jobs
    that were already enqueued.
    """

    if not consent_enabled(session, user_id, course_name):
        return {"course_name": course_name, "embedded": 0, "skipped": "consent_disabled"}

    rows = session.execute(_pending_chunks_query(file_id, user_id, course_name)).all()
    if not rows:
        return {"course_name": course_name, "embedded": 0}

    texts = [chunk.content for chunk, _file in rows]
    result: EmbeddingResult = await provider.embed_texts(texts)

    by_id = {chunk.id: chunk for chunk, _file in rows}
    for chunk_id, vector in zip(by_id.keys(), result.vectors, strict=True):
        chunk = by_id[chunk_id]
        chunk.embedding = vector
        chunk.embedding_model = result.model
    session.flush()
    return {"course_name": course_name, "embedded": len(result.vectors), "model": result.model}
