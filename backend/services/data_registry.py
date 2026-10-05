"""Machine-executable dependency inventory for data lifecycle (D-036 §8-8).

Frozen requirement (M5 A-draft §1): before implementing deletion/export, the
data-family table must be checked against every ORM table, JSON field, Redis
key and local store, turned into a machine-executable matrix — and an
"exists but unregistered" state must FAIL, not warn.

``audit_inventory`` is that check: it reconciles the live ``Base.metadata``
table set and the Redis key literals found in backend source against this
registry in both directions. The integration test asserts a clean report and
proves fail-closed behavior by injecting a fake table / fake key literal.

Entries carry the owner-resolution path and content-field list the P0-3
registry handlers (export serializer / delete handler / verify query) will be
built from; ``disposal`` cites the frozen A-draft §1 family row semantics.
Client-side stores are registered as documentation entries (owner: P0-2/P0-4)
so the matrix is complete across layers even though backend checks cannot
enumerate them.
"""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import Table

import backend.models  # noqa: F401  (registers every table on Base.metadata)
from backend.db.base import Base


class Store:
    POSTGRES = "postgres"
    REDIS = "redis"
    OBJECT_STORAGE = "object_storage"
    LOCAL_CLIENT = "local_client"


class Classification:
    USER_CONTENT = "user_content"
    DERIVED = "derived"
    CREDENTIAL = "credential"
    AUDIT = "audit"
    OPS = "ops"


@dataclass(frozen=True)
class DataResource:
    key: str
    store: str
    table: str | None = None
    owner: str = ""
    content_fields: tuple[str, ...] = ()
    classification: str = Classification.USER_CONTENT
    disposal: str = ""
    notes: str = ""


def _pg(
    key: str,
    table: str,
    owner: str,
    content_fields: tuple[str, ...],
    classification: str,
    disposal: str,
    notes: str = "",
) -> DataResource:
    return DataResource(
        key=key,
        store=Store.POSTGRES,
        table=table,
        owner=owner,
        content_fields=content_fields,
        classification=classification,
        disposal=disposal,
        notes=notes,
    )


