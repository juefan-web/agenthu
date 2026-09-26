"""Arq task functions.

Tasks must be idempotent and safe to retry. The M0 set is intentionally small:
one liveness task and one projection task that the API can enqueue.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from backend.db.session import session_scope

logger = logging.getLogger(__name__)


async def ping(ctx: dict[str, Any], message: str = "pong") -> dict[str, Any]:
    """Trivial task used to verify Redis -> Arq -> task execution."""

    return {"message": message, "job_try": ctx.get("job_try", 1)}


async def recompute_user_current_state(ctx: dict[str, Any], user_id: str) -> dict[str, Any]:
    """Recompute a user's CurrentState projection off the request path."""

    from backend.services.current_state import recompute_current_state

    parsed = uuid.UUID(str(user_id))
    with session_scope() as session:
        state = recompute_current_state(session, parsed)
        return {"user_id": str(parsed), "version": state.version}
