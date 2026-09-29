"""Mapping from domain models to the client contract.

The desktop client validates responses with Zod against ``packages/contracts``.
The client is authoritative for these shapes; this module is the single place
that translates Backend state into them.
"""

from __future__ import annotations

from backend.models.enums import PlanStatus, TaskStatus
from backend.models.focus_session import FocusSession
from backend.schemas.client_contract import (
    ClientCurrentState,
    ClientFocusSession,
    ClientPlan,
    ClientPlanItem,
    ClientTask,
)
from backend.schemas.current_state import CurrentStateRead
from backend.schemas.plan import PlanRead
from backend.schemas.task import TaskRead

_TASK_STATUS = {
    TaskStatus.TODO: "todo",
    TaskStatus.IN_PROGRESS: "in_progress",
    TaskStatus.COMPLETED: "done",
    TaskStatus.CANCELLED: "cancelled",
}
_TASK_STATUS_BY_VALUE = {status.value: mapped for status, mapped in _TASK_STATUS.items()}

_PLAN_STATUS = {
    PlanStatus.DRAFT: "draft",
    PlanStatus.PENDING_CONFIRMATION: "draft",
    PlanStatus.CONFIRMED: "confirmed",
    PlanStatus.COMPLETED: "completed",
    PlanStatus.SUPERSEDED: "superseded",
    # The client has no "cancelled" plan state; the closest terminal state is
    # "superseded". Documented in DECISIONS.md.
    PlanStatus.CANCELLED: "superseded",
}
_PLAN_STATUS_BY_VALUE = {status.value: mapped for status, mapped in _PLAN_STATUS.items()}


def task_status_for_client(status: TaskStatus | str) -> str:
    if isinstance(status, TaskStatus):
        return _TASK_STATUS[status]
    return _TASK_STATUS_BY_VALUE.get(str(status), "todo")


def plan_status_for_client(status: PlanStatus | str) -> str:
    if isinstance(status, PlanStatus):
        return _PLAN_STATUS[status]
    return _PLAN_STATUS_BY_VALUE.get(str(status), "draft")


def task_to_client(task: TaskRead) -> ClientTask:
    return ClientTask(
        id=task.id,
        title=task.title,
        due_at=task.deadline,
        estimate_minutes=task.estimated_duration_minutes,
        status=task_status_for_client(task.status),
        source_event_ids=task.related_event_ids,
        description=task.description,
        goal_id=task.goal_id,
        actual_duration_minutes=task.actual_duration_minutes,
        priority=task.priority,
        completed_at=task.completed_at,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def _plan_item_reason(item, plan: PlanRead) -> str:
    if item.notes:
        return item.notes
    strategy = plan.basis.get("strategy") if isinstance(plan.basis, dict) else None
    if isinstance(strategy, str) and strategy:
        return strategy
    if plan.replan_reason:
        return plan.replan_reason
    return "planned"


def plan_to_client(plan: PlanRead) -> ClientPlan:
    items = [
        ClientPlanItem(
            task_id=item.task_id,
            start_at=item.planned_start,
            end_at=item.planned_end,
            reason=_plan_item_reason(item, plan),
            id=item.id,
            title=item.title,
            order_index=item.order_index,
            planned_minutes=item.planned_minutes,
            status=item.status.value,
            actual_minutes=item.actual_minutes,
        )
        for item in plan.items
    ]
    return ClientPlan(
        id=plan.id,
        generated_at=plan.created_at,
        items=items,
        confirmation_required=plan.status in (PlanStatus.DRAFT, PlanStatus.PENDING_CONFIRMATION),
        status=plan_status_for_client(plan.status),
        title=plan.title,
        goal_id=plan.goal_id,
        basis=plan.basis,
        permission_level=plan.permission_level,
        replan_reason=plan.replan_reason,
        confirmed_at=plan.confirmed_at,
        cancelled_at=plan.cancelled_at,
        completed_at=plan.completed_at,
    )


def current_state_to_client(state: CurrentStateRead) -> ClientCurrentState:
    # Effective label (override first, then the D-027 derived chain) is
    # computed server-side; the client contract only sees the final string.
    context = state.context_label if isinstance(state.context_label, str) else None
    tasks = [task_to_client(task) for task in state.pending_tasks]
    return ClientCurrentState(
        version=state.version,
        updated_at=state.updated_at,
        now=state.current_time,
        context=context,
        tasks=tasks,
        available_minutes=state.available_minutes,
        current_context=state.current_context,
        current_task=task_to_client(state.current_task) if state.current_task else None,
        pending_tasks=tasks,
        current_plan=plan_to_client(state.current_plan) if state.current_plan else None,
        recent_state=state.recent_state,
        current_time=state.current_time,
    )


def focus_session_to_client(session: FocusSession) -> ClientFocusSession:
    return ClientFocusSession(
        id=session.id,
        task_id=session.task_id,
        started_at=session.started_at,
        ended_at=session.ended_at,
        actual_minutes=session.actual_minutes,
        status=session.status.value,
        deviation_note=session.deviation_note,
        user_id=session.user_id,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )
