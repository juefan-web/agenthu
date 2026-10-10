"""Deletion-closure enumeration over the registered families (P0-3 slice 1).

The single source previews and confirmations are both built from: for one
DeleteTarget it enumerates the exact row ids per family plus object-storage
keys, so preview counts, the preview digest and the durable cleanup items
all describe the SAME closure (A-draft §1: export, deletion and verification
use one graph).

Slice-1 scope: the direct families and the derivation edges that exist
today — events→tasks via ``task_events``, events→memories via
``source_event_ids`` UNION canonical ``evidence`` containment plus
memory→memory evidence edges to a fixpoint (keyed-L2 lineage, external
review #6), files→chunks/answers via ``file_id``/``citations``,
sessions→messages via ``session_id``, memory ``supersedes`` chains. The
projection families the slice-2 executor recomputes appear as recompute
effects; plan-item basis closure lands with that executor wiring.

Ownership precedes content everywhere (§3): every query starts from
``user_id``, and a target id that is missing or belongs to someone else is
a 404, never a silent skip.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import Select, or_, select, tuple_
from sqlalchemy.orm import Session

from backend.core.errors import NotFoundError
from backend.models.agent import AgentRun, PendingAction, PendingActionMutation
from backend.models.audit import AuditLog
from backend.models.chat import ChatMessage, ChatSession
from backend.models.consent import ModelContextConsent
from backend.models.current_state import CurrentState
from backend.models.data_lifecycle import DataSuppression
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
from backend.services.data_lifecycle import owner_handle_of

TARGET_CLOSURE = "target_closure"
DERIVED_CLOSURE = "derived_closure"
CHAIN_CLOSURE = "supersedes_chain"
RECOMPUTE = "projection_recompute"
REDACT_90D = "redact_not_delete_90d"
# Slice-2 adjudication ① (task doc §2A): a task whose D-028 anchor
# (source, source_upstream_id) matches a deleted event is that event's
# continuous projection and dies whole; a task merely CORRELATED via a
# task_events edge survives with the edge removed.
ANCHORED_DERIVATION = "anchored_derivation"
DECORRELATED = "decorrelated"
ACCOUNT_TERMINATION = "account_termination"

_LIMITATIONS: tuple[str, ...] = (
    "Encrypted DB/object backups roll for at most 30 days; until then deleted "
    "content may exist in backups and cannot be selectively erased.",
    "Provider-side retention follows the provider's policy; store=false does "
    "not guarantee zero retention upstream.",
    "Local client stores (offline SQLite, localStorage, Stronghold) are "
    "cleared by the client cleanup flow, not by this backend operation.",
    "Copies the user already downloaded are outside remote deletion.",
)


@dataclass(frozen=True)
class FamilyImpact:
    """One family's row-level outcome inside the closure."""

    resource_type: str
    delete_ids: tuple[str, ...] = ()
    recompute_ids: tuple[str, ...] = ()
    redact_ids: tuple[str, ...] = ()
    reason_code: str = TARGET_CLOSURE


@dataclass(frozen=True)
class ClosureResult:
    impacts: tuple[FamilyImpact, ...] = field(default=())
    object_keys: tuple[str, ...] = ()
    limitations: tuple[str, ...] = _LIMITATIONS
    # "{family}:{id}:{updated_at}" per timestamped row — the digest binds
    # content versions, not row counts (A-draft §2.1).
    content_versions: tuple[str, ...] = ()

    def delete_ids_of(self, resource_type: str) -> tuple[str, ...]:
        for impact in self.impacts:
            if impact.resource_type == resource_type:
                return impact.delete_ids
        return ()


def _rows(session: Session, stmt: Select) -> list:
    return list(session.execute(stmt).all())


def _uuids(values) -> list[uuid.UUID]:
    """Target dicts round-trip through JSONB, so ids may arrive as strings."""

    return [uuid.UUID(value) if isinstance(value, str) else value for value in values]


def _evidence_citing_ids(
    session: Session,
    user_id: uuid.UUID,
    *,
    event_ids: set[str] | frozenset[str] = frozenset(),
    memory_ids: set[str] | frozenset[str] = frozenset(),
) -> set[str]:
    """Memories whose canonical evidence cites any of the given events or
    memories (external review #6): keyed L2s are written with empty
    ``source_event_ids`` — their lineage lives only in ``evidence``. The
    jsonb containment (@>) below is what the ix_memories_evidence GIN
    index (jsonb_path_ops) serves; per-id disjuncts bitmap-OR into one
    index scan."""

    clauses = [
        Memory.evidence.contains([{"type": evidence_type, "id": value}])
        for evidence_type, id_set in (("event", event_ids), ("memory", memory_ids))
        for value in id_set
    ]
    if not clauses:
        return set()
    return {
        str(row[0])
        for row in _rows(session, select(Memory.id).where(Memory.user_id == user_id, or_(*clauses)))
    }


