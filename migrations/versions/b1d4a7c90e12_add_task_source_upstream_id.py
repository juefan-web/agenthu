"""add task source_upstream_id

Revision ID: b1d4a7c90e12
Revises: 803f838d3969
Create Date: 2026-09-29

Derived tasks (assignment events, D-028) carry the upstream id from the
event's provenance so ingestion can upsert: (user_id, source,
source_upstream_id) is unique among derived tasks; manual tasks keep NULL
and are unconstrained (multiple NULLs pass PostgreSQL unique indexes).
"""

from alembic import op
import sqlalchemy as sa

revision: str = "b1d4a7c90e12"
down_revision: str | None = "803f838d3969"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("source_upstream_id", sa.String(length=255), nullable=True),
    )
    op.create_unique_constraint(
        "uq_tasks_user_source_upstream",
        "tasks",
        ["user_id", "source", "source_upstream_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_tasks_user_source_upstream", "tasks", type_="unique")
    op.drop_column("tasks", "source_upstream_id")
