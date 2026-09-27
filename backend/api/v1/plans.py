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
from backend.schemas.client_contract import ClientPlan
from backend.schemas.common import Page
from backend.schemas.plan import (
    PlanCreate,
    PlanGenerateRequest,
    PlanItemUpdate,
    PlanRead,
    PlanReplanRequest,
)
from backend.services import permissions
from backend.services.client_view import plan_to_client
from backend.services.current_state import current_plan_for, recompute_current_state
from backend.services.lookup import ensure_owned_tasks, get_goal, get_plan
from backend.services.planner import (
    generate_plan,
    is_client_valid_plan,
    latest_open_plan,
    replan,
    start_of_today,
)

router = APIRouter(prefix="/plans", tags=["plans"])

_CONFIRMABLE = (PlanStatus.DRAFT, PlanStatus.PENDING_CONFIRMATION)
_CANCELLABLE = (PlanStatus.DRAFT, PlanStatus.PENDING_CONFIRMATION, PlanStatus.CONFIRMED)


def _client(plan: Plan) -> ClientPlan:
    return plan_to_client(PlanRead.model_validate(plan))


@router.post("", response_model=ClientPlan, status_code=status.HTTP_201_CREATED)
def create(payload: PlanCreate, user: CurrentUser, db: DBSession) -> ClientPlan:
    if payload.goal_id is not None:
        get_goal(db, user_id=user.id, goal_id=payload.goal_id)
    # P1: a plan item may not reference another user's task.
    task_ids = [item.task_id for item in payload.items if item.task_id is not None]
    ensure_owned_tasks(db, user_id=user.id, task_ids=task_ids)

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
    return _client(plan)


@router.post("/generate", response_model=ClientPlan, status_code=status.HTTP_201_CREATED)
def generate(payload: PlanGenerateRequest, user: CurrentUser, db: DBSession) -> ClientPlan:
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
    return _client(plan)


@router.get("/today", response_model=ClientPlan)
def today(user: CurrentUser, db: DBSession) -> ClientPlan:
    """Return the client's "today" plan.

    The confirmed plan is returned when present; otherwise a deterministic
    baseline plan is generated (pending confirmation) so the client always has
    something to display and confirm.
    """

    # /v1/plans/today must always satisfy the client's PlanSchema, so a manual
    # plan with task-less items is never served here.
    plan = current_plan_for(db, user.id)
    if plan is not None and not is_client_valid_plan(plan):
        plan = None
    if plan is None:
        # Reuse today's draft/pending proposal so repeated reads are stable, but
        # never a stale (cross-day) draft.
        plan = latest_open_plan(db, user.id, since=start_of_today())
    if plan is None:
        plan = generate_plan(db, user_id=user.id)
        recompute_current_state(db, user.id)
    return _client(plan)


@router.get("", response_model=Page[ClientPlan])
def list_all(
    user: CurrentUser,
    db: DBSession,
    pagination: PaginationDep,
    status_filter: Annotated[PlanStatus | None, Query(alias="status")] = None,
    goal_id: Annotated[uuid.UUID | None, Query()] = None,
) -> Page[ClientPlan]:
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
        items=[_client(plan) for plan in plans],
        total=int(total),
        limit=pagination.limit,
        offset=pagination.offset,
    )


@router.get("/{plan_id}", response_model=ClientPlan)
def get_one(plan_id: uuid.UUID, user: CurrentUser, db: DBSession) -> ClientPlan:
    return _client(get_plan(db, user_id=user.id, plan_id=plan_id))


@router.post("/{plan_id}/confirm", response_model=ClientPlan)
def confirm(plan_id: uuid.UUID, user: CurrentUser, db: DBSession) -> ClientPlan:
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
    return _client(plan)


@router.post("/{plan_id}/cancel", response_model=ClientPlan)
def cancel(plan_id: uuid.UUID, user: CurrentUser, db: DBSession) -> ClientPlan:
    plan = get_plan(db, user_id=user.id, plan_id=plan_id)
    if plan.status not in _CANCELLABLE:
        raise ConflictError(f"Plan in status {plan.status.value} cannot be cancelled")
    plan.status = PlanStatus.CANCELLED
    plan.cancelled_at = utcnow()
    db.flush()
    recompute_current_state(db, user.id)
    return _client(plan)


@router.post("/{plan_id}/replan", response_model=ClientPlan, status_code=status.HTTP_201_CREATED)
def replan_endpoint(
    plan_id: uuid.UUID, payload: PlanReplanRequest, user: CurrentUser, db: DBSession
) -> ClientPlan:
    new_plan = replan(
        db,
        user_id=user.id,
        plan_id=plan_id,
        reason=payload.reason,
        horizon_minutes=payload.horizon_minutes,
    )
    recompute_current_state(db, user.id)
    return _client(new_plan)


@router.patch("/{plan_id}/items/{item_id}", response_model=ClientPlan)
def update_item(
    plan_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: PlanItemUpdate,
    user: CurrentUser,
    db: DBSession,
) -> ClientPlan:
    plan = get_plan(db, user_id=user.id, plan_id=plan_id)
    item = next((candidate for candidate in plan.items if candidate.id == item_id), None)
    if item is None:
        raise ValidationError("Plan item not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    db.flush()
    recompute_current_state(db, user.id)
    return _client(plan)


@router.delete("/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(plan_id: uuid.UUID, user: CurrentUser, db: DBSession) -> Response:
    plan = get_plan(db, user_id=user.id, plan_id=plan_id)
    if plan.status not in _CONFIRMABLE:
        raise ConflictError("Only draft or pending plans can be deleted")
    db.delete(plan)
    db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
