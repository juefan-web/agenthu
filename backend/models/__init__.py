"""Importing this package registers every model with ``Base.metadata``.

Alembic autogenerate and ``create_all`` rely on this module being imported.
"""

from backend.models.audit import AuditLog
from backend.models.current_state import CurrentState
from backend.models.enums import (
    AuditActor,
    AuditDecision,
    FocusSessionStatus,
    GoalStatus,
    MemoryCorrectionStatus,
    MemoryLevel,
    PlanItemStatus,
    PlanStatus,
    TaskStatus,
)
from backend.models.event import Event
from backend.models.file import FileObject
from backend.models.focus_session import FocusSession
from backend.models.goal import Goal
from backend.models.material import GroundingConsent, MaterialChunk
from backend.models.memory import Memory
from backend.models.permission import PermissionGrant
from backend.models.plan import Plan, PlanItem
from backend.models.task import Task, task_events
from backend.models.user import User

__all__ = [
    "AuditActor",
    "AuditDecision",
    "AuditLog",
    "CurrentState",
    "Event",
    "FileObject",
    "FocusSession",
    "FocusSessionStatus",
    "Goal",
    "GoalStatus",
    "GroundingConsent",
    "MaterialChunk",
    "Memory",
    "MemoryCorrectionStatus",
    "MemoryLevel",
    "PermissionGrant",
    "Plan",
    "PlanItem",
    "PlanItemStatus",
    "PlanStatus",
    "Task",
    "TaskStatus",
    "User",
    "task_events",
]
