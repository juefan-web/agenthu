"""The durable cleanup executor for accepted data operations (P0-3 slice 2).

Deletion runs the four frozen phases (A-draft §2.5 / §4):

    DELETE_FENCE      the barrier from the confirm transaction already
                      fences the scope; here retrieval and projections go
                      dark (memory embeddings NULLed, recompute ids cleared)
                      before any row delete.
    DELETE_RELATIONAL durable items with action DELETE_RELATIONAL — rows by
                      the exact closure ids; the audit redact item is routed
                      by reading its payload FIRST (adjudication ②).
    DELETE_OBJECTS    DELETE_OBJECT items (storage objects) plus CLEAR_REDIS
                      items (this owner's membership in shared wake-up sets).
    DELETE_VERIFY     VERIFY_ABSENT items; object verification uses the
                      storage.stat trichotomy — only a confirmed 404 counts
                      as erasure evidence, 403/network failures never do.

Every step is idempotent and resumable: the operation's ``phase`` is the
checkpoint, item states carry per-item progress, and failures walk the frozen
backoff ladder inside data_lifecycle. Settlement: all items DONE → COMPLETED
(source/memory barriers release with the completed operation; account barriers
never release, and the account settlement also invalidates the owner's export
operations). A FAILED item parks the operation as FAILED with a safe error and
the outstanding count; the barrier stays (FAILED never lifts one).
"""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from typing import Any

from redis import Redis
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from backend.core.errors import ConflictError, ValidationError
from backend.db.base import utcnow
from backend.models.agent import AgentRun, PendingAction, PendingActionMutation
from backend.models.audit import AuditLog
from backend.models.chat import ChatMessage, ChatSession
from backend.models.consent import ModelContextConsent
from backend.models.current_state import CurrentState
from backend.models.data_lifecycle import DataBarrier, DataCleanupItem, DataOperation
from backend.models.enums import (
    CleanupItemAction,
    CleanupItemState,
    DataBarrierScope,
    DataBarrierState,
    DataOperationKind,
    DataOperationPhase,
    DataOperationStatus,
)
from backend.models.event import Event
from backend.models.file import FileObject
from backend.models.focus_session import FocusSession
from backend.models.goal import Goal
from backend.models.material import GroundingConsent, MaterialAnswer, MaterialChunk
from backend.models.memory import Memory
from backend.models.notification import NotificationPreference
from backend.models.permission import PermissionGrant
from backend.models.plan import Plan, PlanItem
from backend.models.task import Task, task_events
from backend.models.user import User
from backend.services import data_lifecycle as dl
from backend.services.storage import ObjectStorage

logger = logging.getLogger(__name__)

# Explicit resource_type → model map: the executor deletes by exact closure
# ids, and an explicit map keeps that auditable (and typed) instead of
# reflecting through metadata at runtime.
RESOURCE_MODELS: dict[str, Any] = {
    "users": User,
    "events": Event,
    "tasks": Task,
    "goals": Goal,
    "focus_sessions": FocusSession,
    "plans": Plan,
    "plan_items": PlanItem,
    "memories": Memory,
    "file_objects": FileObject,
    "material_chunks": MaterialChunk,
    "material_answers": MaterialAnswer,
    "grounding_consents": GroundingConsent,
    "model_context_consents": ModelContextConsent,
    "permission_grants": PermissionGrant,
    "notification_preferences": NotificationPreference,
    "chat_sessions": ChatSession,
    "chat_messages": ChatMessage,
    "agent_runs": AgentRun,
    "pending_actions": PendingAction,
    "pending_action_mutations": PendingActionMutation,
    "current_states": CurrentState,
}

# Phase → the cleanup actions that phase owns (the fence owns no items).
_PHASE_ACTIONS: dict[DataOperationPhase, tuple[CleanupItemAction, ...]] = {
    DataOperationPhase.DELETE_RELATIONAL: (CleanupItemAction.DELETE_RELATIONAL,),
    DataOperationPhase.DELETE_OBJECTS: (
        CleanupItemAction.DELETE_OBJECT,
        CleanupItemAction.CLEAR_REDIS,
    ),
    DataOperationPhase.DELETE_VERIFY: (CleanupItemAction.VERIFY_ABSENT,),
}

