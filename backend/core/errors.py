"""Unified application error model and HTTP error responses.

The error envelope is part of the frozen contract for M0 and shared with the
React/Tauri client (D-009)::

    {"error": {"code": "not_found", "message": "...", "details": {...}}}
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    """Base class for expected, user-facing errors."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "bad_request"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.details = details or {}


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"


class ValidationError(AppError):
    status_code = 422  # UNPROCESSABLE_CONTENT (renamed in newer Starlette)
    code = "validation_error"


class AuthenticationError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "unauthenticated"


class PermissionDeniedError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "permission_denied"


class PayloadTooLargeError(AppError):
    status_code = 413  # CONTENT_TOO_LARGE (renamed in newer Starlette)
    code = "payload_too_large"


class StorageError(AppError):
    status_code = status.HTTP_502_BAD_GATEWAY
    code = "storage_error"


class ServiceUnavailableError(AppError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "service_unavailable"


def _envelope(
    *,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    status_code: int,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details or {}}},
        headers=headers,
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        headers = {"WWW-Authenticate": "Bearer"} if isinstance(exc, AuthenticationError) else None
        return _envelope(
            code=exc.code,
            message=exc.message,
            details=exc.details,
            status_code=exc.status_code,
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _envelope(
            code="validation_error",
            message="Request validation failed",
            details={"errors": _serialize_errors(exc)},
            status_code=422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _envelope(
            code=_code_for_status(exc.status_code),
            message=str(exc.detail),
            status_code=exc.status_code,
            headers=getattr(exc, "headers", None),
        )


def _serialize_errors(exc: RequestValidationError) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for error in exc.errors():
        serialized.append(
            {
                "loc": list(error.get("loc", ())),
                "msg": error.get("msg", ""),
                "type": error.get("type", ""),
            }
        )
    return serialized


_STATUS_CODES = {
    400: "bad_request",
    401: "unauthenticated",
    403: "permission_denied",
    404: "not_found",
    409: "conflict",
    413: "payload_too_large",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    502: "storage_error",
    503: "service_unavailable",
}


def _code_for_status(status_code: int) -> str:
    return _STATUS_CODES.get(status_code, "error")
