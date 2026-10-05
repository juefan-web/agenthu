from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    # Opaque owner handle for the independent data-lifecycle ledger (D-036 /
    # M5 A-draft §4): ledger rows key on this value with NO FK back to users,
    # so deleting the users row cannot CASCADE the ledger away and business
    # queries cannot join the ledger back to an identity. No server_default
    # on purpose: PG stores a normalized copy of the expression and alembic
    # would flag eternal textual drift; existing rows are backfilled
    # explicitly in migration e6d496a26f09.
    owner_handle: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        unique=True,
        default=lambda: uuid.uuid4().hex,
    )
    # Barrier generation (D-036 §8-1 / A-draft §2): bumped transactionally when
    # a destructive operation is confirmed; in-flight writers compare their
    # observed generation against this value before final writes.
    data_generation: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
