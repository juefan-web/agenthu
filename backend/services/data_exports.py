"""The export pipeline: collect → package → verify → READY (P0-3 slice 2).

One graph, one snapshot (A-draft §3): collection reads every registered
user-owned family in a single transaction, the package is an immutable ZIP
staged in object storage under ``exports/{owner}/{operation}.zip`` with a
manifest (per-entry sha256, family counts, excluded categories), and the
package only flips READY after verification re-reads the staged object and
re-checks every entry checksum. Staging lives 24 hours; a concurrent
deletion (barrier raised or generation moved) voids the export at any phase
boundary and at download — an invalidated package never reports READY.

Exports exclude by construction: credentials (hashed_password), embeddings
(rebuildable; the manifest records the exclusion and the rebuild shape via
graph_version), the lifecycle ledger itself and the rebuilt current-state
projection. Hidden-but-not-yet-hard-cleared chat rows are exported as
stored and the manifest says so — invisibility is not deletion, and the
export must not claim otherwise.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import uuid
import zipfile
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.errors import ConflictError
from backend.core.telemetry import stage_span
from backend.db.base import utcnow
from backend.models.agent import AgentRun, PendingAction, PendingActionMutation
from backend.models.audit import AuditLog
from backend.models.chat import ChatMessage, ChatSession
from backend.models.consent import ModelContextConsent
from backend.models.data_lifecycle import DataBarrier, DataOperation
from backend.models.enums import (
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
from backend.services import data_operations as ops
from backend.services.data_registry import graph_version
from backend.services.storage import ObjectStorage

logger = logging.getLogger(__name__)

EXPORT_STAGING_TTL = timedelta(hours=24)

# Families exported as full rows (model, content fields). ``embedding`` is
# deliberately absent everywhere it exists: embeddings rebuild from content
# and never leave the backend (A-draft §3).
_DIRECT_FAMILIES: tuple[tuple[str, Any, tuple[str, ...]], ...] = (
    ("events", Event, ("data", "context", "provenance", "occurred_at", "source", "type")),
    (
        "tasks",
        Task,
        (
            "title",
            "description",
            "source",
            "source_upstream_id",
            "status",
            "deadline",
            "estimated_duration_minutes",
            "actual_duration_minutes",
            "priority",
            "completed_at",
            "extra",
            "goal_id",
        ),
    ),
    ("goals", Goal, ("title", "description", "status")),
    (
        "focus_sessions",
        FocusSession,
        ("task_id", "status", "started_at", "ended_at", "actual_minutes", "deviation_note"),
    ),
    (
        "plans",
        Plan,
        (
            "title",
            "generated_by",
            "replan_reason",
            "execution_result",
            "confirmed_at",
            "cancelled_at",
            "completed_at",
        ),
    ),
    (
        "memories",
        Memory,
        (
            "content",
            "source",
            "source_event_ids",
            "evidence",
            "subject_key",
            "level",
            "kind",
            "confidence",
            "valid_from",
            "valid_to",
            "supersedes_id",
            "correction_status",
        ),
    ),
    (
        "file_objects",
        FileObject,
        ("filename", "course_name", "status", "storage_key", "file_metadata"),
    ),
    ("material_chunks", MaterialChunk, ("file_id", "content", "char_count", "scanner_version")),
    (
        "material_answers",
        MaterialAnswer,
        ("question", "answer", "citations", "chunk_ids", "memory_ids"),
    ),
    ("grounding_consents", GroundingConsent, ("course_name", "enabled", "consent_text_version")),
    (
        "model_context_consents",
        ModelContextConsent,
        ("enabled", "consent_text_version", "revoked_at"),
    ),
    (
        "permission_grants",
        PermissionGrant,
        ("action", "scope", "level", "note", "granted_at", "revoked_at"),
    ),
    ("notification_preferences", NotificationPreference, ("enabled_categories", "timezone")),
    ("chat_sessions", ChatSession, ("title", "archived_at")),
    ("chat_messages", ChatMessage, ("session_id", "content")),
    (
        "agent_runs",
        AgentRun,
        (
            "status",
            "invocation_kind",
            "context_snapshot",
            "decision_basis",
            "tool_calls",
            "result",
            "failure",
        ),
    ),
    (
        "pending_actions",
        PendingAction,
        ("action", "args", "display", "basis", "status", "result", "grant_snapshot"),
    ),
)

_EXCLUDED_CATEGORIES = [
    "credentials (password hashes, tokens, signed URLs)",
    "embeddings (rebuildable; rebuild shape pinned by graph_version)",
    "internal_lifecycle_ledger (operations/barriers/suppressions)",
    "current_states (projection; rebuilt from remaining data)",
    "object_storage_blobs (listed in manifest; included only with include_files)",
]


def staging_key(owner_handle: str, operation_id: uuid.UUID) -> str:
    return f"exports/{owner_handle}/{operation_id}.zip"


# --- serialization ---------------------------------------------------------------


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def _row_dict(row: Any, fields: tuple[str, ...]) -> dict:
    out: dict[str, Any] = {"id": str(row.id)}
    stamps = []
    for name in ("created_at", "updated_at"):
        stamp = getattr(row, name, None)
        if stamp is not None:
            stamps.append((name, stamp.isoformat()))
    out.update(dict(stamps))
    for name in fields:
        out[name] = _jsonable(getattr(row, name))
    return out


def collect_families(session: Session, user_id: uuid.UUID) -> dict[str, list[dict]]:
    """One consistent snapshot of every exported family (A-draft §3)."""

    collected: dict[str, list[dict]] = {}
    for key, model, fields in _DIRECT_FAMILIES:
        rows = session.scalars(
            select(model).where(model.user_id == user_id).order_by(model.id)
        ).all()
        collected[key] = [_row_dict(row, fields) for row in rows]

    user = session.get(User, user_id)
    assert user is not None  # same-transaction owner read
    collected["users"] = [
        {
            "id": str(user.id),
            "email": user.email,
            "display_name": user.display_name,
            "created_at": user.created_at.isoformat(),
        }
    ]

    plan_items = session.execute(
        select(PlanItem).join(Plan, PlanItem.plan_id == Plan.id).where(Plan.user_id == user_id)
    ).scalars()
    collected["plan_items"] = [
        _row_dict(
            row,
            (
                "plan_id",
                "task_id",
                "title",
                "order_index",
                "planned_start",
                "planned_end",
                "planned_minutes",
                "status",
                "actual_minutes",
                "result",
                "notes",
                "basis",
            ),
        )
        for row in plan_items
    ]

    mutations = session.execute(
        select(PendingActionMutation)
        .join(PendingAction, PendingActionMutation.pending_action_id == PendingAction.id)
        .where(PendingAction.user_id == user_id)
    ).scalars()
    collected["pending_action_mutations"] = [
        _row_dict(row, ("pending_action_id", "response")) for row in mutations
    ]

    edges = session.execute(
        select(task_events.c.task_id, task_events.c.event_id)
        .join(Task, task_events.c.task_id == Task.id)
        .where(Task.user_id == user_id)
    ).all()
    collected["task_events"] = [{"task_id": str(row[0]), "event_id": str(row[1])} for row in edges]

    # Audit copies are the content-free receipt view only (A-draft §3:
    # "允许的审计副本" — never the details/paths/IP/UA payload).
    audit_rows = session.scalars(
        select(AuditLog).where(AuditLog.user_id == user_id).order_by(AuditLog.id)
    ).all()
    collected["audit_logs"] = [
        {
            "id": str(row.id),
            "actor": row.actor,
            "action": row.action,
            "decision": row.decision,
            "created_at": row.created_at.isoformat(),
        }
        for row in audit_rows
    ]
    return collected


# --- package ----------------------------------------------------------------------


def _entry(path: str, data: bytes) -> tuple[dict, tuple[str, bytes]]:
    return (
        {"path": path, "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)},
        (path, data),
    )


def build_package(
    collected: dict[str, list[dict]],
    *,
    include_files: bool,
    storage: ObjectStorage,
    generation: int,
) -> bytes:
    """The immutable ZIP: per-family JSONL + manifest.json + README.txt, all
    archive-relative (A-draft §3)."""

    entries_meta: list[dict] = []
    members: list[tuple[str, bytes]] = []

    for family in sorted(k for k in collected if k != "users"):
        lines = "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in collected[family]
        )
        meta, member = _entry(f"{family}.jsonl", lines.encode("utf-8"))
        entries_meta.append(meta)
        members.append(member)

    meta, member = _entry(
        "users.jsonl",
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in collected["users"]
        ).encode("utf-8"),
    )
    entries_meta.append(meta)
    members.append(member)

    omitted_files: list[dict] = []
    if include_files:
        for row in collected["file_objects"]:
            key = row.get("storage_key")
            if not key:
                continue
            blob = storage.get(key)
            safe_name = (row.get("filename") or "file").replace("/", "_")[:80]
            meta, member = _entry(f"files/{row['id']}__{safe_name}", blob)
            entries_meta.append(meta)
            members.append(member)
    else:
        omitted_files = [
            {"id": row["id"], "filename": row.get("filename")} for row in collected["file_objects"]
        ]

    manifest = {
        "schema_version": ops.SCHEMA_VERSION,
        "graph_version": graph_version(),
        "snapshot_at": utcnow().isoformat(),
        "generation": generation,
        "family_counts": {family: len(rows) for family, rows in collected.items()},
        "entries": entries_meta,
        "relations_notes": (
            "task_events edges export as {task_id,event_id} pairs; memory "
            "history chains via each row's supersedes_id."
        ),
        "rebuild_notes": (
            "Embeddings are excluded and rebuild from the exported content; "
            "current_states is a projection and rebuilds automatically."
        ),
        "excluded_categories": _EXCLUDED_CATEGORIES,
        "include_files": include_files,
        "omitted_files": omitted_files,
        "chat_note": (
            "Chat rows export as stored: rows hidden in the UI but not yet "
            "hard-cleared appear here (invisibility is not deletion)."
        ),
    }
    readme = (
        "Personal data export\n"
        "====================\n\n"
        "One snapshot of your data at the time shown in manifest.json.\n"
        "Each family is a JSONL file (one JSON object per line).\n"
        "Embeddings and internal lifecycle ledgers are excluded; see\n"
        "manifest.json (excluded_categories) for the full list.\n"
        "Files are included only when include_files was requested.\n"
        "This package expires 24 hours after it was built.\n"
    )
    readme_meta, readme_member = _entry("README.txt", readme.encode("utf-8"))
    # manifest.json cannot carry its own checksum (self-reference); it lists
    # every OTHER member and verify_package re-checks exactly those.
    manifest["entries"] = [*entries_meta, readme_meta]
    members.append(readme_member)
    members.append(
        (
            "manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8"),
        )
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, data in members:
            archive.writestr(path, data)
    return buffer.getvalue()


def verify_package(package: bytes) -> bool:
    """Only a re-read that reproduces every manifest checksum may READY."""

    try:
        with zipfile.ZipFile(io.BytesIO(package)) as archive:
            names = set(archive.namelist())
            manifest = json.loads(archive.read("manifest.json"))
            for entry in manifest["entries"]:
                if entry["path"] not in names:
                    return False
                data = archive.read(entry["path"])
                if len(data) != entry["size_bytes"]:
                    return False
                if hashlib.sha256(data).hexdigest() != entry["sha256"]:
                    return False
            return True
    except (KeyError, ValueError, zipfile.BadZipFile):
        return False


# --- operation lifecycle -----------------------------------------------------------


def _void(session: Session, operation: DataOperation, *, code: str, message: str) -> None:
    operation.status = DataOperationStatus.FAILED
    operation.error_code = code
    operation.error_message = message
    operation.error_retryable = False
    operation.next_retry_at = None
    session.flush()


def _check_still_valid(session: Session, operation: DataOperation) -> bool:
    """A deletion accepted for this owner (barrier up or generation moved)
    voids the export; so does the owner's row disappearing."""

    handle = operation.owner_handle
    live = session.execute(
        select(User.id, User.is_active, User.data_generation).where(User.owner_handle == handle)
    ).one_or_none()
    if live is None or not live.is_active:
        _void(
            session,
            operation,
            code="invalidated_by_deletion",
            message="the account is gone or deactivated; the package is void",
        )
        return False
    if int(live.data_generation) != operation.data_generation:
        _void(
            session,
            operation,
            code="invalidated_by_deletion",
            message="a deletion moved the data generation; the package is void",
        )
        return False
    barrier = session.scalar(
        select(DataBarrier.id).where(
            DataBarrier.owner_handle == handle,
            DataBarrier.state == DataBarrierState.ACTIVE,
        )
    )
    if barrier is not None:
        _void(
            session,
            operation,
            code="invalidated_by_deletion",
            message="an active deletion barrier blocks this owner; the package is void",
        )
        return False
    return True


