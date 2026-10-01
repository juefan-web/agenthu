from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from backend.models.enums import PlanItemStatus, PlanStatus
from backend.schemas.plan import PlanItemRead, PlanRead
from backend.services.client_view import plan_to_client


def _plan(
    *, notes: str | None, basis: dict, replan_reason: str | None, item_basis: dict | None = None
) -> PlanRead:
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
        basis=item_basis,
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


def _v2_basis() -> dict:
    return {
        "deadline": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        "slack_minutes": 600,
        "estimate_minutes": 75,
        "estimate_source": "learned:course",
        "sample_count": 2,
        "slot_reason": "今天最长空档",
        "score": {"urgency": 840, "goal": 0, "priority": 0, "total": 840},
        "at_risk": False,
    }


def test_plan_item_reason_renders_from_basis() -> None:
    # D-031 §1: the basis is the record, the reason is a view. The human
    # sentence must exist and never leak internal identifiers.
    client_plan = plan_to_client(
        _plan(notes=None, basis={}, replan_reason=None, item_basis=_v2_basis())
    )
    reason = client_plan.items[0].reason
    assert "预计 75 分钟" in reason
    assert "同课程作业实际用时" in reason
    assert "slots_v2" not in reason


def test_plan_item_reason_prefers_notes() -> None:
    client_plan = plan_to_client(
        _plan(notes="User note", basis={}, replan_reason=None, item_basis=_v2_basis())
    )
    assert client_plan.items[0].reason == "User note"


def test_plan_item_reason_never_empty() -> None:
    # Legacy/manual items without a v2 basis fall back past the (removed)
    # strategy-tag leak to replan_reason / "planned".
    assert plan_to_client(_plan(notes=None, basis={}, replan_reason=None)).items[0].reason
    assert (
        plan_to_client(
            _plan(notes=None, basis={"strategy": "deadline_then_priority"}, replan_reason=None)
        )
        .items[0]
        .reason
        == "planned"
    )
    assert (
        plan_to_client(_plan(notes=None, basis={}, replan_reason="Focus 超时")).items[0].reason
        == "Focus 超时"
    )
