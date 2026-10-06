"""Arq task functions.

Tasks must be idempotent and safe to retry. The replan-trigger drain is the
worker's first real job (D-024's "real caller"): ingestion marks users dirty
in Redis (best-effort, sync) and the cron below drains the set and evaluates
the trigger engine per user. Cron poll granularity plus the engine's
per-signature idempotence provide the debounce; a crashed drain just waits
for the user's next event.

The materials tasks (D-033) follow the same shape: upload enqueues
``extract_material`` (best-effort — Redis being down must not fail the
upload), and ``drain_pending_extractions`` sweeps files stuck in
``uploaded``/``extraction_failed`` as the reliability net for the explicit
user action that started them.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_, select

from backend.adapters.model_provider import get_model_provider
from backend.core.errors import StorageError
from backend.db.base import utcnow
from backend.db.session import session_scope
from backend.models.agent import AgentRun
from backend.models.data_lifecycle import DataOperation
from backend.models.enums import DataOperationKind, DataOperationStatus
from backend.models.file import FileObject
from backend.services.agent_runner import (
    execute_run,
    queue_proactive_run,
    reclaim_expired_runs,
    recover_pending_actions,
    sweep_pending_actions,
)
from backend.services.data_executor import run_deletion
from backend.services.data_exports import expire_ready_exports, run_export
from backend.services.material_ingestion import (
    consent_enabled,
    embed_pending_chunks,
    run_extraction,
)
from backend.services.replan_triggers import evaluate_replan_triggers
from backend.services.storage import get_storage
from backend.services.storage_orphans import (
    claim_due_storage_orphans,
    fail_storage_orphan,
    release_storage_orphan,
)
from backend.worker.enqueue import drain_dirty_users

logger = logging.getLogger(__name__)


async def ping(ctx: dict[str, Any], message: str = "pong") -> dict[str, Any]:
    """Trivial task used to verify Redis -> Arq -> task execution."""

    return {"message": message, "job_try": ctx.get("job_try", 1)}


def _provider_or_none() -> Any | None:
    """Provider construction must never take the run down with it: an
    unconfigured provider degrades the run to the deterministic path."""

    try:
        return get_model_provider()
    except Exception:
        logger.warning("Model provider unavailable; runs degrade deterministically")
        return None


async def execute_agent_run(ctx: dict[str, Any] | None, run_id: str) -> dict[str, Any]:
    """Execute one agent run end-to-end (lease-claimed, settled, audited)."""

    with session_scope() as session:
        run = await execute_run(session, run_id=uuid.UUID(run_id), provider=_provider_or_none())
        if run is None:
            return {"run_id": run_id, "skipped": "not_claimable"}
        return {"run_id": run_id, "status": run.status}


# A QUEUED run whose enqueue was lost gets picked up after this grace (the
# normal enqueued path always wins the atomic claim before the cron fires).
_RUN_GRACE = timedelta(seconds=60)


async def sweep_agent_runtime(ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    """Cron reliability net for the whole agent runtime (§3.2/§5.1):

    - settle PENDING TTLs and EXECUTING rows with expired leases;
    - re-dispatch CONFIRMED/FAILED_RETRYABLE rows (atomic claims);
    - reclaim RUNNING runs with expired leases (watchdog);
    - execute stale QUEUED runs (lost enqueues).
    """

    summary: dict[str, Any] = {}
    with session_scope() as session:
        summary.update(sweep_pending_actions(session))
        summary.update(reclaim_expired_runs(session))
        stale_ids = list(
            session.scalars(
                select(AgentRun.id)
                .where(
                    AgentRun.status == "QUEUED",
                    AgentRun.created_at < datetime.now(UTC) - _RUN_GRACE,
                )
                .limit(20)
            )
        )
    summary["redispatched"] = await recover_pending_actions_by_session()
    for run_id in stale_ids:
        try:
            await execute_agent_run(None, str(run_id))
        except Exception:
            logger.exception("Stale run execution failed", extra={"run_id": str(run_id)})
    summary["stale_runs"] = len(stale_ids)
    return summary


async def recover_pending_actions_by_session() -> int:
    with session_scope() as session:
        return await recover_pending_actions(session, provider=_provider_or_none())


async def drain_trigger_evaluation(ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    """Evaluate replan triggers for every dirty user (cron, every 30s).

    A3: a fired trigger ALSO queues a proactive agent run
    (``invocation_kind=proactive_trigger``; one run per trigger signature,
    ever). The direct enqueue below is best-effort — the runtime sweep
    re-claims any QUEUED run whose enqueue was lost (60s grace), so a Redis
    hiccup delays the notification but never drops it."""

    users = drain_dirty_users()
    suggestions: list[str] = []
    queued_runs: list[str] = []
    for user_id in users:
        try:
            with session_scope() as session:
                suggestion = evaluate_replan_triggers(session, user_id=uuid.UUID(user_id))
                if suggestion is None:
                    continue
                suggestions.append(str(suggestion.id))
                signature = suggestion.basis.get("trigger_signature")
                if not isinstance(signature, str):
                    continue
                run = queue_proactive_run(
                    session,
                    user_id=uuid.UUID(user_id),
                    trigger_kind="replan_trigger",
                    trigger_signature=signature,
                )
                if run is not None:
                    queued_runs.append(str(run.id))
        except Exception:
            # One user's failure must not block the rest; the dirty marker is
            # already consumed, so recovery waits for that user's next event.
            logger.exception("Trigger evaluation failed", extra={"user_id": user_id})
    # After commit: hand the runs to a worker now instead of waiting out the
    # sweep's grace window. ctx["redis"] is the worker's own ArqRedis pool.
    pool = ctx.get("redis") if ctx is not None else None
    if pool is not None:
        for run_id in queued_runs:
            try:
                await pool.enqueue_job("execute_agent_run", run_id)
            except Exception:  # pragma: no cover - sweep is the net
                logger.warning("Proactive run enqueue failed; sweep will claim it")
    return {
        "evaluated": len(users),
        "suggestions": suggestions,
        "proactive_runs": queued_runs,
    }


async def extract_material(ctx: dict[str, Any] | None, file_id: str) -> dict[str, Any]:
    """Extract + scan one file's chunks; embed if the course opted in."""

    with session_scope() as session:
        obj = session.get(FileObject, uuid.UUID(file_id))
        if obj is None:
            return {"file_id": file_id, "skipped": "file_not_found"}
        course_name = obj.course_name
        user_id = obj.user_id
        result = run_extraction(session, uuid.UUID(file_id), get_storage())
        if (
            result.get("status") == "extracted"
            and course_name is not None
            and consent_enabled(session, user_id, course_name)
        ):
            embed = await embed_pending_chunks(
                session,
                get_model_provider(),
                user_id,
                course_name,
                file_id=uuid.UUID(file_id),
            )
            result["embedded"] = embed.get("embedded", 0)
        return result


