"""HTTP middleware: request id and best-effort audit trail."""

from __future__ import annotations

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from backend.db.session import session_scope
from backend.services.audit import safe_record_audit

logger = logging.getLogger(__name__)

_AUDITED_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_SKIP_PREFIXES = ("/health", "/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a request id and expose it in the response headers."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request.state.request_id = request_id
        start = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time-Ms"] = f"{(time.perf_counter() - start) * 1000:.2f}"
        return response


class AuditMiddleware(BaseHTTPMiddleware):
    """Record mutating requests in the audit trail.

    Best-effort: an audit write failure must never break the user's request.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        path = request.url.path
        if request.method not in _AUDITED_METHODS or path.startswith(_SKIP_PREFIXES):
            return response

        user_id = getattr(request.state, "user_id", None)
        actor = getattr(request.state, "actor", "anonymous" if user_id is None else "user")
        duration_ms = int((time.perf_counter() - start) * 1000)
        try:
            with session_scope() as session:
                safe_record_audit(
                    session,
                    action=f"{request.method.lower()} {path}",
                    actor=actor,
                    user_id=user_id,
                    method=request.method,
                    path=path,
                    status_code=response.status_code,
                    duration_ms=duration_ms,
                    permission_level=2,
                    decision="allow" if response.status_code < 400 else "deny",
                    ip_address=request.client.host if request.client else None,
                    user_agent=request.headers.get("user-agent"),
                )
        except Exception:  # pragma: no cover - defensive
            logger.warning("Audit middleware could not persist a record", exc_info=True)
        return response
