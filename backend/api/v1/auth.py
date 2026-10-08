from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select

from backend.api.deps import CurrentUser, DBSession
from backend.config import get_settings
from backend.core.errors import AuthenticationError, ConflictError, RateLimitError
from backend.core.proxy import client_ip
from backend.core.rate_limit import RateLimiter
from backend.core.security import create_access_token, hash_password, verify_password
from backend.models.user import User
from backend.schemas.user import LoginRequest, Token, UserCreate, UserRead

router = APIRouter(prefix="/auth", tags=["auth"])

# One limiter instance per process, shared by register/login/token: they all
# accept arbitrary credentials, so they share the same brute-force budget.
_auth_limiter = RateLimiter(
    max_requests=get_settings().auth_rate_limit_max,
    window_seconds=get_settings().auth_rate_limit_window_seconds,
)


def _enforce_rate_limit(request: Request) -> None:
    source_ip = client_ip(request)
    if not _auth_limiter.hit(f"auth:{source_ip}"):
        raise RateLimitError(
            "Too many authentication attempts; try again later",
            headers={
                "Retry-After": str(
                    _auth_limiter.retry_after(f"auth:{source_ip}"),
                )
            },
        )


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    # Constant-work hash so "unknown email" and "wrong password" are
    # indistinguishable by timing (user-enumeration hardening).
    return hash_password("timing-equalizer-dummy-password")


def _issue_token(user: User) -> Token:
    settings = get_settings()
    token = create_access_token(str(user.id))
    return Token(access_token=token, expires_in=settings.access_token_expire_minutes * 60)


RateLimited = Annotated[None, Depends(_enforce_rate_limit)]


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate, request: Request, db: DBSession, _: RateLimited) -> User:
    # Hash before the existence check so an already-registered email and a
    # fresh one take comparable time (enumeration hardening).
    hashed = hash_password(payload.password)
    existing = db.scalar(select(User).where(User.email == payload.email))
    if existing is not None:
        raise ConflictError("Email is already registered")
    user = User(
        email=payload.email,
        display_name=payload.display_name,
        hashed_password=hashed,
    )
    db.add(user)
    db.flush()
    return user


@router.post("/login", response_model=Token)
def login(
    payload: LoginRequest,
    request: Request,
    db: DBSession,
    _: Annotated[None, Depends(_enforce_rate_limit)],
) -> Token:
    user = db.scalar(select(User).where(User.email == payload.email))
    hashed = user.hashed_password if user is not None else _dummy_hash()
    if not verify_password(payload.password, hashed) or user is None:
        raise AuthenticationError("Invalid email or password")
    if not user.is_active:
        raise AuthenticationError("User is inactive")
    return _issue_token(user)


@router.post("/token", response_model=Token, include_in_schema=True)
def login_form(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    request: Request,
    db: DBSession,
    _: Annotated[None, Depends(_enforce_rate_limit)],
) -> Token:
    """OAuth2 password grant form, used by the OpenAPI 'Authorize' button."""

    user = db.scalar(select(User).where(User.email == form_data.username.strip().lower()))
    hashed = user.hashed_password if user is not None else _dummy_hash()
    if not verify_password(form_data.password, hashed) or user is None:
        raise AuthenticationError("Invalid email or password")
    if not user.is_active:
        raise AuthenticationError("User is inactive")
    return _issue_token(user)


@router.get("/me", response_model=UserRead)
def me(user: CurrentUser) -> User:
    return user