def create_export(
    session: Session, *, user: User, client_request_id: str, include_files: bool
) -> tuple[DataOperation, bool]:
    """Idempotent export accept (A-draft §4): same key + same include_files
    returns the SAME operation; a different include_files is the caller's
    409 (the flag is input, and replay comparison covers it)."""

    handle = dl.owner_handle_of(session, user.id)
    existing = session.scalar(
        select(DataOperation).where(
            DataOperation.owner_handle == handle,
            DataOperation.kind == DataOperationKind.EXPORT,
            DataOperation.client_request_id == client_request_id,
        )
    )
    if existing is not None:
        if existing.export_include_files is not include_files:
            raise ConflictError(
                "client_request_id already used with a different include_files",
                code="idempotency_conflict",
            )
        return existing, False
    operation = DataOperation(
        owner_handle=handle,
        kind=DataOperationKind.EXPORT,
        client_request_id=client_request_id,
        target=None,
        status=DataOperationStatus.QUEUED,
        data_generation=ops.current_generation(session, user.id),
        export_include_files=include_files,
    )
    session.add(operation)
    session.flush()
    return operation, True


def run_export(session: Session, operation: DataOperation, *, storage: ObjectStorage) -> None:
    """Drive collect → package → verify → READY, resuming from the phase
    checkpoint. Any inconsistency voids the export instead of READY. Wrapped
    in the "operation" stage of the OTel chain (P0-5 slice 1)."""

    with stage_span(
        "operation",
        f"data.operation.{operation.kind.value}",
        **{"correlation.id": str(operation.id)},
    ):
        _run_export(session, operation, storage=storage)


