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

# Keys that must never be persisted in audit details. Since D-034 the filter
# is RECURSIVE: nested JSONB used to pass through whole, letting a banned key
# hide one level down. Content-bearing keys (chat/material originals) are
# denied too — audit keeps ids, names, versions, hashes, counts and durations.
_REDACTED_KEYS = {
    "password",
    "hashed_password",
    "token",
    "access_token",
    "refresh_token",
    "id_token",
    "api_key",
    "private_key",
    "secret",
    "cookie",
    "set_cookie",
    "authorization",
    "credential",
    "content",
    "content_raw",
    "body",
    "text",
    "quote",
    "chunk_text",
    "message",
    "message_content",
    "chat",
    "transcript",
    "prompt",
    "lat",
    "lon",
    "latitude",
    "longitude",
    "precise_location",
}

# Safety net for allowed keys: a value that fits no legitimate audit purpose
# but could smuggle raw material/chat text is truncated hard.
_MAX_DETAIL_STRING = 200
_MAX_DEPTH = 6


def _redact_scalar(key: str, value: Any) -> Any:
    if key.lower() in _REDACTED_KEYS:
        return "[redacted]"
    if isinstance(value, str) and len(value) > _MAX_DETAIL_STRING:
        return value[:_MAX_DETAIL_STRING] + "…[truncated]"
    return value


def redact(details: dict[str, Any] | None) -> dict[str, Any]:
    """Recursive deny-list redaction (nested dicts/lists included)."""

    if not details:
        return {}

    def walk(value: Any, key: str, depth: int) -> Any:
        if depth > _MAX_DEPTH:
            return "[max_depth]"
        if isinstance(value, dict):
            return {k: walk(v, k, depth + 1) for k, v in value.items()}
        if isinstance(value, list):
            return [walk(item, key, depth + 1) for item in value]
        return _redact_scalar(key, value)

    return {key: walk(value, key, 0) for key, value in details.items()}


def redact_allowlist(details: dict[str, Any] | None, allowed: frozenset[str]) -> dict[str, Any]:
    """Recursive WHITELIST for agent-path audits (D-034 §3.2).

    Only keys in ``allowed`` survive at any depth — unknown keys are dropped
    rather than marked, so a schema drift cannot smuggle new content fields
    in. The survivors then pass the recursive deny-list, so a banned key is
    doubly blocked even if someone adds it to the allowlist.
    """

    if not details:
        return {}

    def walk(value: Any, key: str, depth: int) -> Any:
        if depth > _MAX_DEPTH:
            return "[max_depth]"
        if isinstance(value, dict):
            return {
                k: walk(v, k, depth + 1) for k, v in value.items() if k in allowed or key in allowed
            }
        if isinstance(value, list):
            return [walk(item, key, depth + 1) for item in value]
        return _redact_scalar(key, value)

    return {key: walk(value, key, 0) for key, value in details.items() if key in allowed}


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
    """Best-effort audit write that never breaks the caller.

    The write runs inside its own SAVEPOINT: on failure only that savepoint
    rolls back. A bare ``session.rollback()`` here would destroy the caller's
    uncommitted work (e.g. a just-inserted Event), which is exactly what this
    helper must never do.
    """

    try:
        with session.begin_nested():
            record_audit(session, **kwargs)
    except Exception:  # pragma: no cover - defensive
        logger.exception("Failed to write audit record", extra={"action": kwargs.get("action")})
