from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from backend.api.deps import CurrentUser, DBSession, PaginationDep
from backend.models.audit import AuditLog
from backend.schemas.audit import AuditLogRead
from backend.schemas.common import Page

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=Page[AuditLogRead])
def list_audit(
    user: CurrentUser,
    db: DBSession,
    pagination: PaginationDep,
    action: Annotated[str | None, Query()] = None,
) -> Page[AuditLogRead]:
    conditions = [AuditLog.user_id == user.id]
    if action:
        conditions.append(AuditLog.action == action)
    total = db.scalar(select(func.count()).select_from(AuditLog).where(*conditions)) or 0
    stmt = (
        select(AuditLog)
        .where(*conditions)
        .order_by(AuditLog.created_at.desc())
        .limit(pagination.limit)
        .offset(pagination.offset)
    )
    entries = list(db.scalars(stmt))
    return Page(
        items=[AuditLogRead.model_validate(entry) for entry in entries],
        total=int(total),
        limit=pagination.limit,
        offset=pagination.offset,
    )
