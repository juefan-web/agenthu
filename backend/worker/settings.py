"""Arq worker settings.

Run with::

    arq backend.worker.settings.WorkerSettings
"""

from __future__ import annotations

from arq.connections import RedisSettings

from backend.config import get_settings
from backend.worker.tasks import ping


def _redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(get_settings().redis_url)


class WorkerSettings:
    functions = [ping]
    redis_settings = _redis_settings()
    max_tries = 3
    job_timeout = 300
    keep_result = 3600
    health_check_interval = 30
