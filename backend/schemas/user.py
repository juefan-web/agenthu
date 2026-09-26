from __future__ import annotations

import uuid

from pydantic import BaseModel, Field, field_validator

from backend.schemas.common import ORMModel

_EMAIL_MAX = 320


class UserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=_EMAIL_MAX)
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=200)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        local, _, domain = normalized.partition("@")
        if not local or not domain or "." not in domain:
            raise ValueError("must be a valid email address")
        return normalized


class UserRead(ORMModel):
    id: uuid.UUID
    email: str
    display_name: str
    is_active: bool


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=_EMAIL_MAX)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