def _impact_with_versions(
    resource_type: str, rows: list, *, reason_code: str = TARGET_CLOSURE
) -> tuple[FamilyImpact, tuple[str, ...]]:
    """Build an impact plus version stamps from (id, updated_at) rows."""

    ids = tuple(str(row[0]) for row in rows)
    versions = tuple(
        f"{resource_type}:{row[0]}:{row[1].isoformat()}" for row in rows if row[1] is not None
    )
    return FamilyImpact(resource_type, delete_ids=ids, reason_code=reason_code), versions


def _owned_ids_or_404(
    session: Session, model, user_id: uuid.UUID, ids: list[uuid.UUID], what: str
) -> tuple[str, ...]:
    """All requested ids must exist AND belong to the user (ownership 404)."""

    found = {
        str(row_id)
        for (row_id,) in session.execute(
            select(model.id).where(model.user_id == user_id, model.id.in_(ids))
        ).all()
    }
    wanted = {str(value) for value in ids}
    if found != wanted:
        raise NotFoundError(f"{what} not found")
    return tuple(sorted(wanted))


def _account_closure(session: Session, user_id: uuid.UUID, handle: str) -> ClosureResult:
    impacts: list[FamilyImpact] = []
    versions: list[str] = []

    # (model, registry key, version-stamp column) — ChatMessage is immutable
    # and deliberately has no updated_at; created_at is its content version.
    direct = (
        (Event, "events", Event.updated_at),
        (Task, "tasks", Task.updated_at),
        (Goal, "goals", Goal.updated_at),
        (FocusSession, "focus_sessions", FocusSession.updated_at),
        (Plan, "plans", Plan.updated_at),
        (Memory, "memories", Memory.updated_at),
        (FileObject, "file_objects", FileObject.updated_at),
        (MaterialChunk, "material_chunks", MaterialChunk.updated_at),
        (MaterialAnswer, "material_answers", MaterialAnswer.updated_at),
        (GroundingConsent, "grounding_consents", GroundingConsent.updated_at),
        (ModelContextConsent, "model_context_consents", ModelContextConsent.updated_at),
        (PermissionGrant, "permission_grants", PermissionGrant.updated_at),
        (NotificationPreference, "notification_preferences", NotificationPreference.updated_at),
        (ChatSession, "chat_sessions", ChatSession.updated_at),
        (ChatMessage, "chat_messages", ChatMessage.created_at),
        (AgentRun, "agent_runs", AgentRun.updated_at),
        (PendingAction, "pending_actions", PendingAction.updated_at),
    )
    for model, key, stamp in direct:
        rows = _rows(session, select(model.id, stamp).where(model.user_id == user_id))
        impact, stamps_v = _impact_with_versions(key, rows)
        impacts.append(impact)
        versions.extend(stamps_v)

    plan_item_rows = _rows(
        session,
        select(PlanItem.id, PlanItem.updated_at)
        .join(Plan, PlanItem.plan_id == Plan.id)
        .where(Plan.user_id == user_id),
    )
    impact, stamps = _impact_with_versions("plan_items", plan_item_rows)
    impacts.append(impact)
    versions.extend(stamps)

    edge_rows = _rows(
        session,
        select(task_events.c.task_id, task_events.c.event_id)
        .join(Task, task_events.c.task_id == Task.id)
        .where(Task.user_id == user_id),
    )
    impacts.append(
        FamilyImpact(
            "task_events",
            delete_ids=tuple(f"{row[0]}:{row[1]}" for row in edge_rows),
            reason_code=DERIVED_CLOSURE,
        )
    )

    mutation_rows = _rows(
        session,
        select(PendingActionMutation.id, PendingActionMutation.updated_at)
        .join(PendingAction, PendingActionMutation.pending_action_id == PendingAction.id)
        .where(PendingAction.user_id == user_id),
    )
    impact, stamps = _impact_with_versions("pending_action_mutations", mutation_rows)
    impacts.append(impact)
    versions.extend(stamps)

    # The users row itself is closure content too: "row itself" per the
    # registry family — deleting it mid-phase is safe because every other
    # item is id-addressed and CASCADE wipes are order-independent.
    impacts.append(FamilyImpact("users", delete_ids=(str(user_id),)))
    user_stamp = session.scalar(select(User.updated_at).where(User.id == user_id))
    if user_stamp is not None:
        versions.append(f"users:{user_id}:{user_stamp.isoformat()}")

    # Projections rebuild from what remains (nothing, for an account).
    projection = session.scalar(select(CurrentState.id).where(CurrentState.user_id == user_id))
    if projection is not None:
        impacts.append(
            FamilyImpact("current_states", recompute_ids=(str(projection),), reason_code=RECOMPUTE)
        )

    # Real row ids, not placeholders: the slice-2 executor's redact path
    # locates rows by id (audit user_id SET-NULLs away once the users row
    # dies, so ids are the only stable anchor; count semantics unchanged).
    audit_rows = _rows(session, select(AuditLog.id).where(AuditLog.user_id == user_id))
    if audit_rows:
        impacts.append(
            FamilyImpact(
                "audit_logs",
                redact_ids=tuple(str(row[0]) for row in audit_rows),
                reason_code=REDACT_90D,
            )
        )

    # Suppression records end with the account (A-draft §5 retention: a
    # suppression lives until re-authorization OR account deletion). The
    # other ledger tables deliberately stay OUT: receipts keep their 90-day
    # window, and the operation/barrier/cleanup-item rows of this very
    # deletion must survive their own execution.
    suppression_rows = _rows(
        session, select(DataSuppression.id).where(DataSuppression.owner_handle == handle)
    )
    if suppression_rows:
        impacts.append(
            FamilyImpact(
                "data_suppressions",
                delete_ids=tuple(str(row[0]) for row in suppression_rows),
                reason_code=ACCOUNT_TERMINATION,
            )
        )

    object_keys = tuple(
        row[0]
        for row in _rows(
            session, select(FileObject.storage_key).where(FileObject.user_id == user_id)
        )
    )
    return ClosureResult(
        impacts=tuple(impacts), object_keys=object_keys, content_versions=tuple(versions)
    )


