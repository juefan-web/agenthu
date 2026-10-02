"""add memories.embedding vector column

Revision ID: b7e4d0a95c13
Revises: f63b7e2a5c91
Create Date: 2026-10-01

M3 pgvector slice (TASKS/m3-memory-schema-migration.md §2 second block): the
extension plus a nullable 1536-dimension embedding column (provider dimension
per D-031 §3; changing provider later = dimension migration + full re-embed).
No index yet — HNSW/IVFFlat is deliberately deferred until scale is measured
(task doc §8, first open question). Requires the database image to carry the
extension (compose `db` now uses pgvector/pgvector:pg16).
"""

from alembic import op
import sqlalchemy as sa

from pgvector.sqlalchemy import Vector

revision: str = "b7e4d0a95c13"
down_revision: str | None = "f63b7e2a5c91"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The compose/CI bootstrap user is the cluster superuser, which CREATE
    # EXTENSION requires; IF NOT EXISTS keeps reruns and pre-provisioned
    # databases idempotent.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column("memories", sa.Column("embedding", Vector(1536), nullable=True))


def downgrade() -> None:
    op.drop_column("memories", "embedding")
    # Only this migration in the tree needs the extension, so only its
    # downgrade drops it (task doc §7.3).
    op.execute("DROP EXTENSION IF EXISTS vector")
