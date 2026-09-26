"""Audit trail helpers.

Every user action, Agent tool call, permission decision, failure and retry
should be auditable. Audit records must never contain raw secrets, chat
content, audio or precise location data.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.orm import Session

from backend.models.audit import AuditLog

logger = logging.getLogger(__name__)

# Keys that must never be persisted in audit details.
_REDACTED_KEYS = {
    "password",
    "hashed_password",
    "token",
    "access_token",
    "refresh_token",
    "secret",
    "cookie",
    "authorization",
    "content_raw",
    "audio",
    "lat",
    "lon",
    "latitude",
    "longitude",
}


def redact(details: dict[str, Any] | None) -> dict[str, Any]:
    if not details:
        return {}
    return {
        key: "[redacted]" if key.lower() in _REDACTED_KEYS else value
        for key, value in details.items()
    }


def record_audit(
    session: Session,
    *,
    action: str,
    actor: str = "user",
    user_id: uuid.UUID | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    method: str | None = None,
    path: str | None = None,
    status_code: int | None = None,
    duration_ms: int | None = None,
    permission_level: int | None = None,
    decision: str | None = None,
    details: dict[str, Any] | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    commit: bool = False,
) -> AuditLog:
    entry = AuditLog(
        user_id=user_id,
        actor=actor,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        method=method,
        path=path,
        status_code=status_code,
        duration_ms=duration_ms,
        permission_level=permission_level,
        decision=decision,
        details=redact(details),
        ip_address=ip_address,
        user_agent=user_agent[:500] if user_agent else None,
    )
    session.add(entry)
    session.flush()
    if commit:
        session.commit()
    return entry


def safe_record_audit(session: Session, **kwargs: Any) -> None:
    """Best-effort audit write that never breaks the caller."""

    try:
        record_audit(session, **kwargs)
    except Exception:  # pragma: no cover - defensive
        logger.exception("Failed to write audit record", extra={"action": kwargs.get("action")})
        session.rollback()
