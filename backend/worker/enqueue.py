"""Best-effort dirty-user marker feeding the trigger worker (sync Redis).

The ingestion path runs on sync worker threads while arq pools are async;
instead of bridging event loops, ingestion marks users dirty in a plain
Redis set and the worker cron drains it. The cron's poll granularity is the
debounce (D-031 §2 "约 30s"), and the engine itself is idempotent per
trigger signature, so a late or repeated drain is harmless. Redis being
unavailable must never fail ingestion — marking is best-effort and simply
waits for the next event.

P0-3 slice 3 removed the storage-orphan marker set that used to live here:
object-delete membership moved to the durable ``storage_orphan_keys``
ledger (A-draft §2.5 — the destructive SPOP could lose keys on a crash).
This set survives only because trigger evaluation is idempotent per
signature; nothing destructive pops from it.
"""

from __future__ import annotations

import logging
import uuid

from redis import Redis

from backend.config import get_settings

logger = logging.getLogger(__name__)

DIRTY_USERS_KEY = "agenthu:trigger:dirty"
_CLIENT: Redis | None = None


def _client() -> Redis:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = Redis.from_url(
            get_settings().redis_url, socket_connect_timeout=2, socket_timeout=2
        )
    return _CLIENT


def mark_user_dirty(user_id: uuid.UUID | str) -> bool:
    """Record that a user's facts changed and triggers should be evaluated."""

    try:
        _client().sadd(DIRTY_USERS_KEY, str(user_id))
        return True
    except Exception:
        logger.warning("Could not mark user dirty for trigger evaluation", exc_info=True)
        return False


def drain_dirty_users(limit: int = 100) -> list[str]:
    """Pop up to ``limit`` user ids pending trigger evaluation."""

    try:
        popped = _client().spop(DIRTY_USERS_KEY, count=limit) or []
    except Exception:
        logger.warning("Could not drain dirty users for trigger evaluation", exc_info=True)
        return []
    return [value.decode() if isinstance(value, bytes) else str(value) for value in popped]
