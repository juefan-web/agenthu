"""add the A3 retrieval index (pg_trgm + chat content GIN)

Revision ID: c4f2a8e01d73
Revises: a7d1c93f4e20
Create Date: 2026-10-03

A3 retrieval slice (D-034): pg_trgm explicitly replaces the m4-phase0
tsvector preset (simple has no CJK tokenization and zhparser is not in the
image). The GIN gin_trgm_ops index accelerates ILIKE substring search over
``chat_messages.content``; sub-3-character queries form no trigram and
degrade to an unindexed — still correct — filter. Retrieval eligibility for
deleted messages is enforced in every read/search WHERE clause
(``deleted_at IS NULL``), so soft delete and eligibility drop share one
transaction by construction; there is no separate FTS index to invalidate.
"""

from alembic import op

revision: str = "c4f2a8e01d73"
down_revision: str | None = "a7d1c93f4e20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_index(
        "ix_chat_messages_content_trgm",
        "chat_messages",
        ["content"],
        postgresql_using="gin",
        postgresql_ops={"content": "gin_trgm_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_chat_messages_content_trgm", table_name="chat_messages")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
