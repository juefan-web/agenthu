from __future__ import annotations

from fastapi import APIRouter

from backend.api.v1 import (
    agent_runs,
    audit,
    auth,
    chat,
    current_state,
    events,
    files,
    focus_sessions,
    goals,
    jobs,
    material,
    material_answers,
    memory,
    model_context_consent,
    notification_preferences,
    pending_actions,
    permissions,
    plans,
    tasks,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(events.router)
api_router.include_router(tasks.router)
api_router.include_router(focus_sessions.router)
api_router.include_router(goals.router)
api_router.include_router(current_state.router)
api_router.include_router(memory.router)
api_router.include_router(plans.router)
api_router.include_router(files.router)
api_router.include_router(permissions.router)
api_router.include_router(audit.router)
api_router.include_router(jobs.router)
api_router.include_router(material.router)
api_router.include_router(material_answers.router)
api_router.include_router(agent_runs.router)
api_router.include_router(pending_actions.router)
api_router.include_router(chat.router)
api_router.include_router(notification_preferences.router)
api_router.include_router(model_context_consent.router)

__all__ = ["api_router"]
