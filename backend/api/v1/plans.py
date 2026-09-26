from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import func, select

from backend.api.deps import CurrentUser, DBSession, PaginationDep
from backend.core.errors import ConflictError, ValidationError
from backend.db.base import utcnow
from backend.models.enums import PlanStatus
from backend.models.plan import Plan, PlanItem
from backend.schemas.common import Page
from backend.schemas.plan import (
    PlanCreate,
    PlanGenerateRequest,
    PlanItemUpdate,
    PlanRead,
    PlanReplanRequest,
)
from backend.services import permissions
from backend.services.current_state import recompute_current_state
from backend.services.lookup import get_goal, get_plan
from backend.services.planner import generate_plan, replan

router = APIRouter(prefix="/plans", tags=["plans"])

_CONFIRMABLE = (PlanStatus.DRAFT, PlanStatus.PENDING_CONFIRMATION)
_CANCELLABLE = (PlanStatus.DRAFT, PlanStatus.PENDING_CONFIRMATION, PlanStatus.CONFIRMED)


@router.post("", response_model=PlanRead, status_code=status.HTTP_201_CREATED)
def create(payload: PlanCreate, user: CurrentUser, db: DBSession) -> Plan:
    if payload.goal_id is not None:
        get_goal(db, user_id=user.id, goal_id=payload.goal_id)
    plan = Plan(
        user_id=user.id,
        goal_id=payload.goal_id,
        title=payload.title,
        status=PlanStatus.DRAFT,
        basis=payload.basis,
        permission_level=payload.permission_level,
        generated_by="manual",
    )
    for item in payload.items:
        plan.items.append(PlanItem(**item.model_dump()))
    db.add(plan)
    db.flush()
    return plan


@router.post("/generate", response_model=PlanRead, status_code=status.HTTP_201_CREATED)
def generate(payload: PlanGenerateRequest, user: CurrentUser, db: DBSession) -> Plan:
    if payload.goal_id is not None:
        get_goal(db, user_id=user.id, goal_id=payload.goal_id)
    plan = generate_plan(
        db,
        user_id=user.id,
        goal_id=payload.goal_id,
        start_at=payload.start_at,
        horizon_minutes=payload.horizon_minutes,
        max_tasks=payload.max_tasks,
    )
    recompute_current_state(db, user.id)
    return plan


@router.get("", response_model=Page[PlanRead])
def list_all(
    user: CurrentUser,
    db: DBSession,
    pagination: PaginationDep,
    status_filter: Annotated[PlanStatus | None, Query(alias="status")] = None,
    goal_id: Annotated[uuid.UUID | None, Query()] = None,
) -> Page[PlanRead]:
    conditions = [Plan.user_id == user.id]
    if status_filter is not None:
        conditions.append(Plan.status == status_filter)
    if goal_id is not None:
        conditions.append(Plan.goal_id == goal_id)
    total = db.scalar(select(func.count()).select_from(Plan).where(*conditions)) or 0
    stmt = (
        select(Plan)
        .where(*conditions)
        .order_by(Plan.created_at.desc())
        .limit(pagination.limit)
        .offset(pagination.offset)
    )
    plans = list(db.scalars(stmt))
    return Page(
        items=[PlanRead.model_validate(plan) for plan in plans],
        total=int(total),
        limit=pagination.limit,
        offset=pagination.offset,
    )


@router.get("/{plan_id}", response_model=PlanRead)
def get_one(plan_id: uuid.UUID, user: CurrentUser, db: DBSession) -> Plan:
    return get_plan(db, user_id=user.id, plan_id=plan_id)


@router.post("/{plan_id}/confirm", response_model=PlanRead)
def confirm(plan_id: uuid.UUID, user: CurrentUser, db: DBSession) -> Plan:
    plan = get_plan(db, user_id=user.id, plan_id=plan_id)
    if plan.status not in _CONFIRMABLE:
        raise ConflictError(f"Plan in status {plan.status.value} cannot be confirmed")
    # User-initiated confirmation goes through the shared permission layer so
    # the decision is auditable and reusable by the Agent.
    decision = permissions.evaluate_permission(
        db, user_id=user.id, action="plan.confirm", actor="user"
    )
    if not (decision.allowed or decision.requires_confirmation):
        raise ConflictError("Permission denied for plan confirmation")
    plan.status = PlanStatus.CONFIRMED
    plan.confirmed_at = utcnow()
    db.flush()
    recompute_current_state(db, user.id)
    return plan


@router.post("/{plan_id}/cancel", response_model=PlanRead)
def cancel(plan_id: uuid.UUID, user: CurrentUser, db: DBSession) -> Plan:
    plan = get_plan(db, user_id=user.id, plan_id=plan_id)
    if plan.status not in _CANCELLABLE:
        raise ConflictError(f"Plan in status {plan.status.value} cannot be cancelled")
    plan.status = PlanStatus.CANCELLED
    plan.cancelled_at = utcnow()
    db.flush()
    recompute_current_state(db, user.id)
    return plan


@router.post("/{plan_id}/replan", response_model=PlanRead, status_code=status.HTTP_201_CREATED)
def replan_endpoint(
    plan_id: uuid.UUID, payload: PlanReplanRequest, user: CurrentUser, db: DBSession
) -> Plan:
    new_plan = replan(
        db,
        user_id=user.id,
        plan_id=plan_id,
        reason=payload.reason,
        horizon_minutes=payload.horizon_minutes,
    )
    recompute_current_state(db, user.id)
    return new_plan


@router.patch("/{plan_id}/items/{item_id}", response_model=PlanRead)
def update_item(
    plan_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: PlanItemUpdate,
    user: CurrentUser,
    db: DBSession,
) -> Plan:
    plan = get_plan(db, user_id=user.id, plan_id=plan_id)
    item = next((candidate for candidate in plan.items if candidate.id == item_id), None)
    if item is None:
        raise ValidationError("Plan item not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    db.flush()
    recompute_current_state(db, user.id)
    return plan


@router.delete("/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(plan_id: uuid.UUID, user: CurrentUser, db: DBSession) -> Response:
    plan = get_plan(db, user_id=user.id, plan_id=plan_id)
    if plan.status not in _CONFIRMABLE:
        raise ConflictError("Only draft or pending plans can be deleted")
    db.delete(plan)
    db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
