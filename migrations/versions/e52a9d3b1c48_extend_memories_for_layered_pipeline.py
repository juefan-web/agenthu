"""extend memories for the layered pipeline

Revision ID: e52a9d3b1c48
Revises: d41c8f2a9b07
Create Date: 2026-10-01

M2 slice of the memory schema extension (D-031 §3, full plan in
TASKS/m3-memory-schema-migration.md): subject_key aggregation identity with
the version-aware live-row unique index (B review amendment: built here, not
in two steps), kind (added nullable and backfilled by level — NOT NULL is not
tightened in M2), canonical evidence, the supersedes_id version chain
(ON DELETE SET NULL), validity window, and decision-use telemetry
(use_count/last_used_at count "entered a decision context" only). The GIN
index backs the deletion/dependency lineage queries. The embedding column
(pgvector) is the M3 slice and is not added here.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "e52a9d3b1c48"
down_revision: str | None = "d41c8f2a9b07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("memories", sa.Column("subject_key", sa.Text(), nullable=True))
    op.add_column(
        "memories",
        sa.Column(
            "kind",
            sa.Enum(
                "episode",
                "fact",
                "habit",
                "preference",
                "model",
                name="memory_kind",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "memories",
        sa.Column(
            "evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "memories",
        sa.Column("supersedes_id", sa.UUID(), sa.ForeignKey("memories.id", ondelete="SET NULL"), nullable=True),
    )
    op.add_column("memories", sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True))
    op.add_column("memories", sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "memories",
        sa.Column("use_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column("memories", sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True))
    # kind backfill (implementation pitfall 1): add nullable -> backfill from
    # level (no ambiguity) -> tighten to NOT NULL only if ever needed. L0 rows
    # have no kind equivalent and stay NULL.
    op.execute(
        "UPDATE memories SET kind = CASE level "
        "WHEN 1 THEN 'episode' WHEN 2 THEN 'fact' WHEN 3 THEN 'model' END "
        "WHERE kind IS NULL"
    )
    op.create_index(
        "uq_memories_user_subject_live",
        "memories",
        ["user_id", "subject_key"],
        unique=True,
        postgresql_where=sa.text("subject_key IS NOT NULL AND supersedes_id IS NULL"),
    )
    op.create_index(
        "ix_memories_supersedes",
        "memories",
        ["supersedes_id"],
        unique=False,
        postgresql_where=sa.text("supersedes_id IS NOT NULL"),
    )
    op.create_index(
        "ix_memories_evidence",
        "memories",
        ["evidence"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"evidence": "jsonb_path_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_memories_evidence", table_name="memories")
    op.drop_index("ix_memories_supersedes", table_name="memories")
    op.drop_index("uq_memories_user_subject_live", table_name="memories")
    op.drop_column("memories", "last_used_at")
    op.drop_column("memories", "use_count")
    op.drop_column("memories", "valid_to")
    op.drop_column("memories", "valid_from")
    op.drop_column("memories", "supersedes_id")
    op.drop_column("memories", "evidence")
    op.drop_column("memories", "kind")
    op.drop_column("memories", "subject_key")
