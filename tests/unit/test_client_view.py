from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from backend.models.enums import PlanItemStatus, PlanStatus
from backend.schemas.plan import PlanItemRead, PlanRead
from backend.services.client_view import plan_to_client


def _plan(*, notes: str | None, basis: dict, replan_reason: str | None) -> PlanRead:
    now = datetime.now(UTC)
    item = PlanItemRead(
        id=uuid.uuid4(),
        plan_id=uuid.uuid4(),
        task_id=uuid.uuid4(),
        title="Study",
        order_index=0,
        planned_start=now,
        planned_end=now + timedelta(minutes=30),
        planned_minutes=30,
        status=PlanItemStatus.PENDING,
        actual_minutes=None,
        result=None,
        notes=notes,
    )
    return PlanRead(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        goal_id=None,
        replaces_plan_id=None,
        title="Today",
        status=PlanStatus.PENDING_CONFIRMATION,
        basis=basis,
        permission_level=2,
        generated_by="deterministic_planner",
        replan_reason=replan_reason,
        execution_result=None,
        confirmed_at=None,
        cancelled_at=None,
        completed_at=None,
        items=[item],
        created_at=now,
        updated_at=now,
    )


def test_plan_item_reason_falls_back_to_strategy() -> None:
    client_plan = plan_to_client(
        _plan(notes=None, basis={"strategy": "deadline_then_priority"}, replan_reason=None)
    )
    assert client_plan.items[0].reason == "deadline_then_priority"


def test_plan_item_reason_prefers_notes() -> None:
    client_plan = plan_to_client(
        _plan(notes="User note", basis={"strategy": "x"}, replan_reason=None)
    )
    assert client_plan.items[0].reason == "User note"


def test_plan_item_reason_never_empty() -> None:
    client_plan = plan_to_client(_plan(notes=None, basis={}, replan_reason=None))
    assert client_plan.items[0].reason
