"""Redis-backed sliding-window limiter semantics and failure facets (P0-5 §7).

These run against a real Redis (CI starts one; locally the dev stack's
`agenthu-redis-1`). The ledger is the single source of truth across
processes, so the sharing test pins the property the in-process version
could not offer, and the outage tests pin the fail-closed 503 facet.
"""

from __future__ import annotations

import time
import uuid

import pytest
import redis
from redis.exceptions import RedisError

from backend.core.errors import RateLimitUnavailableError
from backend.core.rate_limit import RateLimiter, default_client


def _redis_available() -> bool:
    try:
        default_client().ping()
    except RedisError:
        return False
    return True


requires_redis = pytest.mark.skipif(not _redis_available(), reason="Redis is not reachable")


def _fresh_namespace() -> str:
    return f"test:{uuid.uuid4().hex}"


def _dead_client() -> redis.Redis:
    # Port 1 is closed on every support surface; the tiny timeouts bound the
    # wait so the failure is fast, not hanging.
    return redis.Redis.from_url(
        "redis://127.0.0.1:1/0", socket_connect_timeout=0.2, socket_timeout=0.2
    )


@requires_redis
def test_allows_within_window_and_blocks_after() -> None:
    namespace = _fresh_namespace()
    limiter = RateLimiter(max_requests=2, window_seconds=30.0, namespace=namespace)
    assert limiter.hit("k") is True
    assert limiter.hit("k") is True
    assert limiter.hit("k") is False
    # The oldest of two hits leaves the window in at most window_seconds.
    assert 1 <= limiter.retry_after("k") <= 30


@requires_redis
def test_window_slides() -> None:
    limiter = RateLimiter(max_requests=2, window_seconds=1.0, namespace=_fresh_namespace())
    assert limiter.hit("k") is True
    assert limiter.hit("k") is True
    assert limiter.hit("k") is False
    time.sleep(1.1)
    # The first hit has aged out; the budget is one again.
    assert limiter.hit("k") is True


@requires_redis
def test_keys_do_not_share_budget() -> None:
    limiter = RateLimiter(max_requests=1, window_seconds=30.0, namespace=_fresh_namespace())
    assert limiter.hit("a") is True
    assert limiter.hit("a") is False
    assert limiter.hit("b") is True


@requires_redis
def test_separate_limiters_share_one_ledger() -> None:
    """The whole point of the slice: two instances (two processes) see one budget."""

    namespace = _fresh_namespace()
    first = RateLimiter(max_requests=2, window_seconds=30.0, namespace=namespace)
    second = RateLimiter(max_requests=2, window_seconds=30.0, namespace=namespace)
    assert first.hit("shared") is True
    assert second.hit("shared") is True
    assert first.hit("shared") is False
    assert second.hit("shared") is False


@requires_redis
def test_namespaces_are_isolated() -> None:
    limiter = RateLimiter(max_requests=1, window_seconds=30.0, namespace=_fresh_namespace())
    other = RateLimiter(max_requests=1, window_seconds=30.0, namespace=_fresh_namespace())
    assert limiter.hit("k") is True
    assert other.hit("k") is True


def test_disabled_when_max_zero_never_touches_backend() -> None:
    limiter = RateLimiter(
        max_requests=0, window_seconds=10.0, client=_dead_client(), namespace="rl"
    )
    assert all(limiter.hit("k") for _ in range(50))


def test_outage_fails_closed_with_distinct_facet() -> None:
    limiter = RateLimiter(
        max_requests=5, window_seconds=30.0, client=_dead_client(), namespace="rl"
    )
    with pytest.raises(RateLimitUnavailableError) as hit_exc:
        limiter.hit("k")
    assert hit_exc.value.status_code == 503
    assert hit_exc.value.code == "rate_limit_unavailable"
    with pytest.raises(RateLimitUnavailableError):
        limiter.retry_after("k")
