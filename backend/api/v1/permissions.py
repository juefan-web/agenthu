from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status
from sqlalchemy import select

from backend.api.deps import CurrentUser, DBSession
from backend.core.errors import NotFoundError
from backend.models.permission import PermissionGrant
from backend.schemas.permission import (
    PermissionCheckRequest,
    PermissionCheckResult,
    PermissionGrantCreate,
    PermissionGrantRead,
    PermissionPolicyEntry,
    PermissionPolicyRead,
)
from backend.services.permissions import (
    ACTION_POLICY,
    LEVEL_DESCRIPTIONS,
    evaluate_permission,
)

router = APIRouter(prefix="/permissions", tags=["permissions"])


@router.get("/policy", response_model=PermissionPolicyRead)
def policy(user: CurrentUser) -> PermissionPolicyRead:
    entries = [
        PermissionPolicyEntry(action=action, level=level, description=description)
        for action, (level, description) in sorted(ACTION_POLICY.items())
    ]
    return PermissionPolicyRead(levels=LEVEL_DESCRIPTIONS, actions=entries)


@router.get("/grants", response_model=list[PermissionGrantRead])
def list_grants(user: CurrentUser, db: DBSession) -> list[PermissionGrant]:
    stmt = (
        select(PermissionGrant)
        .where(PermissionGrant.user_id == user.id)
        .order_by(PermissionGrant.created_at.desc())
    )
    return list(db.scalars(stmt))


@router.post("/grants", response_model=PermissionGrantRead, status_code=status.HTTP_201_CREATED)
def create_grant(
    payload: PermissionGrantCreate, user: CurrentUser, db: DBSession
) -> PermissionGrant:
    grant = db.scalar(
        select(PermissionGrant).where(
            PermissionGrant.user_id == user.id, PermissionGrant.action == payload.action
        )
    )
    if grant is None:
        grant = PermissionGrant(user_id=user.id, action=payload.action)
        db.add(grant)
    grant.level = payload.level
    grant.scope = payload.scope
    grant.note = payload.note
    grant.expires_at = payload.expires_at
    grant.revoked_at = None
    db.flush()
    return grant


@router.delete("/grants/{grant_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_grant(grant_id: uuid.UUID, user: CurrentUser, db: DBSession) -> Response:
    grant = db.scalar(
        select(PermissionGrant).where(
            PermissionGrant.id == grant_id, PermissionGrant.user_id == user.id
        )
    )
    if grant is None:
        raise NotFoundError("Permission grant not found")
    db.delete(grant)
    db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/check", response_model=PermissionCheckResult)
def check(
    payload: PermissionCheckRequest, user: CurrentUser, db: DBSession
) -> PermissionCheckResult:
    decision = evaluate_permission(
        db,
        user_id=user.id,
        action=payload.action,
        required_level=payload.required_level,
        actor="user",
    )
    return PermissionCheckResult(
        action=decision.action,
        required_level=decision.required_level,
        granted_level=decision.granted_level,
        decision=decision.decision.value,
        allowed=decision.allowed,
        requires_confirmation=decision.requires_confirmation,
        reason=decision.reason,
    )