def _event_closure(session: Session, user_id: uuid.UUID, ids: list[uuid.UUID]) -> ClosureResult:
    impacts: list[FamilyImpact] = []
    versions: list[str] = []
    limitations: list[str] = []

    event_ids = _owned_ids_or_404(session, Event, user_id, ids, "event")
    impacts.append(FamilyImpact("events", delete_ids=event_ids))
    versions.extend(
        f"events:{row[0]}:{row[1].isoformat()}"
        for row in _rows(session, select(Event.id, Event.updated_at).where(Event.id.in_(ids)))
        if row[1] is not None
    )

    # Adjudication ① (§2A): partition affected tasks by D-028 anchor, not by
    # correlation edges. Anchored tasks are content copies and die whole
    # (with their focus sessions via FK CASCADE); merely correlated tasks
    # survive with the edge removed (FK CASCADE on the event side).
    anchors = [
        (row[0], row[1]["upstream_id"])
        for row in _rows(
            session,
            select(Event.source, Event.provenance).where(Event.id.in_(ids)),
        )
        if isinstance(row[1], dict)
        and isinstance(row[1].get("upstream_id"), str)
        and row[1]["upstream_id"]
    ]
    anchored_task_rows: list = []
    if anchors:
        anchored_task_rows = _rows(
            session,
            select(Task.id, Task.updated_at)
            .where(Task.user_id == user_id)
            .where(tuple_(Task.source, Task.source_upstream_id).in_(anchors)),
        )
    if anchored_task_rows:
        impact, stamps = _impact_with_versions(
            "tasks", anchored_task_rows, reason_code=ANCHORED_DERIVATION
        )
        impacts.append(impact)
        versions.extend(stamps)
        anchored_ids = [
            uuid.UUID(row[0]) if isinstance(row[0], str) else row[0] for row in anchored_task_rows
        ]
        focus_rows = _rows(
            session,
            select(FocusSession.id, FocusSession.updated_at).where(
                FocusSession.task_id.in_(anchored_ids)
            ),
        )
        impact, stamps = _impact_with_versions(
            "focus_sessions", focus_rows, reason_code=DERIVED_CLOSURE
        )
        impacts.append(impact)
        versions.extend(stamps)
        limitations.append(
            "Plan items referencing deleted tasks survive with their task link "
            "nulled (plan history is user work); titles copied from the deleted "
            "source may persist there until the plan is recomputed."
        )

    # Correlation records that die: edges to the deleted events (user-made
    # correlations; the surviving tasks keep their content) plus every edge
    # of an anchored task (dies with the task).
    edge_rows = _rows(
        session,
        select(task_events.c.task_id, task_events.c.event_id).where(
            or_(
                task_events.c.event_id.in_(ids),
                task_events.c.task_id.in_(
                    [row[0] for row in anchored_task_rows] if anchored_task_rows else []
                ),
            )
        ),
    )
    if edge_rows:
        impacts.append(
            FamilyImpact(
                "task_events",
                delete_ids=tuple(f"{row[0]}:{row[1]}" for row in edge_rows),
                reason_code=DECORRELATED,
            )
        )

    event_id_strings = {str(value) for value in ids}
    # Citing memories: the denormalized source_event_ids subset (the L1
    # write path) UNION canonical evidence containment (the keyed-L2 path —
    # empty source_event_ids, lineage only in evidence; external review #6),
    # then memory→memory evidence edges extend the set to a fixpoint.
    citing_ids = {
        str(row[0])
        for row in _rows(
            session,
            select(Memory.id, Memory.source_event_ids).where(Memory.user_id == user_id),
        )
        if row[1] and set(row[1]) & event_id_strings
    } | _evidence_citing_ids(session, user_id, event_ids=event_id_strings)
    while True:
        grown = citing_ids | _evidence_citing_ids(session, user_id, memory_ids=citing_ids)
        if grown == citing_ids:
            break
        citing_ids = grown
    if citing_ids:
        impact, stamps = _impact_with_versions(
            "memories",
            _rows(
                session,
                select(Memory.id, Memory.updated_at)
                .where(Memory.id.in_(_uuids(citing_ids)))
                .order_by(Memory.id),
            ),
            reason_code=DERIVED_CLOSURE,
        )
        impacts.append(impact)
        versions.extend(stamps)

    projection = session.scalar(select(CurrentState.id).where(CurrentState.user_id == user_id))
    if projection is not None and (anchored_task_rows or citing_ids):
        impacts.append(
            FamilyImpact("current_states", recompute_ids=(str(projection),), reason_code=RECOMPUTE)
        )

    return ClosureResult(
        impacts=tuple(impacts),
        content_versions=tuple(versions),
        limitations=tuple(_LIMITATIONS + tuple(limitations)),
    )


