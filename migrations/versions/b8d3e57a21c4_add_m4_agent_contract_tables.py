"""add M4 agent contract tables (D-034, slice A1)

Revision ID: b8d3e57a21c4
Revises: e3a7c59f21b8
Create Date: 2026-10-03

Contract codification slice (TASKS/m4-implementation-slices.md A1): five new
tables (agent_runs, pending_actions, chat_sessions, chat_messages,
notification_preferences) plus the memories.content_revision prefix-ordering
key (backfilled with sha256(content) — updated_at cannot serve because the
use-telemetry writer bumps it). The pg_trgm extension and chat FTS index
arrive with the A3 retrieval slice, not here. permission_grants needs no DDL:
revoked_at already exists and NULL means unrevoked, so the soft-revoke change
is API semantics only (DELETE stamps revoked_at instead of deleting).
"""

from alembic import op
import sqlalchemy as sa

revision: str = "b8d3e57a21c4"
down_revision: str | None = "e3a7c59f21b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # D-034 soft revoke: uniqueness moves from "one row per (user, action)" to
    # "one ACTIVE row" — revoked history accumulates for audit reference, and
    # re-granting after a revoke mints a new row instead of reviving the old
    # one. The index keeps the constraint's name (they share a namespace).
    op.drop_constraint(
        "uq_permission_grants_user_action", "permission_grants", type_="unique"
    )
    op.create_index(
        "uq_permission_grants_user_action",
        "permission_grants",
        ["user_id", "action"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )

    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("invocation_kind", sa.String(length=24), nullable=False),
        sa.Column(
            "trigger_ref",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "parent_run_id",
            sa.Uuid(),
            sa.ForeignKey("agent_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("operation_key", sa.String(length=255), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("client_request_id", sa.String(length=255), nullable=True),
        sa.Column("runner_version", sa.String(length=64), nullable=False),
        sa.Column("tool_registry_version", sa.String(length=64), nullable=False),
        sa.Column("prompt_version", sa.String(length=32), nullable=False),
        sa.Column(
            "provider",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "context_snapshot",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("decision_basis", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column(
            "tool_calls",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("lease", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("budget", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("usage", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("result", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("failure", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
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
        sa.CheckConstraint(
            "status IN ('QUEUED', 'RUNNING', 'WAITING_CONFIRMATION', "
            "'SUCCEEDED', 'FAILED', 'CANCELLED')",
            name="ck_agent_runs_status",
        ),
        sa.CheckConstraint(
            "invocation_kind IN ('chat', 'proactive_trigger', "
            "'pending_action_resume', 'retry')",
            name="ck_agent_runs_invocation_kind",
        ),
        sa.UniqueConstraint(
            "user_id", "operation_key", "attempt_no", name="uq_agent_runs_op_attempt"
        ),
    )
    op.create_index(
        "ix_agent_runs_user_created", "agent_runs", ["user_id", "created_at"]
    )
    op.create_index(
        "ix_agent_runs_unfinished",
        "agent_runs",
        ["status"],
        postgresql_where=sa.text(
            "status IN ('QUEUED', 'RUNNING', 'WAITING_CONFIRMATION')"
        ),
    )
    op.create_index(
        "uq_agent_runs_client_request",
        "agent_runs",
        ["user_id", "client_request_id"],
        unique=True,
        postgresql_where=sa.text("client_request_id IS NOT NULL"),
    )
    op.create_index(
        "uq_agent_runs_active_trigger",
        "agent_runs",
        ["user_id", sa.text("(trigger_ref ->> 'trigger_signature')")],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('QUEUED', 'RUNNING', 'WAITING_CONFIRMATION') "
            "AND trigger_ref ->> 'trigger_signature' IS NOT NULL"
        ),
    )

    op.create_table(
        "pending_actions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_run_id",
            sa.Uuid(),
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tool_name", sa.String(length=64), nullable=False),
        sa.Column("tool_version", sa.String(length=32), nullable=False),
        sa.Column("tool_title", sa.String(length=200), nullable=False),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("required_level", sa.Integer(), nullable=False),
        sa.Column(
            "args",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("args_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "display",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "basis",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("execution_lease", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column(
            "grant_id",
            sa.Uuid(),
            sa.ForeignKey("permission_grants.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("grant_snapshot", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ignored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("result", sa.dialects.postgresql.JSONB(), nullable=True),
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
        sa.CheckConstraint(
            "status IN ('PENDING', 'CONFIRMED', 'EXECUTING', 'SUCCEEDED', "
            "'FAILED_RETRYABLE', 'FAILED', 'IGNORED', 'EXPIRED')",
            name="ck_pending_actions_status",
        ),
        sa.CheckConstraint(
            "required_level BETWEEN 0 AND 3", name="ck_pending_actions_level"
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND max_attempts >= 1",
            name="ck_pending_actions_attempts",
        ),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_pending_actions_idem"),
    )
    op.create_index(
        "ix_pending_actions_user_status_created",
        "pending_actions",
        ["user_id", "status", "created_at"],
    )
    op.create_index(
        "ix_pending_actions_expiry",
        "pending_actions",
        ["expires_at"],
        postgresql_where=sa.text("status = 'PENDING'"),
    )

    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
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
        "ix_chat_sessions_user_updated", "chat_sessions", ["user_id", "updated_at"]
    )

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "agent_run_id",
            sa.Uuid(),
            sa.ForeignKey("agent_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("role IN ('user', 'assistant')", name="ck_chat_messages_role"),
    )
    op.create_index(
        "ix_chat_messages_session_created", "chat_messages", ["session_id", "created_at"]
    )
    op.create_index(
        "ix_chat_messages_user_created", "chat_messages", ["user_id", "created_at"]
    )

    op.create_table(
        "notification_preferences",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column(
            "enabled_categories",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("quiet_hours_start", sa.String(length=5), nullable=True),
        sa.Column("quiet_hours_end", sa.String(length=5), nullable=True),
        sa.Column("daily_budget", sa.Integer(), nullable=False),
        sa.Column(
            "budget_date", sa.Date(), server_default=sa.func.current_date(), nullable=False
        ),
        sa.Column("sent_count", sa.Integer(), nullable=False),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint("daily_budget >= 0", name="ck_notification_preferences_budget"),
        sa.CheckConstraint(
            "quiet_hours_start IS NULL AND quiet_hours_end IS NULL "
            "OR quiet_hours_start IS NOT NULL AND quiet_hours_end IS NOT NULL",
            name="ck_notification_preferences_quiet_hours_pair",
        ),
        sa.UniqueConstraint("user_id", name="uq_notification_preferences_user"),
    )
    op.create_index(
        "ix_notification_preferences_budget_date",
        "notification_preferences",
        ["budget_date"],
    )

    # Prefix-ordering key for the agent context assembly: sha256(content) is
    # immutable where updated_at is not (use telemetry bumps it). Existing
    # rows are backfilled in-place; new rows get it from the model's
    # before_insert listener.
    op.add_column(
        "memories",
        sa.Column("content_revision", sa.String(length=64), nullable=True),
    )
    op.execute(
        "UPDATE memories SET content_revision = "
        "encode(sha256(convert_to(content, 'UTF8')), 'hex')"
    )
    op.alter_column("memories", "content_revision", nullable=False)


def downgrade() -> None:
    op.drop_index("uq_permission_grants_user_action", table_name="permission_grants")
    # Revoked history cannot exist under the pre-D-034 hard-delete semantics,
    # so reverting drops it — the same rows the old DELETE endpoint would
    # have removed.
    op.execute("DELETE FROM permission_grants WHERE revoked_at IS NOT NULL")
    op.create_unique_constraint(
        "uq_permission_grants_user_action", "permission_grants", ["user_id", "action"]
    )

    op.alter_column("memories", "content_revision", nullable=True)
    op.drop_column("memories", "content_revision")

    op.drop_index(
        "ix_notification_preferences_budget_date", table_name="notification_preferences"
    )
    op.drop_table("notification_preferences")

    op.drop_index("ix_chat_messages_user_created", table_name="chat_messages")
    op.drop_index("ix_chat_messages_session_created", table_name="chat_messages")
    op.drop_table("chat_messages")

    op.drop_index("ix_chat_sessions_user_updated", table_name="chat_sessions")
    op.drop_table("chat_sessions")

    op.drop_index("ix_pending_actions_expiry", table_name="pending_actions")
    op.drop_index(
        "ix_pending_actions_user_status_created", table_name="pending_actions"
    )
    op.drop_table("pending_actions")

    op.drop_index("uq_agent_runs_active_trigger", table_name="agent_runs")
    op.drop_index("uq_agent_runs_client_request", table_name="agent_runs")
    op.drop_index("ix_agent_runs_unfinished", table_name="agent_runs")
    op.drop_index("ix_agent_runs_user_created", table_name="agent_runs")
    op.drop_table("agent_runs")