_PHASE_ORDER: tuple[DataOperationPhase, ...] = (
    DataOperationPhase.DELETE_FENCE,
    DataOperationPhase.DELETE_RELATIONAL,
    DataOperationPhase.DELETE_OBJECTS,
    DataOperationPhase.DELETE_VERIFY,
)

# Object-verification items live under their own pseudo-family so they can
# never be confused with row verification of file_objects.
OBJECT_VERIFY_FAMILY = "storage_objects"


class ItemExecutionError(Exception):
    """One item failed; retryable=False parks it as FAILED immediately."""

    def __init__(self, summary: str, *, retryable: bool = True) -> None:
        super().__init__(summary)
        self.summary = summary
        self.retryable = retryable


def _as_uuids(values: list[str]) -> list[uuid.UUID]:
    return [uuid.UUID(str(value)) for value in values]


def _edge_pairs(values: list[str]) -> list[tuple[uuid.UUID, uuid.UUID]]:
    pairs: list[tuple[uuid.UUID, uuid.UUID]] = []
    for value in values:
        task_id, _, event_id = str(value).partition(":")
        pairs.append((uuid.UUID(task_id), uuid.UUID(event_id)))
    return pairs


def _edges_filter(pairs: list[tuple[uuid.UUID, uuid.UUID]]):
    return or_(
        *(
            (task_events.c.task_id == task_id) & (task_events.c.event_id == event_id)
            for task_id, event_id in pairs
        )
    )


def _items_of(session: Session, operation_id: uuid.UUID) -> list[DataCleanupItem]:
    return list(
        session.scalars(
            select(DataCleanupItem).where(DataCleanupItem.operation_id == operation_id)
        ).all()
    )


# --- item execution -------------------------------------------------------------


def _redact_audit_rows(session: Session, ids: list[str]) -> None:
    """Adjudication ② redact path: scrub content/PII columns in place, keep
    the row as the 90-day content-free receipt (never a row delete)."""

    parsed = _as_uuids(ids)
    if parsed:
        session.execute(
            update(AuditLog)
            .where(AuditLog.id.in_(parsed))
            .values(details=None, path=None, resource_id=None, ip_address=None, user_agent=None)
        )


def _delete_rows(session: Session, resource_type: str, ids: list[str]) -> None:
    if resource_type == "task_events":
        pairs = _edge_pairs(ids)
        if pairs:
            session.execute(delete(task_events).where(_edges_filter(pairs)))
        return
    model = RESOURCE_MODELS.get(resource_type)
    if model is None:
        raise ItemExecutionError(f"unknown relational family {resource_type}", retryable=False)
    parsed = _as_uuids(ids)
    if parsed:
        session.execute(delete(model).where(model.id.in_(parsed)))


