from __future__ import annotations

import pytest
from arq import create_pool
from arq.connections import RedisSettings
from arq.worker import Worker

from backend.config import get_settings
from backend.worker.tasks import ping

pytestmark = [pytest.mark.integration, pytest.mark.worker]


async def test_ping_task_executes_through_redis() -> None:
    settings = get_settings()
    try:
        pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        await pool.ping()
    except Exception:
        pytest.skip("Redis is not available for worker tests")

    # Keep handle_signals at its default: arq's close() references POSIX-only
    # SIGUSR1 when signals are disabled, which breaks on Windows. Signal
    # registration itself degrades gracefully on Windows.
    worker = Worker(
        functions=[ping],
        redis_pool=pool,
        burst=True,
        poll_delay=0.05,
        queue_name="arq:queue",
    )
    try:
        job = await pool.enqueue_job("ping", "hello", _queue_name="arq:queue")
        assert job is not None
        await worker.async_run()
        result = await job.result(timeout=5)
        assert result == {"message": "hello", "job_try": 1}
    finally:
        await worker.close()
        await pool.aclose()
