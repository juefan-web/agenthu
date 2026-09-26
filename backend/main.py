"""FastAPI application factory and entrypoint.

Run locally with::

    uvicorn backend.main:app --reload
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from backend import __version__
from backend.api.health import router as health_router
from backend.api.v1.router import api_router
from backend.config import get_settings
from backend.core.errors import register_exception_handlers
from backend.core.logging import configure_logging
from backend.db.session import reset_engine
from backend.middleware import AuditMiddleware, RequestContextMiddleware
from backend.schemas.common import ErrorResponse
from backend.services.storage import get_storage
from backend.worker.queue import close_arq_pool

logger = logging.getLogger(__name__)

_DESCRIPTION = """
Backend, data platform and Agent foundations for the AgentHU Personal AI.

All external sources are normalized into a unified **Event** contract before any
domain logic runs. The Backend is the single source of truth for identity,
permissions, events, tasks, goals, current state, memory, plans and files.

This is the **M0** API surface: engineering baseline plus frozen core contracts.
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    try:
        get_storage()
    except Exception:  # pragma: no cover - depends on external services
        logger.warning("Object storage is not ready at startup", exc_info=True)
    yield
    await close_arq_pool()
    reset_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=f"{settings.app_name} API",
        version=__version__,
        description=_DESCRIPTION,
        lifespan=lifespan,
    )

    if settings.audit_enabled:
        app.add_middleware(AuditMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)
    app.include_router(health_router)
    # Document the shared error envelope on every API operation so it is part of
    # the frozen OpenAPI contract the Flutter client generates from.
    app.include_router(
        api_router,
        prefix=settings.api_v1_prefix,
        responses={
            401: {"model": ErrorResponse, "description": "Unauthenticated"},
            403: {"model": ErrorResponse, "description": "Permission denied"},
            404: {"model": ErrorResponse, "description": "Resource not found"},
            409: {"model": ErrorResponse, "description": "Conflict"},
            422: {"model": ErrorResponse, "description": "Validation error"},
        },
    )

    @app.get("/", tags=["meta"])
    def root() -> dict[str, str]:
        return {
            "name": settings.app_name,
            "version": __version__,
            "docs": "/docs",
            "openapi": "/openapi.json",
            "api": settings.api_v1_prefix,
        }

    def custom_openapi() -> dict[str, object]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
            tags=[
                {"name": "auth", "description": "Registration and JWT authentication."},
                {"name": "events", "description": "Unified fact ingestion and query."},
                {"name": "tasks", "description": "Tasks, deadlines and focus sessions."},
                {"name": "goals", "description": "User goals that shape prioritization."},
                {"name": "current-state", "description": "Projection of the user's present."},
                {"name": "memory", "description": "Traceable personal memory entries."},
                {"name": "plans", "description": "Plans, confirmation and re-planning."},
                {"name": "files", "description": "Object storage metadata and access."},
                {"name": "permissions", "description": "Permission levels and grants."},
                {"name": "audit", "description": "Audit trail."},
                {"name": "jobs", "description": "Asynchronous worker jobs."},
            ],
        )
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi  # type: ignore[method-assign]
    return app


app = create_app()