def _verify_item(session: Session, item: DataCleanupItem, *, storage: ObjectStorage) -> None:
    payload: dict = dict(item.payload or {})
    if item.resource_type == OBJECT_VERIFY_FAMILY:
        state = storage.stat(item.item_ref)
        if state == storage.STAT_ABSENT:
            return
        if state == storage.STAT_EXISTS:
            raise ItemExecutionError("object still present", retryable=True)
        if state == storage.STAT_FORBIDDEN:
            # 403 is NOT absence (A-draft §2.5): a permission failure can
            # never pass as erasure evidence.
            raise ItemExecutionError("object check forbidden; not erasure evidence", retryable=True)
        raise ItemExecutionError("object check unavailable; not erasure evidence", retryable=True)
    if item.resource_type == "redis":
        # Wake-up sets are hints (registry notes): emptiness is not erasure
        # evidence and membership is best-effort, so nothing to verify here.
        return
    ids = payload.get("ids") or []
    if not ids:
        return
    if item.resource_type == "audit_logs":
        # Redact verification is the INVERSE of absence: the 90-day receipt
        # rows must still exist, with every content/PII column scrubbed.
        # (Column fetch + Python-side judgement: a count() with the OR filter
        # disagreed with a same-transaction column read on this stack, so the
        # check uses the shape that was verified to read post-update truth.)
        parsed = _as_uuids(ids)
        rows = session.execute(
            select(
                AuditLog.details,
                AuditLog.path,
                AuditLog.resource_id,
                AuditLog.ip_address,
                AuditLog.user_agent,
            ).where(AuditLog.id.in_(parsed))
        ).all()
        if len(rows) != len(parsed):
            raise ItemExecutionError(
                "audit receipt rows missing; redact must keep them", retryable=True
            )
        unscrubbed = sum(1 for row in rows if any(value is not None for value in row))
        if unscrubbed:
            raise ItemExecutionError(f"{unscrubbed} audit rows still carry content", retryable=True)
        return
    if item.resource_type == "task_events":
        pairs = _edge_pairs(ids)
        remaining = (
            session.execute(
                select(func.count()).select_from(task_events).where(_edges_filter(pairs))
            ).scalar_one()
            if pairs
            else 0
        )
    else:
        model = RESOURCE_MODELS.get(item.resource_type)
        if model is None:
            raise ItemExecutionError(f"unknown verify family {item.resource_type}", retryable=False)
        remaining = session.execute(
            select(func.count()).select_from(model).where(model.id.in_(_as_uuids(ids)))
        ).scalar_one()
    if remaining:
        raise ItemExecutionError(f"{remaining} rows still present", retryable=True)


def execute_cleanup_item(
    session: Session,
    item: DataCleanupItem,
    *,
    storage: ObjectStorage,
    redis: Redis | None = None,
) -> None:
    """Execute ONE claimed item.

    Dispatch discipline (adjudication ②): the payload is read BEFORE the
    route is chosen — a redact item can never be routed through row deletion
    (and a non-audit redact item refuses to run at all), and a plain
    relational item can never reach the redact path.
    """

    payload: dict = dict(item.payload or {})
    if item.action == CleanupItemAction.DELETE_RELATIONAL:
        if payload.get("redact") is True:
            if item.resource_type != "audit_logs":
                raise ItemExecutionError(
                    f"redact payload on non-audit family {item.resource_type}",
                    retryable=False,
                )
            _redact_audit_rows(session, payload.get("ids") or [])
            return
        ids = payload.get("ids")
        if not ids:
            raise ItemExecutionError("relational delete item without ids", retryable=False)
        _delete_rows(session, item.resource_type, ids)
    elif item.action == CleanupItemAction.DELETE_OBJECT:
        storage.delete(item.item_ref)
    elif item.action == CleanupItemAction.CLEAR_REDIS:
        if redis is None:
            raise ItemExecutionError("redis unavailable for clear item", retryable=True)
        member = str(payload.get("member") or "")
        if not member:
            raise ItemExecutionError("clear-redis item without member", retryable=False)
        # Shared wake-up sets carry other owners' memberships too: remove
        # this member, never the key itself.
        redis.srem(item.item_ref, member)
    elif item.action == CleanupItemAction.VERIFY_ABSENT:
        _verify_item(session, item, storage=storage)
    else:  # pragma: no cover - enum exhaustiveness guard
        raise ItemExecutionError(f"unsupported action {item.action}", retryable=False)


# --- phase driver ----------------------------------------------------------------


def _fence(session: Session, operation: DataOperation) -> None:
    """Make retrieval and projections dark before any row delete: NULL the
    embeddings of every memory in the closure and drop the stale projection
    rows (they rebuild lazily from what remains)."""

    impact: dict = dict(operation.impact or {})
    for family in impact.get("families", []):
        resource_type = family.get("resource_type")
        if resource_type == "memories" and family.get("delete_ids"):
            session.execute(
                update(Memory)
                .where(Memory.id.in_(_as_uuids(family["delete_ids"])))
                .values(embedding=None)
            )
        recompute_ids = family.get("recompute_ids") or []
        if recompute_ids and resource_type in RESOURCE_MODELS:
            model = RESOURCE_MODELS[resource_type]
            session.execute(delete(model).where(model.id.in_(_as_uuids(recompute_ids))))
    operation.phase = DataOperationPhase.DELETE_RELATIONAL


