from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from backend.models.enums import PlanStatus, TaskStatus
from backend.schemas.event import EventCreate
from backend.schemas.task import TaskCreate


def test_event_defaults_are_timezone_aware() -> None:
    event = EventCreate(type="assignment.created")
    assert event.source == "manual"
    assert event.timestamp.tzinfo is not None
    assert event.data == {}
    assert event.context == {}
    assert event.provenance == {}


def test_event_naive_timestamp_is_normalized_to_utc() -> None:
    event = EventCreate(type="assignment.created", timestamp=datetime(2026, 9, 26, 12, 0, 0))
    assert event.timestamp.tzinfo == UTC


@pytest.mark.parametrize("bad_type", ["Assignment Created", "assignment/created", "", "A.B"])
def test_event_type_must_be_normalized_identifier(bad_type: str) -> None:
    with pytest.raises(ValidationError):
        EventCreate(type=bad_type)


def test_task_create_defaults() -> None:
    task = TaskCreate(title="HW2")
    assert task.status == TaskStatus.TODO
    assert task.source == "manual"
    assert task.related_event_ids == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("todo", TaskStatus.TODO),
        ("in_progress", TaskStatus.IN_PROGRESS),
        ("done", TaskStatus.COMPLETED),
        ("cancelled", TaskStatus.CANCELLED),
    ],
)
def test_task_status_accepts_client_values(raw: str, expected: TaskStatus) -> None:
    task = TaskCreate.model_validate({"title": "HW2", "status": raw})
    assert task.status == expected


def test_task_estimated_duration_bounds() -> None:
    with pytest.raises(ValidationError):
        TaskCreate(title="HW2", estimated_duration_minutes=-5)


def test_plan_status_values_are_stable() -> None:
    assert {status.value for status in PlanStatus} == {
        "DRAFT",
        "PENDING_CONFIRMATION",
        "CONFIRMED",
        "CANCELLED",
        "COMPLETED",
        "SUPERSEDED",
    }


def test_naive_datetimes_are_normalized_to_utc() -> None:
    """Every datetime input shares EventCreate's naive->UTC rule (C4)."""

    from datetime import UTC, datetime

    from pydantic import ValidationError

    from backend.schemas.goal import GoalCreate
    from backend.schemas.plan import PlanGenerateRequest, PlanItemCreate
    from backend.schemas.task import TaskCreate

    naive = datetime(2030, 1, 1, 9, 0, 0)
    aware = datetime(2030, 1, 1, 9, 0, 0, tzinfo=UTC)

    # D-028: TaskCreate/TaskUpdate deadlines reject naive values outright.
    with pytest.raises(ValidationError):
        TaskCreate(title="T", deadline=naive)
    cases = [
        TaskCreate(title="T", deadline=aware),
        GoalCreate(title="G", target_date=naive),
        PlanItemCreate(title="P", planned_start=naive, planned_end=naive),
        PlanGenerateRequest(start_at=naive),
    ]
    for model in cases:
        fields = [
            value
            for name in (
                "deadline",
                "target_date",
                "planned_start",
                "planned_end",
                "start_at",
            )
            if isinstance(value := getattr(model, name, None), datetime)
        ]
        assert fields, f"{type(model).__name__} carried no datetime to check"
        for value in fields:
            assert value.tzinfo is UTC
