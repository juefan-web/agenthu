"""Reference invalidation for deleted chat messages (B contract §5).

Deleting a message (or archiving its session, which cascades message
soft-deletes) must flip every stored DecisionBasis reference that cites it
to ``source_deleted`` in the same transaction — the client renders the
dead-source badge from server state and never guesses. The scans cover the
two faces where references actually persist: ``agent_runs.decision_basis``
and ``pending_actions.basis``. Both are plain JSONB columns, so in-place
mutation must be flagged for the unit of work to notice.

Scan scope is every run/action row of the user — fine at current corpus
size; revisit with the retrieval-redo bucket when runs grow into the
thousands per user.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, attributes

from backend.models.agent import AgentRun, PendingAction

SOURCE_DELETED = "source_deleted"


def _resolved_message_ids(reference: dict) -> set[str]:
    """The message ids one chat_message reference resolves to."""

    ids: set[str] = set()
    if reference.get("kind") != "chat_message":
        return ids
    if isinstance(reference.get("id"), str):
        ids.add(reference["id"])
    locator = reference.get("locator")
    if isinstance(locator, dict) and isinstance(locator.get("message_id"), str):
        ids.add(locator["message_id"])
    return ids


def _flip_references(document: dict | None, deleted: set[str]) -> bool:
    """Flip chat_message references citing ``deleted``; True when changed."""

    if not isinstance(document, dict):
        return False
    references = document.get("references")
    if not isinstance(references, list):
        return False
    changed = False
    for reference in references:
        if (
            isinstance(reference, dict)
            and _resolved_message_ids(reference) & deleted
            and reference.get("state") != SOURCE_DELETED
        ):
            reference["state"] = SOURCE_DELETED
            changed = True
    return changed


def invalidate_chat_message_references(
    session: Session, *, user_id: uuid.UUID, message_ids: set[uuid.UUID]
) -> None:
    """Mark stored basis references to the given messages source_deleted."""

    deleted = {str(message_id) for message_id in message_ids}
    if not deleted:
        return
    for run in session.scalars(
        select(AgentRun).where(AgentRun.user_id == user_id, AgentRun.decision_basis.isnot(None))
    ):
        if _flip_references(run.decision_basis, deleted):
            attributes.flag_modified(run, "decision_basis")
    for action in session.scalars(
        select(PendingAction).where(
            PendingAction.user_id == user_id, PendingAction.basis.isnot(None)
        )
    ):
        if _flip_references(action.basis, deleted):
            attributes.flag_modified(action, "basis")
