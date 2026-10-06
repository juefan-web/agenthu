"""Add the recover digest, delivery cache and export flag columns (P0-3 slice 2)

Revision ID: b52d7e91ac04
Revises: a9c41f7d2e83
Create Date: 2026-10-06 12:00:00.000000

M5 A-draft §4 (D-036 §8-2, P0-3 slice 2):

- ``data_operations.request_digest``: SHA-256 of the canonical confirm
  request body — the recover path's high-entropy second factor (uniform 404
  anti-enumeration, digest participates in matching).
- ``data_operations.export_include_files``: the one export input beyond the
  idempotency key; replay comparison must cover it.
- ``data_receipts.delivery_*``: the 10-minute encrypted re-delivery cache for
  a lost first 202 (nonce + ciphertext + expiry; one use, then never again).

Ledger shape unchanged: owner_handle VALUE keys, no users FK.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b52d7e91ac04"
down_revision: str | None = "a9c41f7d2e83"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "data_operations", sa.Column("request_digest", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "data_operations",
        sa.Column("export_include_files", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "data_receipts", sa.Column("delivery_nonce", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "data_receipts", sa.Column("delivery_ciphertext", sa.String(length=256), nullable=True)
    )
    op.add_column(
        "data_receipts",
        sa.Column("delivery_expires_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("data_receipts", "delivery_expires_at")
    op.drop_column("data_receipts", "delivery_ciphertext")
    op.drop_column("data_receipts", "delivery_nonce")
    op.drop_column("data_operations", "export_include_files")
    op.drop_column("data_operations", "request_digest")
