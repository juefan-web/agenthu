"""Arq worker settings.

Run with::

    arq backend.worker.settings.WorkerSettings
"""

from __future__ import annotations

from arq import cron
from arq.connections import RedisSettings

from backend.config import get_settings
from backend.worker.tasks import (
    drain_pending_extractions,
    drain_storage_orphans,
    drain_trigger_evaluation,
    embed_course_backfill,
    extract_material,
    ping,
)


def _redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(get_settings().redis_url)


class WorkerSettings:
    functions = [
        ping,
        drain_trigger_evaluation,
        extract_material,
        embed_course_backfill,
        drain_pending_extractions,
        drain_storage_orphans,
    ]
    cron_jobs = [
        # Debounce for the trigger engine (D-031 §2: ~30s per user): poll
        # granularity plus the engine's per-signature idempotence.
        cron(drain_trigger_evaluation, second={0, 30}, unique=True, timeout=60),
        # Reliability nets for the materials pipeline (D-033): lost
        # enqueues and best-effort object deletes both get retried.
        cron(drain_pending_extractions, second={0, 30}, unique=True, timeout=120),
        cron(drain_storage_orphans, minute=5, unique=True, timeout=60),
    ]
    redis_settings = _redis_settings()
    max_tries = 3
    job_timeout = 300
    keep_result = 3600
    health_check_interval = 30
