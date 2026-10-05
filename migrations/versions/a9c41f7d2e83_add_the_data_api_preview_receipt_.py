"""Add the data API preview, receipt and suppression tables (P0-3 slice 1)

Revision ID: a9c41f7d2e83
Revises: e6d496a26f09
Create Date: 2026-10-05 23:10:00.000000

M5 A-draft §2+§4 (P0-3 slice 1):

- ``data_previews``: 10-minute digest-bound previews. Plain user data (FK
  users CASCADE) — transient, unlike the ledger below.
- ``data_receipts`` / ``data_suppressions``: ledger rules (owner_handle
  VALUE, no users FK) — both must survive account deletion; receipts store
  only the SHA-256 digest of the one-time capability token.
- ``data_operations.preview_digest`` / ``impact`` and
  ``data_cleanup_items.payload``: the confirm snapshot (exact closure ids)
  the slice-2 executor deletes by, and the replay comparison key.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a9c41f7d2e83"
down_revision: str | None = "e6d496a26f09"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "data_operations", sa.Column("preview_digest", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "data_operations",
        sa.Column("impact", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "data_cleanup_items",
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_table(
        "data_previews",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("target", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("graph_version", sa.String(length=64), nullable=False),
        sa.Column("data_generation", sa.Integer(), nullable=False),
        sa.Column("preview_digest", sa.String(length=64), nullable=False),
        sa.Column("effects", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("limitations", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_data_previews_user_expires",
        "data_previews",
        ["user_id", "expires_at"],
        unique=False,
    )
    op.create_table(
        "data_receipts",
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("owner_handle", sa.String(length=32), nullable=False),
        sa.Column("capability_digest", sa.String(length=64), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.UniqueConstraint("operation_id", name="uq_data_receipts_operation"),
    )
    op.create_index(
        op.f("ix_data_receipts_owner_handle"),
        "data_receipts",
        ["owner_handle"],
        unique=False,
    )
    op.create_table(
        "data_suppressions",
        sa.Column("owner_handle", sa.String(length=32), nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("upstream_hmac", sa.String(length=64), nullable=False),
        sa.Column("raised_generation", sa.Integer(), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_handle", "source_kind", "upstream_hmac", name="uq_data_suppressions_key"
        ),
    )


def downgrade() -> None:
    op.drop_table("data_suppressions")
    op.drop_index(op.f("ix_data_receipts_owner_handle"), table_name="data_receipts")
    op.drop_table("data_receipts")
    op.drop_index("ix_data_previews_user_expires", table_name="data_previews")
    op.drop_table("data_previews")
    op.drop_column("data_cleanup_items", "payload")
    op.drop_column("data_operations", "impact")
    op.drop_column("data_operations", "preview_digest")
