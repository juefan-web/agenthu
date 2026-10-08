"""Shared Arq connection pool and the traced enqueue seam for jobs."""

from __future__ import annotations

from typing import Any

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from arq.jobs import Job
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from backend.config import get_settings

_pool: ArqRedis | None = None


async def get_arq_pool() -> ArqRedis:
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    return _pool


async def close_arq_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None


async def enqueue(
    pool: ArqRedis,
    function: str,
    *args: Any,
    _job_id: str | None = None,
) -> Job | None:
    """Enqueue a job that continues the current trace across processes.

    The api→worker hop has no HTTP headers for the propagator to ride on, so
    the producer's traceparent travels as an ordinary job kwarg and
    ``traced_job`` extracts it as the worker span's parent (P0-5 slice 3) —
    one trace id from the HTTP span down to the worker attempt. With no
    active span the kwarg is omitted and the worker span stays a root, the
    pre-slice-3 semantics. Keyword arguments are deliberately not forwarded:
    every call site is positional-args-only today, and an open ``**kwargs``
    here would let a future caller smuggle a second ``_traceparent`` past
    the seam.

    Only matching worker versions may consume these jobs — an older
    ``traced_job`` would forward the kwarg into task signatures — so api and
    worker upgrade together (compose rebuilds them as one stack).
    """

    # Any-valued so the keyword splat below satisfies arq's datetime/timedelta
    # reserved parameters under strict type checking (the only key ever set
    # here is the traceparent string).
    kwargs: dict[str, Any] = {}
    carrier: dict[str, str] = {}
    TraceContextTextMapPropagator().inject(carrier)
    traceparent = carrier.get("traceparent")
    if traceparent is not None:
        kwargs["_traceparent"] = traceparent
    return await pool.enqueue_job(function, *args, _job_id=_job_id, **kwargs)