def _file_closure(session: Session, user_id: uuid.UUID, ids: list[uuid.UUID]) -> ClosureResult:
    impacts: list[FamilyImpact] = []
    versions: list[str] = []

    file_ids = _owned_ids_or_404(session, FileObject, user_id, ids, "file")
    impacts.append(FamilyImpact("file_objects", delete_ids=file_ids))
    versions.extend(
        f"file_objects:{row[0]}:{row[1].isoformat()}"
        for row in _rows(
            session, select(FileObject.id, FileObject.updated_at).where(FileObject.id.in_(ids))
        )
        if row[1] is not None
    )

    chunk_rows = _rows(
        session,
        select(MaterialChunk.id, MaterialChunk.updated_at)
        .where(MaterialChunk.user_id == user_id)
        .where(MaterialChunk.file_id.in_(ids)),
    )
    impact, stamps = _impact_with_versions(
        "material_chunks", chunk_rows, reason_code=DERIVED_CLOSURE
    )
    impacts.append(impact)
    versions.extend(stamps)

    file_id_strings = set(file_ids)
    answers = [
        row
        for row in _rows(
            session,
            select(MaterialAnswer.id, MaterialAnswer.updated_at, MaterialAnswer.citations).where(
                MaterialAnswer.user_id == user_id
            ),
        )
        if any(str(item.get("file_id")) in file_id_strings for item in row[2])
    ]
    if answers:
        impacts.append(
            FamilyImpact(
                "material_answers",
                delete_ids=tuple(str(row[0]) for row in answers),
                reason_code=DERIVED_CLOSURE,
            )
        )
        versions.extend(
            f"material_answers:{row[0]}:{row[1].isoformat()}"
            for row in answers
            if row[1] is not None
        )

    object_keys = tuple(
        row[0]
        for row in _rows(session, select(FileObject.storage_key).where(FileObject.id.in_(ids)))
    )
    return ClosureResult(
        impacts=tuple(impacts), object_keys=object_keys, content_versions=tuple(versions)
    )


