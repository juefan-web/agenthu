from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from backend.api.deps import CurrentUser, DBSession
from backend.schemas.client_contract import (
    ClientFocusSession,
    FocusSessionCreate,
    FocusSessionUpdate,
)
from backend.services.client_view import focus_session_to_client
from backend.services.focus import create_focus_session, update_focus_session
from backend.services.lookup import get_focus_session, get_task

router = APIRouter(prefix="/focus-sessions", tags=["focus"])


@router.post("", response_model=ClientFocusSession, status_code=status.HTTP_201_CREATED)
def start(payload: FocusSessionCreate, user: CurrentUser, db: DBSession) -> ClientFocusSession:
    task = get_task(db, user_id=user.id, task_id=payload.task_id)
    focus = create_focus_session(db, user_id=user.id, task=task)
    return focus_session_to_client(focus)


@router.get("/{session_id}", response_model=ClientFocusSession)
def get_one(session_id: uuid.UUID, user: CurrentUser, db: DBSession) -> ClientFocusSession:
    focus = get_focus_session(db, user_id=user.id, session_id=session_id)
    return focus_session_to_client(focus)


@router.patch("/{session_id}", response_model=ClientFocusSession)
def update(
    session_id: uuid.UUID,
    payload: FocusSessionUpdate,
    user: CurrentUser,
    db: DBSession,
) -> ClientFocusSession:
    focus = get_focus_session(db, user_id=user.id, session_id=session_id)
    task = get_task(db, user_id=user.id, task_id=focus.task_id)
    focus = update_focus_session(db, user_id=user.id, focus=focus, task=task, payload=payload)
    return focus_session_to_client(focus)
