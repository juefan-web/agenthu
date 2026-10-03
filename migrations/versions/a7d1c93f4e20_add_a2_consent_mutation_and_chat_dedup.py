"""Add A2 runtime tables and the chat message-level dedup key

Revision ID: a7d1c93f4e20
Revises: b8d3e57a21c4
Create Date: 2026-10-03

Three A2 additions (D-034):

- ``model_context_consents`` — the global "Agent model context" gate
  (default OFF). One row per user, mirroring ``grounding_consents``:
  consent-text version echo plus consented/revoked timestamps.
- ``pending_action_mutations`` — the ``(pending_action_id, mutation_id)``
  response cache so a lost-response resend returns the settled body
  instead of dispatching twice.
- ``chat_messages.client_message_id`` — message-level idempotency (ruling
  A2): ``(session_id, client_message_id)`` partial unique; the run-level
  ``client_request_id`` is derived server-side as
  ``chat:{session_id}:{client_message_id}``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a7d1c93f4e20"
down_revision: str | None = "b8d3e57a21c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_context_consents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("consent_text_version", sa.String(length=32), nullable=False),
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_model_context_consents_user"),
    )

    op.create_table(
        "pending_action_mutations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pending_action_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mutation_id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column(
            "response",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
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
        sa.ForeignKeyConstraint(
            ["pending_action_id"], ["pending_actions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pending_action_id", "mutation_id", name="uq_pending_action_mutations"),
        sa.CheckConstraint("kind IN ('confirm', 'ignore', 'retry')", name="ck_pending_mutations_kind"),
    )

    op.add_column(
        "chat_messages",
        sa.Column("client_message_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "uq_chat_messages_client_id",
        "chat_messages",
        ["session_id", "client_message_id"],
        unique=True,
        postgresql_where=sa.text("client_message_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_chat_messages_client_id", table_name="chat_messages")
    op.drop_column("chat_messages", "client_message_id")
    op.drop_table("pending_action_mutations")
    op.drop_table("model_context_consents")
