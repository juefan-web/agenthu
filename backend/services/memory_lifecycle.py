"""Semantic memory lifecycle actions (confirm / correct / reject).

D-032 ruling: correction_status moves only through these actions — direct
fills on Create/Update would bypass the version chain. The chain direction is
**superseded-by** (A proposal, B counter-signed 2026-10-01, migration plan
§8): when a new version lands, the *old* row gets ``supersedes_id`` set to
the new row's id in the same transaction. Live row == ``supersedes_id IS
NULL``; the partial unique index and the retrieval filter both key on that.

The correct/supersede logic here is the template the L2 aggregation writer
will reuse (same transaction ordering: retire the old row *before* inserting
the new live row, so the partial unique index never sees two live rows).
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.core.errors import ConflictError
from backend.db.base import utcnow
from backend.models.enums import MemoryCorrectionStatus
from backend.models.memory import Memory

logger = logging.getLogger(__name__)


def _require_live(memory: Memory) -> None:
    if memory.supersedes_id is not None:
        raise ConflictError(
            "Memory is superseded by a newer version; operate on the live row instead"
        )


def confirm_memory(session: Session, memory: Memory) -> Memory:
    """User confirmation: UNREVIEWED/REJECTED -> CONFIRMED, in place.

    A status acknowledgment is not a content change, so no new version is
    created. Confirming an already-confirmed row is a no-op (idempotent).
    Confirming a REJECTED row is the documented "un-reject" path (§5).
    """

    _require_live(memory)
    memory.correction_status = MemoryCorrectionStatus.CONFIRMED
    session.flush()
    return memory


def reject_memory(session: Session, memory: Memory) -> Memory:
    """User rejection: the live row stays as a REJECTED placeholder.

    The row keeps its ``subject_key`` so keyed writers see the rejection and
    skip re-deriving the same subject (§5). Idempotent.
    """

    _require_live(memory)
    memory.correction_status = MemoryCorrectionStatus.REJECTED
    session.flush()
    return memory


def correct_memory(
    session: Session,
    memory: Memory,
    *,
    content: str,
    confidence: float | None,
) -> Memory:
    """User correction: new version superseding the old row (superseded-by).

    The old row is marked CORRECTED, gets ``valid_to`` and — in the same
    transaction — ``supersedes_id = <new row id>``; the new row is CONFIRMED
    (user-written by definition) and becomes the live row. Statement order
    is fixed by the partial unique index: the old row must retire BEFORE the
    new live row inserts (the index cannot be deferred and would otherwise
    see two live rows), which is why the FK is DEFERRABLE — it validates the
    forward pointer at commit, when the new row exists. A SELECT ... FOR
    UPDATE on the old row serializes concurrent corrections; the loser sees
    the pointer already set and gets a 409 instead of a second live row.
    """

    locked = session.scalar(
        select(Memory)
        .where(Memory.id == memory.id, Memory.user_id == memory.user_id)
        .with_for_update()
    )
    if locked is None:
        raise ConflictError("Memory is no longer available")
    _require_live(locked)

    now = utcnow()
    replacement = Memory(
        # Explicit id: the column default only fires at flush, but the old
        # row's superseded-by pointer needs it before either row is flushed.
        id=uuid.uuid4(),
        user_id=memory.user_id,
        level=memory.level,
        domain=memory.domain,
        content=content,
        source={**memory.source, "user_corrected": True},
        source_event_ids=list(memory.source_event_ids),
        confidence=memory.confidence if confidence is None else confidence,
        correction_status=MemoryCorrectionStatus.CONFIRMED,
        subject_key=memory.subject_key,
        kind=memory.kind,
        evidence=list(memory.evidence),
        valid_from=now,
    )
    locked.correction_status = MemoryCorrectionStatus.CORRECTED
    locked.valid_to = locked.valid_to or now
    locked.supersedes_id = replacement.id
    session.flush()  # retire the old row before the new live row lands
    session.add(replacement)
    session.flush()
    return replacement


def upsert_keyed_memory(
    session: Session,
    *,
    user_id: uuid.UUID,
    subject_key: str,
    level: int,
    kind: str,
    domain: str,
    content: str,
    source: dict,
    confidence: float,
    evidence: list[dict],
) -> Memory | None:
    """Deterministic keyed upsert along the superseded-by chain (§4.2).

    The L2 aggregation writer's primitive: FOR UPDATE the live row, skip when
    the user REJECTED the subject (blocking re-derivation, §5), no-op when
    the derived value is unchanged (no version churn per aggregation run),
    otherwise supersede — old row retires (pointer + valid_to) *before* the
    new live row inserts, exactly like ``correct_memory``. Returns the live
    row (existing or new), or None when blocked or race-lost.
    """

    locked = session.scalar(
        select(Memory)
        .where(
            Memory.user_id == user_id,
            Memory.subject_key == subject_key,
            Memory.supersedes_id.is_(None),
        )
        .with_for_update()
    )
    now = utcnow()
    if locked is not None:
        if locked.correction_status == MemoryCorrectionStatus.REJECTED:
            logger.info(
                "Keyed memory re-derivation blocked by REJECTED live row",
                extra={"subject_key": subject_key, "user_id": str(user_id)},
            )
            return None
        unchanged = (
            locked.source.get("value") == source.get("value")
            and locked.source.get("sample_count") == source.get("sample_count")
            if isinstance(locked.source, dict)
            else False
        )
        if unchanged:
            return locked
        replacement = Memory(
            id=uuid.uuid4(),
            user_id=user_id,
            level=level,
            domain=domain,
            content=content,
            source=source,
            source_event_ids=[],
            confidence=confidence,
            correction_status=MemoryCorrectionStatus.CONFIRMED,
            subject_key=subject_key,
            kind=kind,
            evidence=evidence,
            valid_from=now,
        )
        locked.valid_to = locked.valid_to or now
        locked.supersedes_id = replacement.id
        session.flush()
        session.add(replacement)
        session.flush()
        return replacement

    fresh = Memory(
        id=uuid.uuid4(),
        user_id=user_id,
        level=level,
        domain=domain,
        content=content,
        source=source,
        source_event_ids=[],
        confidence=confidence,
        correction_status=MemoryCorrectionStatus.CONFIRMED,
        subject_key=subject_key,
        kind=kind,
        evidence=evidence,
        valid_from=now,
    )
    session.add(fresh)
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError:
        return None  # lost a race against another writer for this key
    return fresh
