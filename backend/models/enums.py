"""Domain enumerations and the SQLAlchemy enum helper.

Enums are stored as ``VARCHAR`` + ``CHECK`` constraints (``native_enum=False``) so
that adding a member is a normal migration and does not require altering a native
PostgreSQL enum type. Member names equal values for stable JSON round-tripping.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum

from sqlalchemy import Enum as SAEnum


def sa_enum(enum_cls: type[StrEnum], name: str) -> SAEnum:
    """Build a portable SQLAlchemy enum column type."""

    return SAEnum(
        enum_cls,
        name=name,
        native_enum=False,
        length=32,
        create_constraint=True,
        validate_strings=True,
    )


class GoalStatus(StrEnum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    ARCHIVED = "ARCHIVED"


class TaskStatus(StrEnum):
    TODO = "TODO"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PlanStatus(StrEnum):
    DRAFT = "DRAFT"
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    SUPERSEDED = "SUPERSEDED"


class PlanItemStatus(StrEnum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"


class FocusSessionStatus(StrEnum):
    # Values match the client contract (packages/contracts FocusSessionSchema).
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class MemoryCorrectionStatus(StrEnum):
    UNREVIEWED = "UNREVIEWED"
    CONFIRMED = "CONFIRMED"
    CORRECTED = "CORRECTED"
    REJECTED = "REJECTED"


class MemoryKind(StrEnum):
    """Structural memory kind (D-031 §3), orthogonal to ``level``."""

    EPISODE = "episode"
    FACT = "fact"
    HABIT = "habit"
    PREFERENCE = "preference"
    MODEL = "model"


class MemoryLevel(IntEnum):
    """L0 raw event -> L1 experience -> L2 stable fact -> L3 personal model."""

    L0_EVENT = 0
    L1_EXPERIENCE = 1
    L2_FACT = 2
    L3_MODEL = 3


class AuditActor(StrEnum):
    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"


class AuditDecision(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_CONFIRMATION = "require_confirmation"


class DataOperationKind(StrEnum):
    """Lifecycle operation kinds (M5 A-draft §4): export or deletion only."""

    EXPORT = "export"
    DELETION = "deletion"


class DataOperationStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    RETRY_WAIT = "RETRY_WAIT"
    READY = "READY"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"


class DataOperationPhase(StrEnum):
    """Durable phase checkpoints (A-draft §4); deletion runs the four phases."""

    EXPORT_COLLECT = "export_collect"
    EXPORT_PACKAGE = "export_package"
    EXPORT_VERIFY = "export_verify"
    DELETE_FENCE = "delete_fence"
    DELETE_RELATIONAL = "delete_relational"
    DELETE_OBJECTS = "delete_objects"
    DELETE_VERIFY = "delete_verify"


class CleanupItemState(StrEnum):
    PENDING = "PENDING"
    CLAIMED = "CLAIMED"
    DONE = "DONE"
    FAILED = "FAILED"


class CleanupItemAction(StrEnum):
    """What the durable cleanup executor must do for one item (P0-3 wires it)."""

    DELETE_RELATIONAL = "delete_relational"
    DELETE_OBJECT = "delete_object"
    CLEAR_REDIS = "clear_redis"
    VERIFY_ABSENT = "verify_absent"


class DataBarrierScope(StrEnum):
    """Barrier breadth (A-draft §2): account fences everything; source/memory
    fence the target closure plus affected derivations."""

    ACCOUNT = "account"
    SOURCE = "source"
    MEMORY = "memory"


class DataBarrierState(StrEnum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
