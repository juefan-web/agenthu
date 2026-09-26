from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status
from sqlalchemy import func, select

from backend.api.deps import CurrentUser, DBSession, PaginationDep
from backend.core.errors import NotFoundError
from backend.models.goal import Goal
from backend.schemas.common import Page
from backend.schemas.goal import GoalCreate, GoalRead, GoalUpdate
from backend.services.lookup import get_goal

router = APIRouter(prefix="/goals", tags=["goals"])


@router.post("", response_model=GoalRead, status_code=status.HTTP_201_CREATED)
def create(payload: GoalCreate, user: CurrentUser, db: DBSession) -> Goal:
    goal = Goal(user_id=user.id, **payload.model_dump())
    db.add(goal)
    db.flush()
    return goal


@router.get("", response_model=Page[GoalRead])
def list_all(user: CurrentUser, db: DBSession, pagination: PaginationDep) -> Page[GoalRead]:
    conditions = [Goal.user_id == user.id]
    total = db.scalar(select(func.count()).select_from(Goal).where(*conditions)) or 0
    stmt = (
        select(Goal)
        .where(*conditions)
        .order_by(Goal.priority.desc(), Goal.created_at.desc())
        .limit(pagination.limit)
        .offset(pagination.offset)
    )
    goals = list(db.scalars(stmt))
    return Page(
        items=[GoalRead.model_validate(goal) for goal in goals],
        total=int(total),
        limit=pagination.limit,
        offset=pagination.offset,
    )


@router.get("/{goal_id}", response_model=GoalRead)
def get_one(goal_id: uuid.UUID, user: CurrentUser, db: DBSession) -> Goal:
    return get_goal(db, user_id=user.id, goal_id=goal_id)


@router.patch("/{goal_id}", response_model=GoalRead)
def update(goal_id: uuid.UUID, payload: GoalUpdate, user: CurrentUser, db: DBSession) -> Goal:
    goal = get_goal(db, user_id=user.id, goal_id=goal_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(goal, field, value)
    db.flush()
    return goal


@router.delete("/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(goal_id: uuid.UUID, user: CurrentUser, db: DBSession) -> Response:
    goal = db.scalar(select(Goal).where(Goal.id == goal_id, Goal.user_id == user.id))
    if goal is None:
        raise NotFoundError("Goal not found")
    db.delete(goal)
    db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
