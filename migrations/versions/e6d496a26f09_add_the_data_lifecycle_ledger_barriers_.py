"""Add the data lifecycle ledger, barriers and generation (P0-1 slice 2)

Revision ID: e6d496a26f09
Revises: 45b7db4cb2cb
Create Date: 2026-10-05 19:01:34.783283

D-036 §8-8 / M5 A-draft §2+§4 substrate:

- ``data_operations`` / ``data_cleanup_items`` / ``data_barriers`` key on the
  opaque ``users.owner_handle`` VALUE with no FK to users, so account deletion
  cannot CASCADE the ledger away and identity is not recoverable from it.
- ``users.owner_handle`` backfills existing rows through the server default
  (``replace(gen_random_uuid()::text, '-', '')``); ``users.data_generation``
  starts at 1 and is bumped transactionally by destructive confirms (the
  producers arrive with the deletion slice P0-3).
- Enum columns keep the ``sa_enum`` VARCHAR+CHECK convention; alembic's
  duplicate rendering of each CHECK is deduped to one constraint per enum.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e6d496a26f09"
down_revision: str | None = "45b7db4cb2cb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "data_operations",
        sa.Column("owner_handle", sa.String(length=32), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "EXPORT",
                "DELETION",
                name="data_operation_kind",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("client_request_id", sa.String(length=128), nullable=False),
        sa.Column("target", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "QUEUED",
                "RUNNING",
                "RETRY_WAIT",
                "READY",
                "COMPLETED",
                "EXPIRED",
                "FAILED",
                name="data_operation_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "phase",
            sa.Enum(
                "EXPORT_COLLECT",
                "EXPORT_PACKAGE",
                "EXPORT_VERIFY",
                "DELETE_FENCE",
                "DELETE_RELATIONAL",
                "DELETE_OBJECTS",
                "DELETE_VERIFY",
                name="data_operation_phase",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("data_generation", sa.Integer(), nullable=False),
        sa.Column("progress_processed", sa.Integer(), nullable=False),
        sa.Column("progress_total", sa.Integer(), nullable=True),
        sa.Column("outstanding_count", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_retryable", sa.Boolean(), nullable=True),
        sa.Column("receipt_id", sa.Uuid(), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint(
            "owner_handle", "kind", "client_request_id", name="uq_data_operations_idem"
        ),
    )
    op.create_index("ix_data_operations_owner", "data_operations", ["owner_handle"], unique=False)
    op.create_index("ix_data_operations_status", "data_operations", ["status"], unique=False)
    op.create_table(
        "data_barriers",
        sa.Column("owner_handle", sa.String(length=32), nullable=False),
        sa.Column(
            "scope",
            sa.Enum(
                "ACCOUNT",
                "SOURCE",
                "MEMORY",
                name="data_barrier_scope",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("target", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "state",
            sa.Enum(
                "ACTIVE",
                "RELEASED",
                name="data_barrier_state",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("raised_generation", sa.Integer(), nullable=False),
        sa.Column("operation_id", sa.Uuid(), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["operation_id"], ["data_operations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_data_barriers_owner_state",
        "data_barriers",
        ["owner_handle", "state"],
        unique=False,
    )
    op.create_table(
        "data_cleanup_items",
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("owner_handle", sa.String(length=32), nullable=False),
        sa.Column("resource_type", sa.String(length=100), nullable=False),
        sa.Column("item_ref", sa.Text(), nullable=False),
        sa.Column(
            "action",
            sa.Enum(
                "DELETE_RELATIONAL",
                "DELETE_OBJECT",
                "CLEAR_REDIS",
                "VERIFY_ABSENT",
                name="data_cleanup_action",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
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
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["operation_id"], ["data_operations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "operation_id",
            "resource_type",
            "item_ref",
            "action",
            name="uq_data_cleanup_items_item",
        ),
    )
    op.create_index(
        "ix_data_cleanup_items_claim",
        "data_cleanup_items",
        ["state", "next_retry_at"],
        unique=False,
    )
    op.create_index(
        "ix_data_cleanup_items_operation",
        "data_cleanup_items",
        ["operation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_data_cleanup_items_owner_handle"),
        "data_cleanup_items",
        ["owner_handle"],
        unique=False,
    )
    # Explicit backfill (no server_default): PG would store a normalized copy
    # of a uuid-generating default expression, which alembic compares
    # textually against the model — permanent false drift. Adding nullable,
    # backfilling, then tightening keeps the catalog and the model identical.
    op.add_column(
        "users",
        sa.Column("owner_handle", sa.String(length=32), nullable=True),
    )
    op.execute(
        "UPDATE users SET owner_handle = replace(gen_random_uuid()::text, '-', '')"
        " WHERE owner_handle IS NULL"
    )
    op.alter_column("users", "owner_handle", existing_type=sa.String(length=32), nullable=False)
    op.add_column(
        "users",
        sa.Column("data_generation", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )
    op.create_unique_constraint("uq_users_owner_handle", "users", ["owner_handle"])


def downgrade() -> None:
    op.drop_constraint("uq_users_owner_handle", "users", type_="unique")
    op.drop_column("users", "data_generation")
    op.drop_column("users", "owner_handle")
    op.drop_index(op.f("ix_data_cleanup_items_owner_handle"), table_name="data_cleanup_items")
    op.drop_index("ix_data_cleanup_items_operation", table_name="data_cleanup_items")
    op.drop_index("ix_data_cleanup_items_claim", table_name="data_cleanup_items")
    op.drop_table("data_cleanup_items")
    op.drop_index("ix_data_barriers_owner_state", table_name="data_barriers")
    op.drop_table("data_barriers")
    op.drop_index("ix_data_operations_status", table_name="data_operations")
    op.drop_index("ix_data_operations_owner", table_name="data_operations")
    op.drop_table("data_operations")