REGISTRY: tuple[DataResource, ...] = (
    # --- postgres: user content families (A-draft §1) ------------------------
    _pg(
        "users",
        "users",
        "row itself",
        ("email", "display_name"),
        Classification.USER_CONTENT,
        "Full-account deletion target; hashed_password is a credential and is "
        "never exported; owner_handle/data_generation are lifecycle metadata.",
    ),
    _pg(
        "events",
        "events",
        "user_id",
        ("data", "context", "provenance"),
        Classification.USER_CONTENT,
        "L0 raw events; source deletion distinguishes pure derivation from "
        "independent edits; re-ingest suppression keyed by upstream id.",
    ),
    _pg(
        "tasks",
        "tasks",
        "user_id",
        ("title", "description", "extra", "source_upstream_id"),
        Classification.USER_CONTENT,
        "Derived from events but user-edited work items: derived content "
        "cleared, independent edits decorrelated then kept (A-draft §1).",
    ),
    _pg(
        "task_events",
        "task_events",
        "tasks.user_id via task_id",
        (),
        Classification.DERIVED,
        "Association edges; deleted with either side.",
    ),
    _pg(
        "goals",
        "goals",
        "user_id",
        ("title", "description"),
        Classification.USER_CONTENT,
        "Deleted with the account / by explicit target.",
    ),
    _pg(
        "focus_sessions",
        "focus_sessions",
        "user_id",
        ("deviation_note",),
        Classification.USER_CONTENT,
        "Focus results are Events; session rows are user content.",
    ),
    _pg(
        "plans",
        "plans",
        "user_id",
        ("title", "basis", "replan_reason", "execution_result"),
        Classification.USER_CONTENT,
        "Basis/recomputation chain; deleted with account or affected recompute closure.",
    ),
    _pg(
        "plan_items",
        "plan_items",
        "plans.user_id via plan_id",
        ("title", "result", "notes", "basis"),
        Classification.USER_CONTENT,
        "basis/result reference sources; cleared/recomputed per A-draft §1.",
    ),
    _pg(
        "current_states",
        "current_states",
        "user_id",
        ("current_context", "recent_state", "pending_task_ids"),
        Classification.USER_CONTENT,
        "Recomputed projection; rebuilt rather than exported as-is.",
    ),
    _pg(
        "memories",
        "memories",
        "user_id",
        ("content", "source", "source_event_ids", "evidence", "embedding", "subject_key"),
        Classification.USER_CONTENT,
        "Forgetting follows the supersedes closure; source deletion "
        "invalidates then recomputes from remaining evidence; independent "
        "corrections are decorrelated, embeddings cleared.",
    ),
    _pg(
        "file_objects",
        "file_objects",
        "user_id",
        ("filename", "metadata", "storage_key"),
        Classification.USER_CONTENT,
        "Row plus blob in object storage; chunk/embedding/blob cleared "
        "together (A-draft §1 FileObject family).",
    ),
    _pg(
        "material_chunks",
        "material_chunks",
        "user_id",
        ("content", "embedding"),
        Classification.DERIVED,
        "chunk.text and embedding cleared with the file; independent of user-authored content.",
    ),
    _pg(
        "material_answers",
        "material_answers",
        "user_id",
        ("question", "answer", "citations", "chunk_ids", "memory_ids"),
        Classification.USER_CONTENT,
        "Composite answers citing deleted material are cleared whole "
        "(r1 recommendation, preview lists the effect).",
    ),
    _pg(
        "grounding_consents",
        "grounding_consents",
        "user_id",
        ("course_name",),
        Classification.USER_CONTENT,
        "Consent history follows the account; revocation is not deletion.",
    ),
    _pg(
        "model_context_consents",
        "model_context_consents",
        "user_id",
        (),
        Classification.USER_CONTENT,
        "Consent history follows the account.",
    ),
    _pg(
        "permission_grants",
        "permission_grants",
        "user_id",
        ("scope", "note"),
        Classification.USER_CONTENT,
        "Revoked with account deletion; never granted Level 3 for "
        "self-account/source deletion (A-draft §2).",
    ),
    _pg(
        "notification_preferences",
        "notification_preferences",
        "user_id",
        ("enabled_categories", "timezone"),
        Classification.USER_CONTENT,
        "Follows the account.",
    ),
    _pg(
        "chat_sessions",
        "chat_sessions",
        "user_id",
        ("title",),
        Classification.USER_CONTENT,
        "Title may copy first-message content; permanent delete clears "
        "copies and leaves content-free source_deleted markers.",
    ),
    _pg(
        "chat_messages",
        "chat_messages",
        "user_id",
        ("content",),
        Classification.USER_CONTENT,
        "Soft delete is invisibility, not deletion; hidden-chat hard clear after 7d (D-036 §8-2).",
    ),
    _pg(
        "agent_runs",
        "agent_runs",
        "user_id",
        ("context_snapshot", "decision_basis", "tool_calls", "result", "failure"),
        Classification.USER_CONTENT,
        "Snapshots/basis/results are user content; cancelled honestly on "
        "deletion (existing terminal states, A-draft §2.4).",
    ),
    _pg(
        "pending_actions",
        "pending_actions",
        "user_id",
        ("args", "display", "basis", "result", "grant_snapshot"),
        Classification.USER_CONTENT,
        "Unexecuted actions invalidated, never re-dispatched; cached "
        "confirmation responses are user content too.",
    ),
    _pg(
        "pending_action_mutations",
        "pending_action_mutations",
        "user_id",
        ("response",),
        Classification.USER_CONTENT,
        "Cached responses cannot be reused for deleted mutations; sanitized "
        "views only (A-draft §4).",
    ),
    _pg(
        "audit_logs",
        "audit_logs",
        "user_id (SET NULL)",
        ("details", "path", "resource_id", "ip_address", "user_agent"),
        Classification.AUDIT,
        "Minimal content-free receipts kept per retention (90d completed ops); "
        "account deletion scrubs IP/UA/paths/JSON bodies (A-draft §5).",
    ),
    # --- postgres: lifecycle ledger (this slice; survives users deletion) ----
    _pg(
        "data_operations",
        "data_operations",
        "owner_handle value (opaque, no FK)",
        ("target", "error_message"),
        Classification.OPS,
        "Independent ledger keyed by opaque handle: deleting the users row "
        "must not CASCADE it away; identity cannot be recovered from it.",
    ),
    _pg(
        "data_cleanup_items",
        "data_cleanup_items",
        "owner_handle value (opaque, no FK)",
        ("item_ref", "last_error"),
        Classification.OPS,
        "Durable cleanup work queue; Redis only wakes the executor.",
    ),
    _pg(
        "data_barriers",
        "data_barriers",
        "owner_handle value (opaque, no FK)",
        ("target",),
        Classification.OPS,
        "Barrier state; restore replays suppression + generation from the "
        "ledger family, never from the users row.",
    ),
    _pg(
        "data_previews",
        "data_previews",
        "user_id (transient; CASCADE with the account)",
        ("target", "effects"),
        Classification.OPS,
        "10-minute digest-bound previews; lazy TTL purge on create.",
    ),
    _pg(
        "data_receipts",
        "data_receipts",
        "owner_handle value (opaque, no FK)",
        ("capability_digest",),
        Classification.OPS,
        "90-day account-deletion receipts; digest only, token never stored.",
    ),
    _pg(
        "data_suppressions",
        "data_suppressions",
        "owner_handle value (opaque, no FK)",
        ("upstream_hmac",),
        Classification.OPS,
        "Source re-import suppression (A-draft §2.6); HMAC identifiers, no "
        "content; personal data per §5 despite opacity.",
    ),
    # --- redis ---------------------------------------------------------------
    DataResource(
        key="redis:trigger-dirty",
        store=Store.REDIS,
        owner="member = user_id",
        classification=Classification.OPS,
        disposal="Transient wake-up set (worker/enqueue.py); membership is a "
        "hint, drain is idempotent per trigger signature (D-031).",
        notes="literal agenthu:trigger:dirty",
    ),
    DataResource(
        key="redis:storage-orphans",
        store=Store.REDIS,
        owner="member = object key (user-resolvable via file_objects)",
        classification=Classification.OPS,
        disposal="Best-effort orphan object markers (worker/enqueue.py SPOP "
        "is destructive); the durable data_cleanup_items queue supersedes "
        "this pattern for lifecycle cleanup (A-draft §2.5).",
        notes="literal agenthu:storage:orphans",
    ),
    DataResource(
        key="redis:arq-managed",
        store=Store.REDIS,
        owner="library-managed (arq queue/results/health keys)",
        classification=Classification.OPS,
        disposal="arq job/result keys live and die with Redis; jobs are "
        "re-derivable, ledger rows are authoritative.",
        notes="arq-namespace keys are library-internal, not scanned",
    ),
    # --- object storage ------------------------------------------------------
    DataResource(
        key="object-storage:file-blobs",
        store=Store.OBJECT_STORAGE,
        owner="key = file_objects.storage_key (uuid-scheme, user-resolvable)",
        content_fields=("blob bytes",),
        classification=Classification.USER_CONTENT,
        disposal="Object delete with versions/copies; permissions errors are "
        "not completion (A-draft §2.5); orphan deletes drain via the durable "
        "queue.",
    ),
    # --- local client (documentation entries; owner: P0-2/P0-4) --------------
    DataResource(
        key="local:desktop-sqlite",
        store=Store.LOCAL_CLIENT,
        owner="owner-namespaced since P0-2 (pending_events/sync_state/focus_draft keyed by owner)",
        classification=Classification.USER_CONTENT,
        disposal="Local cleanup is client-side verified cleanup (SQLite/WAL) "
        "and is reported separately from server receipts (E7-7).",
    ),
    DataResource(
        key="local:web-localStorage",
        store=Store.LOCAL_CLIENT,
        owner="owner-namespaced queue/draft/corrupt-backup keys (P0-2)",
        classification=Classification.USER_CONTENT,
        disposal="Local deletion does not touch another account's namespace.",
    ),
    DataResource(
        key="local:stronghold",
        store=Store.LOCAL_CLIENT,
        owner="token slot (single, overwritten on login)",
        classification=Classification.CREDENTIAL,
        disposal="Credentials never cloud-exported; cleared on logout/"
        "account cleanup (B contract).",
    ),
)


