"""add material_answers (grounded Q&A records)

Revision ID: e3a7c59f21b8
Revises: c8f2a14d6b93
Create Date: 2026-10-02

M3 grounded-answers slice (TASKS/m3-grounded-answers.md §3.5/§6). One row
per answered question: the answer text, surviving machine-verified
citations (snapshot tuples — file_id + checksum pin the version read;
deliberately NOT an FK so deleting a file invalidates citations softly
instead of destroying answer history), the chunk/memory ids that fed the
context, and the model/prompt versions for citation-accuracy measurement.
"""

from alembic import op
import sqlalchemy as sa

revision: str = "e3a7c59f21b8"
down_revision: str | None = "c8f2a14d6b93"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "material_answers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("course_name", sa.String(300), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("grounded", sa.Boolean(), nullable=False),
        sa.Column(
            "citations",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "chunk_ids",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "memory_ids",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("model_version", sa.String(100), nullable=False),
        sa.Column("prompt_version", sa.String(32), nullable=False),
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
    )
    op.create_index(
        "ix_material_answers_user_course_created",
        "material_answers",
        ["user_id", "course_name", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_material_answers_user_course_created", table_name="material_answers"
    )
    op.drop_table("material_answers")
