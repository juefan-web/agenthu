"""Add the durable storage orphan keys table (P0-3 slice 3)

Revision ID: c7a3f02d9e51
Revises: b52d7e91ac04
Create Date: 2026-10-06 16:00:00.000000

M5 A-draft §2.5 (P0-3 slice 3): the plain file-delete path's object-delete
marker moves from the destructive Redis SPOP set to a durable work table
registered in the SAME transaction as the relational delete. A crash after
a Redis pop could forget the object; a crash anywhere now leaves a
claimable row and the drain cron (lease + frozen backoff ladder) retries
it. The state enum reuses the cleanup-item values (PENDING/CLAIMED/DONE/
FAILED — non-native VARCHAR + CHECK, same as data_cleanup_items), so no
new PG type is introduced.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c7a3f02d9e51"
down_revision: str | None = "b52d7e91ac04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "storage_orphan_keys",
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column(
            "state",
            sa.Enum(
                "PENDING",
                "CLAIMED",
                "DONE",
                "FAILED",
                name="data_cleanup_state",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key", name="uq_storage_orphan_keys_key"),
    )
    op.create_index(
        "ix_storage_orphan_keys_due",
        "storage_orphan_keys",
        ["state", "next_retry_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_storage_orphan_keys_due", table_name="storage_orphan_keys")
    op.drop_table("storage_orphan_keys")
