from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict


def normalize_naive_utc(value: datetime) -> datetime:
    """Treat a naive datetime as UTC (the single rule for every datetime input).

    Client timestamps must be timezone-aware ISO-8601; when one arrives naive
    anyway, labeling it UTC keeps stored values consistent instead of letting
    the database interpret local time (an 8-hour skew for Asia/Shanghai). This
    mirrors what ``EventCreate.timestamp`` has always done — it is now the
    contract for every datetime the API accepts.
    """

    return value if value.tzinfo else value.replace(tzinfo=UTC)


UTCDatetime = Annotated[datetime, AfterValidator(normalize_naive_utc)]


def _require_timezone(value: datetime) -> datetime:
    # Deadline is the ordering-critical field of the whole product; a silent
    # 8-hour skew is worse than a rejected request (D-028 narrows C4 for
    # deadlines specifically — other datetimes keep the lenient rule).
    if value.tzinfo is None:
        raise ValueError(
            "deadline must be timezone-aware ISO-8601 (include the UTC offset, "
            "e.g. +08:00); naive deadline values are rejected (D-028)"
        )
    return value


TzRequiredDatetime = Annotated[datetime, AfterValidator(_require_timezone)]


class ORMModel(BaseModel):
    """Base for schemas read directly from SQLAlchemy objects."""

    model_config = ConfigDict(from_attributes=True)


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, object] = {}


class ErrorResponse(BaseModel):
    error: ErrorBody