def _run_item_phase(
    session: Session,
    operation: DataOperation,
    phase: DataOperationPhase,
    *,
    storage: ObjectStorage,
    redis: Redis | None,
) -> bool:
    """Run one action-phase pass over this operation's due items.

    True = every item the phases covered so far own is DONE and the driver
    may advance to the next phase; False = the operation is parked
    (RETRY_WAIT or FAILED) or another executor still holds a claim.
    """

    actions = {action.value for action in _PHASE_ACTIONS[phase]}
    # Earlier phases must stay DONE; a regression there parks the operation.
    for previous in _PHASE_ORDER[: _PHASE_ORDER.index(phase)]:
        actions.update(action.value for action in _PHASE_ACTIONS.get(previous, ()))
    items = dl.claim_cleanup_items(session, operation_id=operation.id, actions=actions)
    for item in items:
        try:
            execute_cleanup_item(session, item, storage=storage, redis=redis)
            dl.complete_cleanup_item(session, item.id)
        except ItemExecutionError as error:
            if error.retryable:
                dl.fail_cleanup_item(session, item.id, error_summary=error.summary)
            else:
                dl.park_cleanup_item(session, item.id, error_summary=error.summary)
        except Exception:
            logger.exception("Cleanup item failed", extra={"item_id": str(item.id)})
            dl.fail_cleanup_item(session, item.id, error_summary="executor failure (safe summary)")
    return _settle_progress(session, operation, actions)


def _settle_progress(session: Session, operation: DataOperation, actions: set[str]) -> bool:
    """Recount progress and decide park-vs-advance for the covered actions.

    Progress counts use ALL of the operation's items; the advance decision
    only looks at items owned by the phases covered so far (later-phase
    items are still pending and must not block the checkpoint).
    """

    items = _items_of(session, operation.id)
    done = sum(1 for item in items if item.state == CleanupItemState.DONE)
    operation.progress_processed = done
    operation.outstanding_count = len(items) - done
    scoped = [item for item in items if item.action in actions]
    failed = [item for item in scoped if item.state == CleanupItemState.FAILED]
    if failed:
        operation.status = DataOperationStatus.FAILED
        operation.error_code = "cleanup_item_failed"
        operation.error_message = f"{len(failed)} cleanup item(s) exhausted their retry ladder"
        operation.error_retryable = True
        operation.next_retry_at = None
        session.flush()
        return False
    now = utcnow()
    gated = [
        item.next_retry_at
        for item in scoped
        if item.state == CleanupItemState.PENDING and item.next_retry_at is not None
    ]
    claimed = [item for item in scoped if item.state == CleanupItemState.CLAIMED]
    if gated or claimed:
        operation.status = DataOperationStatus.RETRY_WAIT
        operation.next_retry_at = (
            min(gated) if gated else now + timedelta(seconds=dl.CLEANUP_BACKOFF_LADDER_S[0])
        )
        session.flush()
        return False
    if all(item.state == CleanupItemState.DONE for item in scoped):
        return True
    # PENDING, ungated, but not claimed in this pass (claim window/limit):
    # retry immediately on the next pass.
    operation.status = DataOperationStatus.RETRY_WAIT
    operation.next_retry_at = now
    session.flush()
    return False


def _invalidate_owner_exports(session: Session, operation: DataOperation) -> None:
    """Account-deletion settlement: every export of this owner is void (the
    staging objects themselves die via the account's DELETE_OBJECT items)."""

    exports = list(
        session.scalars(
            select(DataOperation).where(
                DataOperation.owner_handle == operation.owner_handle,
                DataOperation.kind == DataOperationKind.EXPORT,
                DataOperation.status.in_(
                    (
                        DataOperationStatus.QUEUED,
                        DataOperationStatus.RUNNING,
                        DataOperationStatus.RETRY_WAIT,
                        DataOperationStatus.READY,
                    )
                ),
            )
        ).all()
    )
    for export in exports:
        export.status = DataOperationStatus.FAILED
        export.error_code = "invalidated_by_deletion"
        export.error_message = "a deletion was accepted for this owner; the package is void"
        export.error_retryable = False
        export.next_retry_at = None
    if exports:
        session.flush()


