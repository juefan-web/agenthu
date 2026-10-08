"""Client-validity invariant for plans.

The desktop client validates every plan response with the frozen Zod contract
(``packages/contracts``), whose ``PlanItemSchema`` requires non-null
``task_id``, ``start_at`` and ``end_at``. A plan violating that shape cannot be
rendered by the client at all, so the Backend must never serve one on a
client-facing path (DECISIONS.md D-023). This module is the single home for the
rule, in both its Python and SQL forms; keep them in sync.
"""

from __future__ import annotations

from sqlalchemy import Exists, or_, select

from backend.models.plan import Plan, PlanItem


def is_client_valid_plan(plan: Plan) -> bool:
    """Whether every plan item satisfies the desktop client's PlanItemSchema.

    ``reason`` is intentionally not checked here: ``client_view.plan_to_client``
    always produces a non-empty value — the fallback chain is item notes
    (nullable since #75) -> v2 basis render (``render_reason``) ->
    ``plan.replan_reason`` (nullable) -> the literal "planned" — covered by
    ``tests/unit/test_client_view.py``. The Python/SQL double validation
    (``is_client_valid_plan`` + ``client_invalid_item_exists``) stays by
    design: the projection boundary keeps checking the client schema.
    """

    return all(
        item.task_id is not None and item.planned_start is not None and item.planned_end is not None
        for item in plan.items
    )


def client_invalid_item_exists() -> Exists:
    """SQL form of ``not is_client_valid_plan`` for use as a query filter.

    Filtering in SQL (rather than scanning a fixed number of rows in Python)
    means a valid plan is never hidden behind several invalid ones.
    """

    return (
        select(PlanItem.id)
        .where(
            PlanItem.plan_id == Plan.id,
            or_(
                PlanItem.task_id.is_(None),
                PlanItem.planned_start.is_(None),
                PlanItem.planned_end.is_(None),
            ),
        )
        .exists()
    )
