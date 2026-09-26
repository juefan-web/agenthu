from __future__ import annotations

from fastapi import APIRouter

from backend.api.deps import CurrentUser, DBSession
from backend.schemas.current_state import CurrentStateRead, CurrentStateUpdate
from backend.services.current_state import recompute_current_state, update_overrides

router = APIRouter(prefix="/current-state", tags=["current-state"])


@router.get("", response_model=CurrentStateRead)
def get_current_state(user: CurrentUser, db: DBSession) -> CurrentStateRead:
    """Recompute and return the projection of the user's present."""

    return recompute_current_state(db, user.id)


@router.post("/refresh", response_model=CurrentStateRead)
def refresh(user: CurrentUser, db: DBSession) -> CurrentStateRead:
    return recompute_current_state(db, user.id)


@router.patch("", response_model=CurrentStateRead)
def patch(payload: CurrentStateUpdate, user: CurrentUser, db: DBSession) -> CurrentStateRead:
    return update_overrides(db, user.id, payload)