@dataclass
class InventoryReport:
    unregistered_tables: list[str] = field(default_factory=list)
    unknown_registry_tables: list[str] = field(default_factory=list)
    unregistered_redis_literals: list[str] = field(default_factory=list)
    stale_redis_entries: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (
            self.unregistered_tables
            or self.unknown_registry_tables
            or self.unregistered_redis_literals
            or self.stale_redis_entries
        )


def graph_version() -> str:
    """Stable content digest of the dependency-graph definition itself.

    Previews and confirmations bind to it, so a registry change (new family,
    corrected closure rule) between preview and confirm yields preview_stale
    instead of a silently different deletion scope.
    """

    payload = [
        [entry.key, entry.store, entry.table or "", entry.owner, list(entry.content_fields)]
        for entry in REGISTRY
    ]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def redis_literals_in_source() -> set[str]:
    """Every `agenthu:` string literal in backend source (fail-closed scan).

    Docstrings count on purpose: if prose introduces a key-looking literal it
    must be registered or reworded — the check must fail, not guess.
    """

    literals: set[str] = set()
    root = Path(__file__).resolve().parent.parent
    for path in sorted(root.rglob("*.py")):
        if path.name == "data_registry.py":
            # This module necessarily spells the registered literals out in
            # its notes; counting them would make the scan self-fulfilling.
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value.startswith("agenthu:")
            ):
                literals.add(node.value)
    return literals


def _registered_redis_literals() -> set[str]:
    return {
        entry.notes.removeprefix("literal ")
        for entry in REGISTRY
        if entry.store == Store.REDIS and entry.notes.startswith("literal ")
    }


def audit_inventory(metadata: type[Base] | None = None) -> InventoryReport:
    """Reconcile ORM tables and Redis literals against the registry."""

    tables: dict[str, Table] = (metadata or Base).metadata.tables
    registered_tables = {
        e.table: e.key for e in REGISTRY if e.store == Store.POSTGRES and e.table is not None
    }
    report = InventoryReport(
        unregistered_tables=sorted(set(tables) - set(registered_tables)),
        unknown_registry_tables=sorted(set(registered_tables) - set(tables)),
    )
    scanned = redis_literals_in_source()
    registered = _registered_redis_literals()
    report.unregistered_redis_literals = sorted(scanned - registered)
    report.stale_redis_entries = sorted(registered - scanned)
    return report