async def embed_course_backfill(
    ctx: dict[str, Any] | None, user_id: str, course_name: str
) -> dict[str, Any]:
    """Embed all pending clean chunks of a course after opt-in."""

    with session_scope() as session:
        return await embed_pending_chunks(
            session, get_model_provider(), uuid.UUID(user_id), course_name
        )


# Grace window before the cron retries an upload whose initial enqueue was
# lost: wide enough that the normal (enqueued) path always wins the race.
_RETRY_GRACE = timedelta(seconds=60)
_MAX_RETRIES = 10


async def drain_pending_extractions(ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    """Sweep course files stuck without extraction (cron, every 30s)."""

    cutoff = datetime.now(UTC) - _RETRY_GRACE
    processed = 0
    try:
        with session_scope() as session:
            file_ids = list(
                session.scalars(
                    select(FileObject.id).where(
                        FileObject.course_name.is_not(None),
                        FileObject.status.in_(("uploaded", "extraction_failed")),
                        FileObject.updated_at < cutoff,
                    )
                )
            )
        for file_id in file_ids:
            try:
                await extract_material(None, str(file_id))
                processed += 1
            except Exception:
                logger.exception("Extraction retry failed", extra={"file_id": str(file_id)})
                with session_scope() as session:
                    obj = session.get(FileObject, file_id)
                    if obj is not None:
                        retries = int(obj.file_metadata.get("extraction_retries", 0)) + 1
                        obj.file_metadata = {**obj.file_metadata, "extraction_retries": retries}
                        if retries >= _MAX_RETRIES:
                            obj.status = "unsupported_type"
                            obj.file_metadata = {
                                **obj.file_metadata,
                                "extraction_note": "retry budget exhausted",
                            }
                        session.flush()
    except Exception:
        logger.exception("Pending-extraction sweep failed")
    return {"processed": processed}


async def drain_storage_orphans(ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    """Retry object deletions whose DB rows are already gone (A-draft §2.5).

    Membership lives in the durable ``storage_orphan_keys`` ledger (the
    slice-3 cutover): rows are claimed FOR UPDATE SKIP LOCKED with a lease,
    failures walk the frozen backoff ladder, and success deletes the row.
    The cron's cadence is the wake — Redis holds nothing for this flow.
    """

    storage = get_storage()
    deleted = 0
    with session_scope() as session:
        for orphan in claim_due_storage_orphans(session, limit=100):
            key = orphan.storage_key
            try:
                row_exists = session.scalar(
                    select(FileObject.id).where(FileObject.storage_key == key)
                )
                if row_exists is not None:
                    # Keys embed a uuid and are never reused; if a live row
                    # shows up under a supposedly deleted key, dropping the
                    # marker beats looping forever.
                    logger.warning("Orphan key %r has a live row; dropping marker", key)
                    release_storage_orphan(session, key)
                    continue
                storage.delete(key)
                deleted += 1
                release_storage_orphan(session, key)
            except Exception as exc:
                logger.warning("Orphan object delete failed for %r", key, exc_info=True)
                fail_storage_orphan(
                    session, orphan.id, error_summary=f"object delete failed: {type(exc).__name__}"
                )
    return {"deleted": deleted}


async def run_data_operation(ctx: dict[str, Any] | None, operation_id: str) -> dict[str, Any]:
    """Drive one accepted data operation as far as it can go right now.

    Deletions resume from the persisted phase checkpoint; a parked
    RETRY_WAIT operation comes back through the sweep when its earliest
    backoff gate passes. Redis only wakes work — the durable ledger is the
    truth (A-draft §2.5), so a lost enqueue costs latency, never an object.
    """

    storage = get_storage()
    redis_pool = ctx.get("redis") if ctx is not None else None
    with session_scope() as session:
        operation = session.get(DataOperation, uuid.UUID(operation_id))
        if operation is None:
            return {"operation_id": operation_id, "skipped": "not_found"}
        if operation.kind == DataOperationKind.DELETION:
            run_deletion(session, operation, storage=storage, redis=redis_pool)
        else:
            try:
                run_export(session, operation, storage=storage)
            except StorageError:
                # Transient staging failure: park briefly; the sweep retries.
                operation.status = DataOperationStatus.RETRY_WAIT
                operation.next_retry_at = utcnow() + timedelta(seconds=30)
                session.flush()
        return {"operation_id": operation_id, "status": operation.status.value}


# A RUNNING operation whose worker died re-enters the sweep after this grace
# (mirrors the agent-runtime watchdog; item claims self-heal via the lease).
_OPERATION_RUN_GRACE = timedelta(seconds=60)


async def sweep_data_operations(ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    """Cron reliability net for the data lifecycle (every 30s).

    Dispatches QUEUED / due-RETRY_WAIT / stale-RUNNING operations and flips
    READY exports past their 24h staging TTL to EXPIRED, deleting the
    staged object (A-draft §3).
    """

    now = datetime.now(UTC)
    with session_scope() as session:
        due = list(
            session.execute(
                select(DataOperation.id).where(
                    or_(
                        DataOperation.status == DataOperationStatus.QUEUED,
                        and_(
                            DataOperation.status == DataOperationStatus.RETRY_WAIT,
                            or_(
                                DataOperation.next_retry_at.is_(None),
                                DataOperation.next_retry_at <= now,
                            ),
                        ),
                        and_(
                            DataOperation.status == DataOperationStatus.RUNNING,
                            DataOperation.updated_at < now - _OPERATION_RUN_GRACE,
                        ),
                    )
                )
            ).scalars()
        )
        expired = expire_ready_exports(session, storage=get_storage())
    pool = ctx.get("redis") if ctx is not None else None
    dispatched = 0
    if pool is not None:
        for operation_id in due:
            try:
                await pool.enqueue_job("run_data_operation", str(operation_id))
                dispatched += 1
            except Exception:  # pragma: no cover - next sweep retries
                logger.warning(
                    "Data operation dispatch failed",
                    extra={"operation_id": str(operation_id)},
                )
    return {"due": len(due), "dispatched": dispatched, "expired_exports": expired}
