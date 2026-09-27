"""Shared FastAPI dependencies."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Query, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.core.errors import AuthenticationError
from backend.core.security import decode_access_token
from backend.db.session import get_db
from backend.models.user import User
from backend.services.storage import ObjectStorage, get_storage

# Derived from the configured prefix so this OpenAPI metadata cannot drift from
# the real route again (frozen as /v1/auth/token, see DECISIONS.md D-018).
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{get_settings().api_v1_prefix}/auth/token",
    auto_error=False,
)

DBSession = Annotated[Session, Depends(get_db)]
TokenHeader = Annotated[str | None, Depends(oauth2_scheme)]
StorageDep = Annotated[ObjectStorage, Depends(get_storage)]


def get_current_user(
    request: Request,
    token: TokenHeader,
    db: DBSession,
) -> User:
    if not token:
        raise AuthenticationError("Authentication required")
    payload = decode_access_token(token)
    subject = payload.get("sub")
    try:
        user_id = uuid.UUID(str(subject))
    except (ValueError, TypeError) as exc:
        raise AuthenticationError("Invalid token subject") from exc

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("User not found or inactive")

    # Exposed to the audit middleware.
    request.state.user_id = user.id
    request.state.actor = "user"
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


@dataclass
class Pagination:
    limit: int
    offset: int


def get_pagination(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Pagination:
    return Pagination(limit=limit, offset=offset)


PaginationDep = Annotated[Pagination, Depends(get_pagination)]
