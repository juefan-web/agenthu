"""In-process fixed-window rate limiter for unauthenticated endpoints.

Login and registration are brute-forceable by design (they accept arbitrary
credentials), so they need a per-source throttle. This implementation is
deliberately simple: a sliding-window counter per ``(bucket, client IP)`` key,
kept in process memory. The M0 API runs as a single uvicorn worker, which this
covers; when the API is deployed with multiple workers or behind a shared
gateway, the ``hit`` call is the seam to swap in a Redis-backed limiter.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque


class RateLimiter:
    """Sliding-window limiter: at most ``max_requests`` per ``window_seconds``."""

    def __init__(self, max_requests: int, window_seconds: float) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def hit(self, key: str, *, now: float | None = None) -> bool:
        """Register a request and report whether it is within the limit.

        Returns ``True`` when allowed, ``False`` when the key is over the limit.
        Over-limit attempts still refresh nothing, so the window slides past
        them once the oldest allowed hit ages out.
        """

        if self.max_requests <= 0:  # Explicitly disabled.
            return True
        current = time.monotonic() if now is None else now
        window_start = current - self.window_seconds
        hits = self._hits[key]
        while hits and hits[0] <= window_start:
            hits.popleft()
        if len(hits) >= self.max_requests:
            return False
        hits.append(current)
        return True

    def retry_after(self, key: str, *, now: float | None = None) -> int:
        """Seconds until the oldest hit leaves the window (for Retry-After)."""

        current = time.monotonic() if now is None else now
        hits = self._hits.get(key)
        if not hits:
            return 0
        return max(0, int(hits[0] + self.window_seconds - current) + 1)
