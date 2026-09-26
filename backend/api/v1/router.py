from __future__ import annotations

from fastapi import APIRouter

from backend.api.v1 import (
    audit,
    auth,
    current_state,
    events,
    files,
    goals,
    jobs,
    memory,
    permissions,
    plans,
    tasks,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(events.router)
api_router.include_router(tasks.router)
api_router.include_router(goals.router)
api_router.include_router(current_state.router)
api_router.include_router(memory.router)
api_router.include_router(plans.router)
api_router.include_router(files.router)
api_router.include_router(permissions.router)
api_router.include_router(audit.router)
api_router.include_router(jobs.router)

__all__ = ["api_router"]
