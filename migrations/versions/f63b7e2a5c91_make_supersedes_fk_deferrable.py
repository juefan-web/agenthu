"""make supersedes FK deferrable

Revision ID: f63b7e2a5c91
Revises: e52a9d3b1c48
Create Date: 2026-10-01

The superseded-by chain write order is fixed by the partial unique index: the
old row must retire (supersedes_id := new row id) BEFORE the new live row
inserts, otherwise two live rows share the key at statement time. A partial
unique index cannot be deferred in PostgreSQL, so the FK is made DEFERRABLE
INITIALLY DEFERRED instead — the pointer is validated at commit, when the
new row exists. Standard version-chain table practice; no data change.
"""

from alembic import op
import sqlalchemy as sa

revision: str = "f63b7e2a5c91"
down_revision: str | None = "e52a9d3b1c48"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("memories_supersedes_id_fkey", "memories", type_="foreignkey")
    op.create_foreign_key(
        None,
        "memories",
        "memories",
        ["supersedes_id"],
        ["id"],
        ondelete="SET NULL",
        deferrable=True,
        initially="DEFERRED",
    )


def downgrade() -> None:
    op.drop_constraint("memories_supersedes_id_fkey", "memories", type_="foreignkey")
    op.create_foreign_key(
        None,
        "memories",
        "memories",
        ["supersedes_id"],
        ["id"],
        ondelete="SET NULL",
    )
