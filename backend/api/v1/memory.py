from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import func, select

from backend.api.deps import CurrentUser, DBSession, PaginationDep
from backend.models.enums import MemoryCorrectionStatus
from backend.models.memory import Memory
from backend.schemas.common import Page
from backend.schemas.memory import MemoryCreate, MemoryRead, MemoryUpdate
from backend.services.lookup import ensure_owned_events, get_memory

router = APIRouter(prefix="/memory", tags=["memory"])


@router.post("", response_model=MemoryRead, status_code=status.HTTP_201_CREATED)
def create(payload: MemoryCreate, user: CurrentUser, db: DBSession) -> Memory:
    # P2: every referenced source event must belong to the current user.
    ensure_owned_events(db, user_id=user.id, event_ids=payload.source_event_ids)
    data = payload.model_dump()
    data["source_event_ids"] = [str(event_id) for event_id in payload.source_event_ids]
    memory = Memory(user_id=user.id, **data)
    db.add(memory)
    db.flush()
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
    for field, value in data.items():
        setattr(memory, field, value)
    db.flush()
    return memory


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(memory_id: uuid.UUID, user: CurrentUser, db: DBSession) -> Response:
    memory = get_memory(db, user_id=user.id, memory_id=memory_id)
    db.delete(memory)
    db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
