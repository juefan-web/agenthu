"""Estimate learning (D-031 §4) — the first real "learn" step.

Reader: the planner ladder ``user > learned:course > learned:ratio > default``
served from L2 memory rows, so every learned number is traceable, correctable
and rejectable through the same Memory surface the user sees.

Writers (``aggregate_*``) run synchronously in the focus.completed handler —
the next plan must already see a completed task's lesson (the E4 spec
generates the plan immediately after seeding). They upsert keyed rows
through the generic superseded-by chain in ``memory_lifecycle``; a REJECTED
live row blocks re-derivation of its subject_key.

Ratio sampling (A erratum proposal 2026-10-01, pending B counter-signature):
only completions executed under a real plan item count — calibration targets
planned estimates, and focus sessions started outside any plan have no true
planned value (the frozen text's "missing -> assume 60" injects noise and,
on shared test accounts, accumulates samples that flip the ladder).
"""

from __future__ import annotations

import math
import statistics
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.enums import MemoryCorrectionStatus, PlanItemStatus, TaskStatus
from backend.models.memory import Memory
from backend.models.task import Task

DEFAULT_TASK_MINUTES = 60
COURSE_SAMPLE_LIMIT = 20
COURSE_MIN_SAMPLES = 2
RATIO_SAMPLE_LIMIT = 20
RATIO_MIN_SAMPLES = 3
CONFIDENCE_CAP = 0.9

RATIO_SUBJECT_KEY = "estimate_ratio:user"


def course_subject_key(course: str) -> str:
    return f"estimate:course:{course}"


@dataclass(frozen=True)
class Estimate:
    minutes: int
    source: str  # default | user | learned:course | learned:ratio
    sample_count: int = 0


def round_half_up(value: float) -> int:
    return math.floor(value + 0.5)


def live_key_row(session: Session, *, user_id: uuid.UUID, subject_key: str) -> Memory | None:
    """The retrievable row for a subject_key: live and not rejected (§5)."""

    return session.scalar(
        select(Memory).where(
            Memory.user_id == user_id,
            Memory.subject_key == subject_key,
            Memory.supersedes_id.is_(None),
            Memory.correction_status != MemoryCorrectionStatus.REJECTED,
        )
    )


def estimate_for_task(session: Session, *, user_id: uuid.UUID, task: Task) -> Estimate:
    """The frozen ladder (D-031 §4); activation is gated by sample count, not
    by the general retrieval confidence floor — the thresholds below ARE the
    estimate reader's gate."""

    if task.estimated_duration_minutes is not None:
        return Estimate(task.estimated_duration_minutes, "user")

    course = task.extra.get("course_name") if isinstance(task.extra, dict) else None
    if isinstance(course, str) and course:
        row = live_key_row(session, user_id=user_id, subject_key=course_subject_key(course))
        if row is not None:
            count = _sample_count(row)
            if count >= COURSE_MIN_SAMPLES and row.source.get("value") is not None:
                return Estimate(int(row.source["value"]), "learned:course", count)

    row = live_key_row(session, user_id=user_id, subject_key=RATIO_SUBJECT_KEY)
    if row is not None:
        count = _sample_count(row)
        if count >= RATIO_MIN_SAMPLES and row.source.get("value") is not None:
            return Estimate(
                round_half_up(DEFAULT_TASK_MINUTES * float(row.source["value"])),
                "learned:ratio",
                count,
            )

    return Estimate(DEFAULT_TASK_MINUTES, "default")


def _sample_count(row: Memory) -> int:
    value = row.source.get("sample_count") if isinstance(row.source, dict) else None
    return value if isinstance(value, int) and value > 0 else 0


def course_actuals(session: Session, *, user_id: uuid.UUID, course: str) -> list[int]:
    """Accumulated actual minutes of the most recent completed tasks in the
    course (D-028 L3 puts course_name into task.extra)."""

    rows = session.execute(
        select(Task.actual_duration_minutes)
        .where(
            Task.user_id == user_id,
            Task.status == TaskStatus.COMPLETED,
            Task.actual_duration_minutes.is_not(None),
            Task.extra["course_name"].as_string() == course,
        )
        .order_by(Task.completed_at.desc().nulls_last())
        .limit(COURSE_SAMPLE_LIMIT)
    ).all()
    return [int(minutes) for (minutes,) in rows if minutes is not None]


def plan_item_ratios(session: Session, *, user_id: uuid.UUID) -> list[float]:
    """actual / planned of the most recent completed plan items (erratum:
    only real planned values count — see the module docstring)."""

    from backend.models.plan import Plan, PlanItem  # local: avoid import cycle

    rows = session.execute(
        select(PlanItem.actual_minutes, PlanItem.planned_minutes)
        .join(Plan, PlanItem.plan_id == Plan.id)
        .where(
            Plan.user_id == user_id,
            PlanItem.status == PlanItemStatus.COMPLETED,
            PlanItem.actual_minutes.is_not(None),
            PlanItem.planned_minutes.is_not(None),
            PlanItem.planned_minutes > 0,
        )
        .order_by(PlanItem.updated_at.desc().nulls_last())
        .limit(RATIO_SAMPLE_LIMIT)
    ).all()
    return [
        actual / planned for actual, planned in rows if actual is not None and planned is not None
    ]


def trimmed_mean(values: list[float]) -> float:
    ordered = sorted(values)
    if len(ordered) >= 4:
        drop = math.ceil(len(ordered) * 0.1)
        ordered = ordered[drop : len(ordered) - drop]
    return statistics.fmean(ordered)
