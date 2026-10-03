"""The global model-context consent gate (D-034 §6.2).

Single read point for the runner and context assembly: an ACTIVE consent
(enabled, not revoked) returns its text version; anything else returns
``None``, and callers must treat ``None`` as "no user context may leave the
backend" — the runner then forces ``capability: "none"`` and the run degrades
to the deterministic path (plans and replan suggestions keep working, which
is the M4 exit criterion's server side).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.base import utcnow
from backend.models.consent import ModelContextConsent
from backend.schemas.consent import MODEL_CONTEXT_CONSENT_TEXT_VERSION


def get_consent_row(session: Session, user_id: uuid.UUID) -> ModelContextConsent | None:
    return session.scalar(select(ModelContextConsent).where(ModelContextConsent.user_id == user_id))


def active_consent_version(session: Session, user_id: uuid.UUID) -> str | None:
    """Consent text version when an active opt-in exists, else ``None``.

    A row disabled after enabling keeps ``enabled=False`` and a stamped
    ``revoked_at``; both conditions are checked explicitly so a partially
    written row can never read as active.
    """

    row = get_consent_row(session, user_id)
    if row is None or not row.enabled or row.revoked_at is not None:
        return None
    return row.consent_text_version


def set_consent(
    session: Session,
    user_id: uuid.UUID,
    *,
    enabled: bool,
    consent_text_version: str,
) -> ModelContextConsent:
    """Idempotent upsert. Opt-in echoes the current text version (stale
    echoes are rejected by the API layer before this call)."""

    row = get_consent_row(session, user_id)
    if row is None:
        row = ModelContextConsent(
            user_id=user_id,
            consent_text_version=consent_text_version,
        )
        session.add(row)
    row.enabled = enabled
    row.consent_text_version = consent_text_version
    if enabled:
        row.consented_at = utcnow()
        row.revoked_at = None
    else:
        row.revoked_at = utcnow()
    session.flush()
    return row


def consent_text_current(version: str) -> bool:
    return version == MODEL_CONTEXT_CONSENT_TEXT_VERSION
