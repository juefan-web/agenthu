"""Keyset pagination (D-029) shared plumbing.

Cursor contract: an opaque base64url token wrapping the sort-key values of
the last row on a page. ``null``/absent means "first page or no more
pages" per direction — callers decide which by whether more rows exist.
The keys inside are the endpoint's actual ``ORDER BY`` (D-029's binding
rule: "键序与现有排序一致") — for tasks that is
``(deadline nulls last, created_at desc, id desc)``, for events
``(timestamp desc, id desc)``, so the frozen text's ``(created_at, id)``
parenthetical is superseded for tasks (it predates the deadline-first
ordering; the cursor is opaque so the client never sees the difference).
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from backend.core.errors import ValidationError


def encode_cursor(*parts: Any) -> str:
    """Opaque cursor: base64url(JSON array of the sort-key values)."""

    payload = json.dumps(list(parts), separators=(",", ":"), default=str).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def decode_cursor(cursor: str, expected_parts: int) -> tuple[str | None, ...]:
    """Inverse of :func:`encode_cursor`; anything malformed is a 422.

    The cursor is opaque to clients, so a client that minted one for
    another endpoint (or hand-crafted garbage) must fail loudly, not
    silently restart from the first page.
    """

    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = json.loads(base64.urlsafe_b64decode(padded.encode()))
        if not isinstance(raw, list) or len(raw) != expected_parts:
            raise ValueError("wrong part count")
        return tuple(None if part is None else str(part) for part in raw)
    except Exception as exc:
        raise ValidationError("Invalid pagination cursor") from exc


def keyset_page(
    session: Session,
    stmt: Select,
    *,
    limit: int,
    after: Any,
    key_of: Callable[[Any], tuple[Any, ...]],
) -> tuple[list[Any], str | None]:
    """Fetch one keyset page and the next cursor.

    ``stmt`` must already carry the full WHERE (filters + keyset
    "strictly after the cursor row" predicate) and the ORDER BY; ``after``
    is the sentinel predicate for "no cursor yet" (typically ``True``).
    Fetches limit+1 rows so ``next_cursor`` needs no COUNT: an extra row
    means a next page exists, keyed by the last row actually returned.
    """

    rows = list(session.scalars(stmt.limit(limit + 1)))
    has_more = len(rows) > limit
    page = rows[:limit]
    next_cursor = encode_cursor(*key_of(page[-1])) if has_more and page else None
    return page, next_cursor


def count_total(session: Session, stmt: Select) -> int:
    """COUNT over the same filters (offset path only — D-029 keeps total
    off the cursor path to avoid a per-page count)."""

    return int(session.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
