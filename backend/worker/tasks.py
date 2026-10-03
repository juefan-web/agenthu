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

from sqlalchemy import select

from backend.adapters.model_provider import get_model_provider
from backend.db.session import session_scope
from backend.models.agent import AgentRun
from backend.models.file import FileObject
from backend.services.agent_runner import (
    execute_run,
    reclaim_expired_runs,
    recover_pending_actions,
    sweep_pending_actions,
)
from backend.services.material_ingestion import (
    consent_enabled,
    embed_pending_chunks,
    run_extraction,
)
from backend.services.replan_triggers import evaluate_replan_triggers
from backend.services.storage import get_storage
from backend.worker.enqueue import drain_dirty_users, mark_storage_orphan, pop_storage_orphans

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
    """Evaluate replan triggers for every dirty user (cron, every 30s)."""

    users = drain_dirty_users()
    suggestions: list[str] = []
    for user_id in users:
        try:
            with session_scope() as session:
                suggestion = evaluate_replan_triggers(session, user_id=uuid.UUID(user_id))
            if suggestion is not None:
                suggestions.append(str(suggestion.id))
        except Exception:
            # One user's failure must not block the rest; the dirty marker is
            # already consumed, so recovery waits for that user's next event.
            logger.exception("Trigger evaluation failed", extra={"user_id": user_id})
    return {"evaluated": len(users), "suggestions": suggestions}


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
    """Retry best-effort object deletions whose DB rows are already gone."""

    storage = get_storage()
    deleted = 0
    for key in pop_storage_orphans():
        try:
            with session_scope() as session:
                row_exists = session.scalar(
                    select(FileObject.id).where(FileObject.storage_key == key)
                )
            if row_exists is not None:
                # Keys embed a uuid and are never reused; if a live row shows
                # up under a supposedly deleted key, dropping the marker beats
                # looping forever.
                logger.warning("Orphan key %r has a live row; dropping marker", key)
                continue
            storage.delete(key)
            deleted += 1
        except Exception:
            logger.warning("Orphan object delete failed for %r", key, exc_info=True)
            # Best-effort stays best-effort; keys that failed this round are
            # re-marked so a later cron pass retries them.
            mark_storage_orphan(key)
    return {"deleted": deleted}
