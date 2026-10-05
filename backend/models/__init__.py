"""Importing this package registers every model with ``Base.metadata``.

Alembic autogenerate and ``create_all`` rely on this module being imported.
"""

from backend.models.agent import AgentRun, PendingAction, PendingActionMutation
from backend.models.audit import AuditLog
from backend.models.chat import ChatMessage, ChatSession
from backend.models.consent import ModelContextConsent
from backend.models.current_state import CurrentState
from backend.models.data_lifecycle import (
    DataBarrier,
    DataCleanupItem,
    DataOperation,
    DataPreview,
    DataReceipt,
    DataSuppression,
)
from backend.models.enums import (
    AuditActor,
    AuditDecision,
    CleanupItemAction,
    CleanupItemState,
    DataBarrierScope,
    DataBarrierState,
    DataOperationKind,
    DataOperationPhase,
    DataOperationStatus,
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
from backend.models.material import GroundingConsent, MaterialAnswer, MaterialChunk
from backend.models.memory import Memory
from backend.models.notification import NotificationPreference
from backend.models.permission import PermissionGrant
from backend.models.plan import Plan, PlanItem
from backend.models.task import Task, task_events
from backend.models.user import User

__all__ = [
    "AgentRun",
    "AuditActor",
    "AuditDecision",
    "AuditLog",
    "ChatMessage",
    "ChatSession",
    "CleanupItemAction",
    "CleanupItemState",
    "CurrentState",
    "DataBarrier",
    "DataBarrierScope",
    "DataBarrierState",
    "DataCleanupItem",
    "DataOperation",
    "DataOperationKind",
    "DataOperationPhase",
    "DataOperationStatus",
    "DataPreview",
    "DataReceipt",
    "DataSuppression",
    "Event",
    "FileObject",
    "FocusSession",
    "FocusSessionStatus",
    "Goal",
    "GoalStatus",
    "GroundingConsent",
    "MaterialAnswer",
    "MaterialChunk",
    "Memory",
    "MemoryCorrectionStatus",
    "MemoryLevel",
    "ModelContextConsent",
    "NotificationPreference",
    "PendingAction",
    "PendingActionMutation",
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
