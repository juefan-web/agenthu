"""Arq worker settings.

Run with::

    arq backend.worker.settings.WorkerSettings
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from arq import cron
from arq.connections import RedisSettings

from backend.config import get_settings
from backend.core.telemetry import (
    configure_telemetry,
    instrument_outbound_clients,
    shutdown_telemetry,
    traced_job,
)
from backend.worker.tasks import (
    drain_pending_extractions,
    drain_storage_orphans,
    drain_trigger_evaluation,
    embed_course_backfill,
    execute_agent_run,
    extract_material,
    ping,
    run_data_operation,
    sweep_agent_runtime,
    sweep_data_operations,
)


def _redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(get_settings().redis_url)


# P0-5 slice 1: every arq execution is the "worker attempt" layer of the OTel
# chain — wrap once here (functools.wraps keeps the names arq's cron
# uniqueness keys derive from) so tasks and crons share one span shape.
_traced_ping = traced_job(ping)
_traced_drain_triggers = traced_job(drain_trigger_evaluation)
_traced_extract_material = traced_job(extract_material)
_traced_embed_backfill = traced_job(embed_course_backfill)
_traced_drain_extractions = traced_job(drain_pending_extractions)
_traced_drain_orphans = traced_job(drain_storage_orphans)
_traced_execute_run = traced_job(execute_agent_run)
_traced_sweep_runtime = traced_job(sweep_agent_runtime)
_traced_run_operation = traced_job(run_data_operation)
_traced_sweep_operations = traced_job(sweep_data_operations)


async def _on_startup(ctx: dict[str, Any]) -> None:
    provider = configure_telemetry("agenthu-worker")
    if provider is not None:
        instrument_outbound_clients(provider)


async def _on_shutdown(ctx: dict[str, Any]) -> None:
    shutdown_telemetry()


class WorkerSettings:
    on_startup: Callable[[dict[str, Any]], Awaitable[None]] = _on_startup
    on_shutdown: Callable[[dict[str, Any]], Awaitable[None]] = _on_shutdown
    functions = [
        _traced_ping,
        _traced_drain_triggers,
        _traced_extract_material,
        _traced_embed_backfill,
        _traced_drain_extractions,
        _traced_drain_orphans,
        _traced_execute_run,
        _traced_sweep_runtime,
        _traced_run_operation,
        _traced_sweep_operations,
    ]
    cron_jobs = [
        # Debounce for the trigger engine (D-031 §2: ~30s per user): poll
        # granularity plus the engine's per-signature idempotence.
        cron(_traced_drain_triggers, second={0, 30}, unique=True, timeout=60),
        # Reliability nets for the materials pipeline (D-033): lost
        # enqueues and best-effort object deletes both get retried.
        cron(_traced_drain_extractions, second={0, 30}, unique=True, timeout=120),
        cron(_traced_drain_orphans, minute=5, unique=True, timeout=60),
        # Agent runtime reliability net (D-034 §3.2/§5.1): lease watchdogs,
        # TTL expiry, lost-enqueue QUEUED runs, pending re-dispatch.
        cron(_traced_sweep_runtime, second={0, 30}, unique=True, timeout=120),
        # Data lifecycle reliability net (P0-3 slice 2): dispatch accepted
        # operations, retry parked ones, expire 24h export staging.
        cron(_traced_sweep_operations, second={0, 30}, unique=True, timeout=120),
    ]
    redis_settings = _redis_settings()
    max_tries = 3
    job_timeout = 300
    keep_result = 3600
    health_check_interval = 30