def _run_export(session: Session, operation: DataOperation, *, storage: ObjectStorage) -> None:
    if operation.kind != DataOperationKind.EXPORT:
        return
    if operation.status not in (
        DataOperationStatus.QUEUED,
        DataOperationStatus.RUNNING,
        DataOperationStatus.RETRY_WAIT,
    ):
        return
    operation.status = DataOperationStatus.RUNNING
    phase = operation.phase or DataOperationPhase.EXPORT_COLLECT

    if phase == DataOperationPhase.EXPORT_COLLECT:
        if not _check_still_valid(session, operation):
            return
        handle = operation.owner_handle
        live = session.execute(
            select(User.id).where(User.owner_handle == handle)
        ).scalar_one_or_none()
        if live is None:  # pragma: no cover - _check_still_valid covered it
            _void(
                session, operation, code="invalidated_by_deletion", message="owner row disappeared"
            )
            return
        collected = collect_families(session, live)
        package = build_package(
            collected,
            include_files=bool(operation.export_include_files),
            storage=storage,
            generation=operation.data_generation,
        )
        operation.phase = DataOperationPhase.EXPORT_PACKAGE
        session.flush()
    else:
        package = storage.get(staging_key(operation.owner_handle, operation.id))

    if phase in (DataOperationPhase.EXPORT_COLLECT, DataOperationPhase.EXPORT_PACKAGE):
        if not _check_still_valid(session, operation):
            return
        storage.put(
            staging_key(operation.owner_handle, operation.id),
            package,
            "application/zip",
        )
        operation.phase = DataOperationPhase.EXPORT_VERIFY
        session.flush()

    # EXPORT_VERIFY (and the tail of earlier phases): re-read from staging.
    if not _check_still_valid(session, operation):
        return
    staged = storage.get(staging_key(operation.owner_handle, operation.id))
    if not verify_package(staged):
        _void(
            session,
            operation,
            code="export_verify_failed",
            message="staged package failed checksum verification; no READY",
        )
        return
    operation.status = DataOperationStatus.READY
    operation.phase = DataOperationPhase.EXPORT_VERIFY
    operation.expires_at = utcnow() + EXPORT_STAGING_TTL
    session.flush()


