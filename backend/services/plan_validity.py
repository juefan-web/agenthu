"""Client-validity invariant for plans.

The Zod contract (``packages/contracts``) mirrors the backend's nullable
serialization: since #75, ``PlanItemSchema`` accepts explicit ``null``
``task_id`` / ``start_at`` / ``end_at`` (placement may leave a windowless or
taskless item), so the client can structurally render such items. The stricter
non-null invariant kept here is a deliberate server-side design choice, not a
contract constraint: the Backend commits to serving only fully-formed plan
items on client-facing paths. This module is the single home for the rule, in
both its Python and SQL forms; keep them in sync. (DECISIONS.md D-023 records
the rule under its original, pre-#75 contract wording — historical context,
kept as-is.)
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
