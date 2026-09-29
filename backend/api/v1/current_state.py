from __future__ import annotations

from fastapi import APIRouter

from backend.api.deps import CurrentUser, DBSession
from backend.schemas.client_contract import ClientCurrentState
from backend.schemas.current_state import CurrentStateUpdate
from backend.services.client_view import current_state_to_client
from backend.services.current_state import recompute_current_state, update_overrides

router = APIRouter(prefix="/current-state", tags=["current-state"])


@router.get("", response_model=ClientCurrentState)
def get_current_state(user: CurrentUser, db: DBSession) -> ClientCurrentState:
    """Recompute and return the projection of the user's present."""

    return current_state_to_client(recompute_current_state(db, user.id))


@router.post("/refresh", response_model=ClientCurrentState)
def refresh(user: CurrentUser, db: DBSession) -> ClientCurrentState:
    return current_state_to_client(recompute_current_state(db, user.id))


@router.patch("", response_model=ClientCurrentState)
def patch(payload: CurrentStateUpdate, user: CurrentUser, db: DBSession) -> ClientCurrentState:
    return current_state_to_client(update_overrides(db, user.id, payload))
