"""add plan_items.basis

Revision ID: d41c8f2a9b07
Revises: b1d4a7c90e12
Create Date: 2026-10-01

Per-item structured explainability payload (D-031 §1). The plan-level basis
keeps global entries only (strategy tag, current-state version, horizon) so
it does not grow with task count; the per-item reasons (deadline, slack,
estimate + estimate_source, slot_reason, score parts, at_risk) live here.
Old rows keep NULL — the client contract declares the field optional.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "d41c8f2a9b07"
down_revision: str | None = "b1d4a7c90e12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "plan_items",
        sa.Column("basis", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("plan_items", "basis")
