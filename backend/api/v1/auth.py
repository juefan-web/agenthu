from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select

from backend.api.deps import CurrentUser, DBSession
from backend.config import get_settings
from backend.core.errors import AuthenticationError, ConflictError
from backend.core.security import create_access_token, hash_password, verify_password
from backend.models.user import User
from backend.schemas.user import LoginRequest, Token, UserCreate, UserRead

router = APIRouter(prefix="/auth", tags=["auth"])


def _issue_token(user: User) -> Token:
    settings = get_settings()
    token = create_access_token(str(user.id))
    return Token(access_token=token, expires_in=settings.access_token_expire_minutes * 60)


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate, db: DBSession) -> User:
    existing = db.scalar(select(User).where(User.email == payload.email))
    if existing is not None:
        raise ConflictError("Email is already registered")
    user = User(
        email=payload.email,
        display_name=payload.display_name,
        hashed_password=hash_password(payload.password),
    )
    db.add(user)
    db.flush()
    return user


@router.post("/login", response_model=Token)
def login(payload: LoginRequest, db: DBSession) -> Token:
    user = db.scalar(select(User).where(User.email == payload.email))
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise AuthenticationError("Invalid email or password")
    if not user.is_active:
        raise AuthenticationError("User is inactive")
    return _issue_token(user)


@router.post("/token", response_model=Token, include_in_schema=True)
def login_form(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DBSession,
) -> Token:
    """OAuth2 password grant form, used by the OpenAPI 'Authorize' button."""

    user = db.scalar(select(User).where(User.email == form_data.username.strip().lower()))
    if user is None or not verify_password(form_data.password, user.hashed_password):
        raise AuthenticationError("Invalid email or password")
    if not user.is_active:
        raise AuthenticationError("User is inactive")
    return _issue_token(user)


@router.get("/me", response_model=UserRead)
def me(user: CurrentUser) -> User:
    return user
