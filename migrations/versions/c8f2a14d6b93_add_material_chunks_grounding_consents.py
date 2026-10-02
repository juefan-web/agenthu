"""add material_chunks + grounding_consents, file_objects.course_name

Revision ID: c8f2a14d6b93
Revises: b7e4d0a95c13
Create Date: 2026-10-02

M3 materials ingestion slice (TASKS/m3-materials-ingestion.md §1). Two
user-scoped tables plus the course key on file_objects. ``material_chunks``
reuses the pgvector extension installed by b7e4d0a95c13 (its downgrade owns
DROP EXTENSION; this one only drops its own objects). The embedding column
width (1536) matches memories.embedding per D-031 §3 — same provider
dimension, different data category (documents vs. memories), so the columns
are not merged.
"""

from alembic import op
import sqlalchemy as sa

from pgvector.sqlalchemy import Vector

revision: str = "c8f2a14d6b93"
down_revision: str | None = "b7e4d0a95c13"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "file_objects", sa.Column("course_name", sa.String(300), nullable=True)
    )

    op.create_table(
        "material_chunks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "file_id",
            sa.Uuid(),
            sa.ForeignKey("file_objects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("scanner_version", sa.String(64), nullable=False),
        sa.Column("scan_status", sa.String(16), nullable=False),
        sa.Column(
            "scan_flags",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column("embedding_model", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("file_id", "chunk_index", name="uq_material_chunks_file_index"),
        sa.CheckConstraint(
            "scan_status IN ('clean', 'flagged')",
            name="ck_material_chunks_scan_status",
        ),
    )
    op.create_index(
        "ix_material_chunks_user_file", "material_chunks", ["user_id", "file_id"]
    )

    op.create_table(
        "grounding_consents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("course_name", sa.String(300), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("consent_text_version", sa.String(32), nullable=False),
        sa.Column("consented_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "course_name", name="uq_grounding_consents_user_course"),
    )


def downgrade() -> None:
    op.drop_table("grounding_consents")
    op.drop_index("ix_material_chunks_user_file", table_name="material_chunks")
    op.drop_table("material_chunks")
    op.drop_column("file_objects", "course_name")
