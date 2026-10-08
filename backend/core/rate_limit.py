"""Redis-backed sliding-window rate limiter for unauthenticated endpoints.

Login, registration and deletion-recovery are brute-forceable by design (they
accept arbitrary credentials or one-time handles), so they need a per-source
throttle. The M5 API runs as several processes against one Redis, so the
bucket ledger lives there and every process counts against the same budget
(P0-5 ruling 4: the Redis ledger is the single source of truth; clients and
UIs never keep a second count).

The ``hit``/``retry_after`` seam keeps its shape; the sliding-window
semantics are the same as the former in-process implementation, computed
atomically by a Lua script against the Redis server clock (no client clock
skew). Keys are namespaced under ``rl:`` to stay clear of arq's keys.

Fail-closed (ops contract §6): when Redis is unreachable — bounded by
``RATE_LIMIT_REDIS_TIMEOUT_SECONDS`` — both methods raise
:class:`RateLimitUnavailableError`, which surfaces as a distinct 503 facet
(``rate_limit_unavailable``). Never a silent allow (fail-open would
re-enable brute force across processes), never a disguised 429.
"""

from __future__ import annotations

import threading
import uuid

import redis
from redis.commands.core import Script
from redis.exceptions import RedisError

from backend.config import get_settings
from backend.core.errors import RateLimitUnavailableError

#: Both scripts take KEYS[1] = bucket zset and ARGV[1] = window milliseconds;
#: the clock is read server-side (TIME), so all processes share one clock.
_HIT_SCRIPT = """
local t = redis.call('TIME')
local now = t[1] * 1000 + math.floor(t[2] / 1000)
local window = tonumber(ARGV[1])
local max = tonumber(ARGV[2])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - window)
local count = redis.call('ZCARD', KEYS[1])
if count >= max then
    return 0
end
redis.call('ZADD', KEYS[1], now, ARGV[3])
redis.call('PEXPIRE', KEYS[1], window)
return 1
"""

_RETRY_AFTER_SCRIPT = """
local t = redis.call('TIME')
local now = t[1] * 1000 + math.floor(t[2] / 1000)
local window = tonumber(ARGV[1])
local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
if oldest[2] == nil then
    return 0
end
local seconds = math.floor((tonumber(oldest[2]) + window - now) / 1000) + 1
if seconds < 0 then
    return 0
end
return seconds
"""

_client: redis.Redis | None = None
_client_lock = threading.Lock()


def default_client() -> redis.Redis:
    """Process-wide client (lazy; one connection pool, thread-safe)."""

    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                settings = get_settings()
                timeout = settings.rate_limit_redis_timeout_seconds
                _client = redis.Redis.from_url(
                    settings.redis_url,
                    socket_connect_timeout=timeout,
                    socket_timeout=timeout,
                )
    return _client


class RateLimiter:
    """Sliding-window limiter: at most ``max_requests`` per ``window_seconds``.

    ``namespace`` isolates test ledgers from the production ``rl:`` one;
    ``client`` overrides the process-wide Redis connection (also for tests).
    """

    def __init__(
        self,
        max_requests: int,
        window_seconds: float,
        *,
        client: redis.Redis | None = None,
        namespace: str = "rl",
    ) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._namespace = namespace
        self._redis = client
        self._hit_script: Script | None = None
        self._retry_script: Script | None = None

    def _conn(self) -> redis.Redis:
        return self._redis if self._redis is not None else default_client()

    def _key(self, key: str) -> str:
        return f"{self._namespace}:{key}"

    def hit(self, key: str) -> bool:
        """Register a request and report whether it is within the limit.

        Returns ``True`` when allowed, ``False`` when the key is over the
        limit. Over-limit attempts register nothing, so the window slides
        past them once the oldest allowed hit ages out.
        """

        if self.max_requests <= 0:  # Explicitly disabled.
            return True
        hit_script = self._hit_script
        if hit_script is None:
            hit_script = self._conn().register_script(_HIT_SCRIPT)
            self._hit_script = hit_script
        try:
            allowed = hit_script(
                keys=[self._key(key)],
                args=[int(self.window_seconds * 1000), self.max_requests, uuid.uuid4().hex],
            )
        except RedisError as exc:
            raise RateLimitUnavailableError(
                "Rate limiter backend is unavailable; failing closed"
            ) from exc
        return bool(allowed)

    def retry_after(self, key: str) -> int:
        """Seconds until the oldest hit leaves the window (for Retry-After)."""

        retry_script = self._retry_script
        if retry_script is None:
            retry_script = self._conn().register_script(_RETRY_AFTER_SCRIPT)
            self._retry_script = retry_script
        try:
            seconds = retry_script(keys=[self._key(key)], args=[int(self.window_seconds * 1000)])
        except RedisError as exc:
            raise RateLimitUnavailableError(
                "Rate limiter backend is unavailable; failing closed"
            ) from exc
        # Script.__call__ is typed for async clients too; ours is sync, so the
        # result is the Lua return value — an int (never an awaitable).
        return seconds if isinstance(seconds, int) else 0