def download_package(
    session: Session, operation: DataOperation, *, storage: ObjectStorage
) -> bytes:
    """Owner download (A-draft §3): READY only, no-store at the route, and a
    concurrent deletion voids the package instead of serving a stale one."""

    from backend.core.errors import AppError, ConflictError, ServiceUnavailableError

    if operation.kind != DataOperationKind.EXPORT:
        raise ConflictError("download applies to exports only", code="export_not_ready")
    if operation.status == DataOperationStatus.EXPIRED:
        raise AppError("export package expired", code="export_expired", status_code=410)
    if operation.status != DataOperationStatus.READY:
        raise ConflictError("export package is not READY", code="export_not_ready")
    if not _check_still_valid(session, operation):
        raise ConflictError(
            "a deletion invalidated this package; export again",
            code="invalidated_by_deletion",
        )
    try:
        return storage.get(staging_key(operation.owner_handle, operation.id))
    except Exception as error:
        raise ServiceUnavailableError(
            "export storage is unavailable; retry later",
            code="dependency_unavailable",
        ) from error


def expire_ready_exports(session: Session, *, storage: ObjectStorage) -> int:
    """24h staging TTL (cron): EXPIRED + the staged object deleted."""

    now = utcnow()
    ready = list(
        session.scalars(
            select(DataOperation).where(
                DataOperation.kind == DataOperationKind.EXPORT,
                DataOperation.status == DataOperationStatus.READY,
                DataOperation.expires_at.is_not(None),
                DataOperation.expires_at <= now,
            )
        ).all()
    )
    for operation in ready:
        operation.status = DataOperationStatus.EXPIRED
        operation.next_retry_at = None
        try:
            storage.delete(staging_key(operation.owner_handle, operation.id))
        except Exception:
            # The status flip is the source of truth; a leftover object is
            # unreachable (nothing serves EXPIRED packages) and the next
            # sweep retries the delete.
            logger.warning(
                "Expired export object delete failed", extra={"operation_id": str(operation.id)}
            )
    if ready:
        session.flush()
    return len(ready)
