"""Pydantic API schemas.

These models are the frozen M0 contract shared with the React/Tauri client
(D-009). Any change here must be accompanied by a contract note and, if
persisted, a migration.
"""

from backend.schemas.audit import AuditLogRead
from backend.schemas.common import ErrorResponse, Page
from backend.schemas.current_state import CurrentStateRead, CurrentStateUpdate
from backend.schemas.event import EventCreate, EventRead
from backend.schemas.file import FileRead, SignedUrl
from backend.schemas.goal import GoalCreate, GoalRead, GoalUpdate
from backend.schemas.memory import MemoryCreate, MemoryRead, MemoryUpdate
from backend.schemas.permission import (
    PermissionCheckRequest,
    PermissionCheckResult,
    PermissionGrantCreate,
    PermissionGrantRead,
    PermissionPolicyRead,
)
from backend.schemas.plan import (
    PlanCreate,
    PlanGenerateRequest,
    PlanItemCreate,
    PlanItemRead,
    PlanItemUpdate,
    PlanRead,
    PlanReplanRequest,
)
from backend.schemas.task import TaskCreate, TaskRead, TaskUpdate
from backend.schemas.user import LoginRequest, Token, UserCreate, UserRead

__all__ = [
    "AuditLogRead",
    "CurrentStateRead",
    "CurrentStateUpdate",
    "ErrorResponse",
    "EventCreate",
    "EventRead",
    "FileRead",
    "GoalCreate",
    "GoalRead",
    "GoalUpdate",
    "LoginRequest",
    "MemoryCreate",
    "MemoryRead",
    "MemoryUpdate",
    "Page",
    "PermissionCheckRequest",
    "PermissionCheckResult",
    "PermissionGrantCreate",
    "PermissionGrantRead",
    "PermissionPolicyRead",
    "PlanCreate",
    "PlanGenerateRequest",
    "PlanItemCreate",
    "PlanItemRead",
    "PlanItemUpdate",
    "PlanRead",
    "PlanReplanRequest",
    "SignedUrl",
    "TaskCreate",
    "TaskRead",
    "TaskUpdate",
    "Token",
    "UserCreate",
    "UserRead",
]
