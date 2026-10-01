"""Arq task functions.

Tasks must be idempotent and safe to retry. The replan-trigger drain is the
worker's first real job (D-024's "real caller"): ingestion marks users dirty
in Redis (best-effort, sync) and the cron below drains the set and evaluates
the trigger engine per user. Cron poll granularity plus the engine's
per-signature idempotence provide the debounce; a crashed drain just waits
for the user's next event.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from backend.db.session import session_scope
from backend.services.replan_triggers import evaluate_replan_triggers
from backend.worker.enqueue import drain_dirty_users

logger = logging.getLogger(__name__)


async def ping(ctx: dict[str, Any], message: str = "pong") -> dict[str, Any]:
    """Trivial task used to verify Redis -> Arq -> task execution."""

    return {"message": message, "job_try": ctx.get("job_try", 1)}


async def drain_trigger_evaluation(ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    """Evaluate replan triggers for every dirty user (cron, every 30s)."""

    users = drain_dirty_users()
    suggestions: list[str] = []
    for user_id in users:
        try:
            with session_scope() as session:
                suggestion = evaluate_replan_triggers(session, user_id=uuid.UUID(user_id))
            if suggestion is not None:
                suggestions.append(str(suggestion.id))
        except Exception:
            # One user's failure must not block the rest; the dirty marker is
            # already consumed, so recovery waits for that user's next event.
            logger.exception("Trigger evaluation failed", extra={"user_id": user_id})
    return {"evaluated": len(users), "suggestions": suggestions}
