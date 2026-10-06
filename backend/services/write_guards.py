"""Barrier / suppression / generation write guards (P0-3 slice 3).

The single façade business write paths call to honor A-draft §2.3/§2.6:
entry and final-write checks against owner barriers and the live
``data_generation``, plus the upstream-suppression check that keeps a
deleted source from resurrecting under a fresh ``client_event_id``.

Everything here raises :class:`WriteBlocked` / :class:`SuppressedSource`
(both ``ConflictError`` subclasses, so HTTP callers map to 409 through the
existing AppError handler) carrying the scope on the exception, so worker
callers can settle runs/actions per A-draft §2.4 (``account_deleted`` /
``source_deleted``) without string-matching messages.
"""

from __future__ import annotations

import hashlib
import hmac
import uuid

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.core.errors import ConflictError
from backend.models.data_lifecycle import DataSuppression
from backend.models.enums import DataBarrierScope
from backend.models.user import User
from backend.services import data_lifecycle as dl
from backend.services.audit import record_audit

#: Rejection reason surfaced to the desktop sync coordinator for a
#: suppressed envelope (plain string — the batch contract has no code enum).
SUPPRESSED_REASON = "source was deleted; explicit re-authorization required to re-import"


def upstream_hmac(source_kind: str, upstream: str) -> str:
    """HMAC-SHA256 of ``{source_kind}:{upstream}`` under the server secret.

    The suppression anchor recorded at confirm time (P0-3 slice 1, task-doc
    formula ``kind:upstream``). No title or content participates.
    """

    key = get_settings().secret_key.encode("utf-8")
    return hmac.new(key, f"{source_kind}:{upstream}".encode(), hashlib.sha256).hexdigest()


def event_anchor_upstream(provenance: dict | None) -> str | None:
    """The connector-level upstream id of an event envelope, if any.

    Mirrors the registration fallback order exactly (``upstream_id`` first,
    event-row id second — but a *new* event cannot know a deleted row's id,
    so interception only ever matches on ``upstream_id``). Events without an
    ``upstream_id`` (manual/test sources) have no anchor and pass through;
    the frozen precondition that connector events must carry one is a
    connector-side discipline (task doc §2B), not enforced here.
    """

    if not isinstance(provenance, dict):
        return None
    value = provenance.get("upstream_id")
    if isinstance(value, str) and value:
        return value
    return None


class WriteBlocked(ConflictError):
    """An ACTIVE barrier covers this write, or the work is generation-stale.

    HTTP callers surface the 409 as-is (``deletion_in_progress`` /
    ``generation_stale``); worker callers read ``scope`` to settle per
    A-draft §2.4: account → ``account_deleted``, source/memory →
    ``source_deleted``.
    """

    def __init__(self, *, scope: str | None = None, generation_stale: bool = False) -> None:
        if generation_stale:
            message = "data generation moved; re-base on current state and retry"
            code = "generation_stale"
        else:
            message = f"an active {scope or 'source'} deletion blocks this write"
            code = "deletion_in_progress"
        super().__init__(message, code=code)
        self.scope = scope
        self.generation_stale = generation_stale

    @property
    def lifecycle_code(self) -> str:
        """The §2.4 terminal-state code for run/action settlement."""

        return "account_deleted" if self.scope == "account" else "source_deleted"


class SuppressedSource(ConflictError):
    """Re-import of a deleted source anchor (A-draft §2.6)."""

    def __init__(self) -> None:
        super().__init__(SUPPRESSED_REASON, code="source_deleted")


def current_generation_of(session: Session, user_id: uuid.UUID) -> int:
    """The owner's live ``data_generation`` (capture point for rechecks)."""

    return session.scalar(select(User.data_generation).where(User.id == user_id)) or 1


def assert_write_allowed(
    session: Session,
    *,
    user_id: uuid.UUID,
    scope: DataBarrierScope,
    target_ids: set[str] | None = None,
    observed_generation: int | None = None,
) -> None:
    """Entry / final-write barrier + generation check (A-draft §2.3).

    Scoped callers MUST pass the ids they are about to touch in the barrier
    target's identity space (B carry ③ on #70: an unsaid id set cannot
    disprove overlap and fails closed). ``observed_generation`` re-checks
    work accepted before an external call before its results are written
    back — stale work raises instead of writing.
    """

    try:
        handle = dl.owner_handle_of(session, user_id)
        dl.assert_writable(
            session,
            owner_handle=handle,
            scope=scope,
            target_ids=target_ids,
            observed_generation=observed_generation,
            user_id=user_id,
        )
    except dl.BarrierConflict as exc:
        raise WriteBlocked(scope=exc.barrier.scope.value) from exc
    except dl.GenerationStale as exc:
        raise WriteBlocked(generation_stale=True) from exc


def is_suppressed(
    session: Session, *, user_id: uuid.UUID, source: str, provenance: dict | None
) -> bool:
    """True when this event's upstream anchor was deleted for this owner.

    Suppression rows are written in the confirm transaction itself, so the
    anchor is blocked from confirm time onward — through the barrier window
    and forever after, until explicit re-authorization releases it.
    """

    upstream = event_anchor_upstream(provenance)
    if upstream is None:
        return False
    try:
        handle = dl.owner_handle_of(session, user_id)
    except dl.LifecycleError:
        return False
    digest = upstream_hmac("event", upstream)
    row = session.scalar(
        select(DataSuppression.id).where(
            DataSuppression.owner_handle == handle,
            DataSuppression.source_kind == "event",
            DataSuppression.upstream_hmac == digest,
            DataSuppression.released_at.is_(None),
        )
    )
    return row is not None


def release_source_suppressions(
    session: Session,
    *,
    user_id: uuid.UUID,
    source_kind: str,
    upstream_ids: list[str],
) -> int:
    """Release suppressed anchors after the user explicitly re-authorized
    the source (A-draft §2.6: re-import stays blocked until then).

    Idempotent; returns how many rows this call released. The audit row
    records only the kind and the count — upstream identities stay HMAC'd.
    The trigger surface (connector re-authorization flow) arrives with
    P0-6; the frozen §4 route matrix deliberately has no release route.
    """

    if not upstream_ids:
        return 0
    handle = dl.owner_handle_of(session, user_id)
    digests = [upstream_hmac(source_kind, upstream) for upstream in upstream_ids]
    result = session.execute(
        update(DataSuppression)
        .where(
            DataSuppression.owner_handle == handle,
            DataSuppression.source_kind == source_kind,
            DataSuppression.upstream_hmac.in_(digests),
            DataSuppression.released_at.is_(None),
        )
        .values(released_at=dl.utcnow())
    )
    released = int(getattr(result, "rowcount", 0) or 0)
    if released:
        record_audit(
            session,
            action="data.suppression_released",
            actor="user",
            user_id=user_id,
            resource_type="data_suppression",
            resource_id=None,
            details={"source_kind": source_kind, "released": int(released)},
        )
    return int(released)