def _complete_operation(session: Session, operation: DataOperation) -> None:
    operation.status = DataOperationStatus.COMPLETED
    operation.error_code = None
    operation.error_message = None
    operation.error_retryable = None
    operation.next_retry_at = None
    for barrier in session.scalars(
        select(DataBarrier).where(
            DataBarrier.operation_id == operation.id,
            DataBarrier.state == DataBarrierState.ACTIVE,
        )
    ).all():
        if barrier.scope == DataBarrierScope.ACCOUNT:
            # Never auto-released (A-draft §2.2): the barrier lifts only
            # with the account itself.
            continue
        dl.release_barrier(session, barrier.id, completed_operation=operation)
    if (operation.target or {}).get("kind") == "account":
        _invalidate_owner_exports(session, operation)
    session.flush()


def run_deletion(
    session: Session,
    operation: DataOperation,
    *,
    storage: ObjectStorage,
    redis: Redis | None = None,
) -> None:
    """Drive one deletion operation as far as it can go right now.

    Called by the worker for QUEUED operations and by the sweep for
    RETRY_WAIT ones whose backoff gate has passed; each call resumes from
    the persisted phase checkpoint and per-item states.
    """

    if operation.kind != DataOperationKind.DELETION:
        return
    if operation.status not in (
        DataOperationStatus.QUEUED,
        DataOperationStatus.RUNNING,
        DataOperationStatus.RETRY_WAIT,
    ):
        return
    if operation.status == DataOperationStatus.QUEUED:
        operation.status = DataOperationStatus.RUNNING
        operation.phase = DataOperationPhase.DELETE_FENCE
        session.flush()
    phase: DataOperationPhase | None = operation.phase or DataOperationPhase.DELETE_FENCE
    while phase in _PHASE_ORDER:
        if phase == DataOperationPhase.DELETE_FENCE:
            _fence(session, operation)
            session.flush()
            phase = DataOperationPhase.DELETE_RELATIONAL
            continue
        assert phase is not None  # loop guard: only _PHASE_ORDER members
        if not _run_item_phase(session, operation, phase, storage=storage, redis=redis):
            return
        index = _PHASE_ORDER.index(phase)
        if index + 1 < len(_PHASE_ORDER):
            phase = _PHASE_ORDER[index + 1]
            operation.phase = phase
            session.flush()
        else:
            phase = None
    _complete_operation(session, operation)


def retry_cleanup_operation(
    session: Session, operation: DataOperation, *, expected_version: int
) -> DataOperation:
    """Manual retry (A-draft §2): the SAME operation, barrier untouched,
    exhausted items get a fresh ladder. Only source/memory deletions —
    after an account deletion the owner can no longer authenticate, so
    those FAILED cleanups walk the automatic ladder and ops handling only."""

    if operation.version != expected_version:
        raise ConflictError("operation moved since; reload and retry", code="version_conflict")
    if operation.kind != DataOperationKind.DELETION or (operation.target or {}).get("kind") not in (
        "source",
        "memory",
    ):
        raise ValidationError(
            "manual retry applies to source/memory deletions only", code="unsupported_scope"
        )
    if operation.status not in (DataOperationStatus.FAILED, DataOperationStatus.RETRY_WAIT):
        raise ConflictError("operation is not in a retryable state", code="not_retryable")
    items = _items_of(session, operation.id)
    for item in items:
        if item.state in (CleanupItemState.FAILED, CleanupItemState.PENDING):
            item.state = CleanupItemState.PENDING
            item.attempts = 0
            item.next_retry_at = None
            item.claimed_at = None
            item.last_error = None
    operation.status = DataOperationStatus.QUEUED
    operation.error_code = None
    operation.error_message = None
    operation.error_retryable = None
    operation.next_retry_at = None
    operation.version += 1
    session.flush()
    return operation
