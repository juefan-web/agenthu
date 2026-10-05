from __future__ import annotations

import uuid
from collections.abc import Sequence

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from backend.api.deps import CurrentUser, DBSession, PaginationDep
from backend.core.errors import ConflictError
from backend.models.enums import MemoryCorrectionStatus
from backend.models.memory import Memory
from backend.schemas.common import Page
from backend.schemas.memory import (
    EventEvidence,
    Evidence,
    MemoryCorrectRequest,
    MemoryCreate,
    MemoryRead,
    MemoryUpdate,
)
from backend.services.lookup import ensure_owned_events, get_memory
from backend.services.memory_lifecycle import (
    confirm_memory,
    correct_memory,
    live_memory_conditions,
    reject_memory,
)

router = APIRouter(prefix="/memory", tags=["memory"])


def _evidence_event_ids(evidence: Sequence[Evidence]) -> list[uuid.UUID]:
    # Event-type evidence references get the same cross-user check as
    # source_event_ids (D-014); memory/document references resolve in M3+.
    return [item.id for item in evidence if isinstance(item, EventEvidence)]


def _dump_evidence(evidence: Sequence[Evidence]) -> list[dict]:
    return [item.model_dump(mode="json") for item in evidence]


def _live_key_owner(db: DBSession, user_id: uuid.UUID, subject_key: str | None) -> uuid.UUID | None:
    """Id of the live row occupying (user, subject_key), if any (D-031 §3;
    liveness per D-036 §1, so a retired-but-unpointed row does not squat
    the key)."""

    if subject_key is None:
        return None
    stmt = select(Memory.id).where(
        Memory.user_id == user_id,
        Memory.subject_key == subject_key,
        *live_memory_conditions(),
    )
    return db.scalar(stmt)


@router.post("", response_model=MemoryRead, status_code=status.HTTP_201_CREATED)
def create(payload: MemoryCreate, user: CurrentUser, db: DBSession) -> Memory:
    # P2: every referenced source event must belong to the current user.
    ensure_owned_events(db, user_id=user.id, event_ids=payload.source_event_ids)
    ensure_owned_events(db, user_id=user.id, event_ids=_evidence_event_ids(payload.evidence))
    # Pre-check first (D-003 pattern): the common conflict exits cleanly and
    # only the true race falls into the savepoint below. A failed flush
    # poisons the session until an explicit rollback, which is fine in
    # production (get_db rolls back on exception) but noisy in tests; the
    # pre-check keeps the happy path of every caller clean either way.
    if _live_key_owner(db, user.id, payload.subject_key) is not None:
        raise ConflictError(
            "A live memory with this subject_key already exists; supersede it "
            "instead of creating a second live row"
        )
    data = payload.model_dump()
    data["source_event_ids"] = [str(event_id) for event_id in payload.source_event_ids]
    data["evidence"] = _dump_evidence(payload.evidence)
    memory = Memory(user_id=user.id, **data)
    db.add(memory)
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError:
        # Race backstop: someone else inserted the live row between the
        # pre-check and the insert.
        raise ConflictError(
            "A live memory with this subject_key already exists; supersede it "
            "instead of creating a second live row"
        ) from None
    return memory


@router.get("", response_model=Page[MemoryRead])
def list_all(
    user: CurrentUser,
    db: DBSession,
    pagination: PaginationDep,
    level: int | None = Query(default=None, ge=0, le=3),
    domain: str | None = Query(default=None),
    correction_status: MemoryCorrectionStatus | None = Query(default=None),
) -> Page[MemoryRead]:
    conditions = [Memory.user_id == user.id]
    if level is not None:
        conditions.append(Memory.level == level)
    if domain is not None:
        conditions.append(Memory.domain == domain)
    if correction_status is not None:
        conditions.append(Memory.correction_status == correction_status)
    total = db.scalar(select(func.count()).select_from(Memory).where(*conditions)) or 0
    stmt = (
        select(Memory)
        .where(*conditions)
        .order_by(Memory.updated_at.desc())
        .limit(pagination.limit)
        .offset(pagination.offset)
    )
    memories = list(db.scalars(stmt))
    return Page(
        items=[MemoryRead.model_validate(memory) for memory in memories],
        total=int(total),
        limit=pagination.limit,
        offset=pagination.offset,
    )


@router.get("/{memory_id}", response_model=MemoryRead)
def get_one(memory_id: uuid.UUID, user: CurrentUser, db: DBSession) -> Memory:
    return get_memory(db, user_id=user.id, memory_id=memory_id)


@router.patch("/{memory_id}", response_model=MemoryRead)
def update(memory_id: uuid.UUID, payload: MemoryUpdate, user: CurrentUser, db: DBSession) -> Memory:
    memory = get_memory(db, user_id=user.id, memory_id=memory_id)
    data = payload.model_dump(exclude_unset=True)
    if "source_event_ids" in data and data["source_event_ids"] is not None:
        ensure_owned_events(db, user_id=user.id, event_ids=data["source_event_ids"])
        data["source_event_ids"] = [str(event_id) for event_id in data["source_event_ids"]]
    if "evidence" in data and data["evidence"] is not None:
        evidence = payload.evidence
        if evidence is not None:
            ensure_owned_events(db, user_id=user.id, event_ids=_evidence_event_ids(evidence))
            data["evidence"] = _dump_evidence(evidence)
    # Same pre-check as create; the row itself keeps its own key.
    if (
        "subject_key" in data
        and data["subject_key"] != memory.subject_key
        and _live_key_owner(db, user.id, data["subject_key"]) not in (None, memory.id)
    ):
        raise ConflictError(
            "A live memory with this subject_key already exists; supersede it "
            "instead of creating a second live row"
        )
    for field, value in data.items():
        setattr(memory, field, value)
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError:
        raise ConflictError(
            "A live memory with this subject_key already exists; supersede it "
            "instead of creating a second live row"
        ) from None
    return memory


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(memory_id: uuid.UUID, user: CurrentUser, db: DBSession) -> Response:
    memory = get_memory(db, user_id=user.id, memory_id=memory_id)
    db.delete(memory)
    db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{memory_id}/confirm", response_model=MemoryRead)
def confirm(memory_id: uuid.UUID, user: CurrentUser, db: DBSession) -> Memory:
    """Confirm a memory (also the documented "un-reject" path)."""

    return confirm_memory(db, get_memory(db, user_id=user.id, memory_id=memory_id))


@router.post(
    "/{memory_id}/correct",
    response_model=MemoryRead,
    status_code=status.HTTP_201_CREATED,
)
def correct(
    memory_id: uuid.UUID, payload: MemoryCorrectRequest, user: CurrentUser, db: DBSession
) -> Memory:
    """Replace a memory with a corrected version (201: a new row is created)."""

    return correct_memory(
        db,
        get_memory(db, user_id=user.id, memory_id=memory_id),
        content=payload.content,
        confidence=payload.confidence,
    )


@router.post("/{memory_id}/reject", response_model=MemoryRead)
def reject(memory_id: uuid.UUID, user: CurrentUser, db: DBSession) -> Memory:
    """Reject a memory; the live row stays as a REJECTED subject_key placeholder."""

    return reject_memory(db, get_memory(db, user_id=user.id, memory_id=memory_id))
