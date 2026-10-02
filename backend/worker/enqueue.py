"""Best-effort dirty-user marker feeding the trigger worker (sync Redis).

The ingestion path runs on sync worker threads while arq pools are async;
instead of bridging event loops, ingestion marks users dirty in a plain
Redis set and the worker cron drains it. The cron's poll granularity is the
debounce (D-031 §2 "约 30s"), and the engine itself is idempotent per
trigger signature, so a late or repeated drain is harmless. Redis being
unavailable must never fail ingestion — marking is best-effort and simply
waits for the next event.
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


STORAGE_ORPHANS_KEY = "agenthu:storage:orphans"


def mark_storage_orphan(key: str) -> bool:
    """Record an object key whose DB row is gone but whose delete failed.

    The deletion order contract (D-033 §5) deletes rows transactionally and
    treats the object delete as best-effort; this marker is what makes
    "best-effort" eventually-consistent instead of eventually-forgotten.
    """

    try:
        _client().sadd(STORAGE_ORPHANS_KEY, key)
        return True
    except Exception:
        logger.warning("Could not mark storage orphan %r", key, exc_info=True)
        return False


def pop_storage_orphans(limit: int = 100) -> list[str]:
    """Pop up to ``limit`` object keys pending best-effort deletion."""

    try:
        popped = _client().spop(STORAGE_ORPHANS_KEY, count=limit) or []
    except Exception:
        logger.warning("Could not drain storage orphans", exc_info=True)
        return []
    return [value.decode() if isinstance(value, bytes) else str(value) for value in popped]
