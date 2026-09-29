from __future__ import annotations

import logging
from typing import Any

import redis
from fastapi import APIRouter, Response, status
from sqlalchemy import text

from backend import __version__
from backend.api.deps import DBSession, StorageDep
from backend.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health")
def liveness() -> dict[str, Any]:
    settings = get_settings()
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": __version__,
        "environment": settings.environment,
    }


@router.get("/health/ready")
def readiness(response: Response, db: DBSession, storage: StorageDep) -> dict[str, Any]:
    settings = get_settings()
    checks: dict[str, str] = {}
    healthy = True

    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        logger.warning("Readiness: database check failed")
        checks["database"] = "unavailable"
        healthy = False

    client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=2)
    try:
        client.ping()
        checks["redis"] = "ok"
    except Exception:
        logger.warning("Readiness: redis check failed")
        checks["redis"] = "unavailable"
        healthy = False
    finally:
        client.close()

    try:
        storage.ensure_ready()
        checks["object_storage"] = "ok"
    except Exception:
        logger.warning("Readiness: object storage check failed")
        checks["object_storage"] = "unavailable"
        healthy = False

    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ok" if healthy else "degraded", "checks": checks}