def _chat_session_closure(
    session: Session, user_id: uuid.UUID, ids: list[uuid.UUID]
) -> ClosureResult:
    impacts: list[FamilyImpact] = []
    versions: list[str] = []

    session_ids = _owned_ids_or_404(session, ChatSession, user_id, ids, "chat session")
    impacts.append(FamilyImpact("chat_sessions", delete_ids=session_ids))
    versions.extend(
        f"chat_sessions:{row[0]}:{row[1].isoformat()}"
        for row in _rows(
            session, select(ChatSession.id, ChatSession.updated_at).where(ChatSession.id.in_(ids))
        )
        if row[1] is not None
    )

    message_rows = _rows(
        session,
        select(ChatMessage.id, ChatMessage.created_at)
        .where(ChatMessage.user_id == user_id)
        .where(ChatMessage.session_id.in_(ids)),
    )
    impact, stamps = _impact_with_versions(
        "chat_messages", message_rows, reason_code=DERIVED_CLOSURE
    )
    impacts.append(impact)
    versions.extend(stamps)
    return ClosureResult(impacts=tuple(impacts), content_versions=tuple(versions))


def _chat_message_closure(
    session: Session, user_id: uuid.UUID, ids: list[uuid.UUID]
) -> ClosureResult:
    message_ids = _owned_ids_or_404(session, ChatMessage, user_id, ids, "chat message")
    versions = tuple(
        f"chat_messages:{row[0]}:{row[1].isoformat()}"
        for row in _rows(
            session, select(ChatMessage.id, ChatMessage.created_at).where(ChatMessage.id.in_(ids))
        )
        if row[1] is not None
    )
    return ClosureResult(
        impacts=(FamilyImpact("chat_messages", delete_ids=message_ids),),
        content_versions=versions,
    )


def _memory_closure(session: Session, user_id: uuid.UUID, ids: list[uuid.UUID]) -> ClosureResult:
    _owned_ids_or_404(session, Memory, user_id, ids, "memory")
    # include_history is enforced at the schema layer (Literal[True]); here
    # the closure IS the whole chain: successors via supersedes_id, older
    # rows via "who points into the closure", plus memories whose canonical
    # EVIDENCE cites a closure member (keyed L2 lineage — external review
    # #6), all iterated to a fixpoint.
    reachable = {str(value) for value in ids}
    while True:
        successors = _rows(
            session,
            select(Memory.supersedes_id).where(
                Memory.user_id == user_id,
                Memory.id.in_(_uuids(reachable)),
                Memory.supersedes_id.is_not(None),
            ),
        )
        older = _rows(
            session,
            select(Memory.id).where(
                Memory.user_id == user_id,
                Memory.supersedes_id.in_(_uuids(reachable)),
            ),
        )
        grown = (
            reachable
            | {str(row[0]) for row in successors}
            | {str(row[0]) for row in older}
            | _evidence_citing_ids(session, user_id, memory_ids=reachable)
        )
        if grown == reachable:
            break
        reachable = grown
    version_rows = _rows(
        session,
        select(Memory.id, Memory.updated_at)
        .where(Memory.id.in_(_uuids(reachable)))
        .order_by(Memory.id),
    )
    impact, stamps = _impact_with_versions("memories", version_rows, reason_code=CHAIN_CLOSURE)
    return ClosureResult(impacts=(impact,), content_versions=stamps)


def enumerate_closure(session: Session, *, user_id: uuid.UUID, target: dict) -> ClosureResult:
    """The one graph: closure enumeration for a validated DeleteTarget dict."""

    kind = target["kind"]
    if kind == "account":
        return _account_closure(session, user_id, handle=owner_handle_of(session, user_id))
    if kind == "source":
        source_kind = target["source_kind"]
        ids = _uuids(target["ids"])
        if source_kind == "event":
            return _event_closure(session, user_id, ids)
        if source_kind == "file":
            return _file_closure(session, user_id, ids)
        if source_kind == "chat_session":
            return _chat_session_closure(session, user_id, ids)
        if source_kind == "chat_message":
            return _chat_message_closure(session, user_id, ids)
        raise ValueError(f"unsupported source kind: {source_kind}")
    if kind == "memory":
        return _memory_closure(session, user_id, _uuids(target["ids"]))
    raise ValueError(f"unsupported target kind: {kind}")
