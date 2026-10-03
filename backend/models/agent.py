"""Agent runs and pending actions (D-034, M4-A1 contract slice).

``agent_runs`` — one row per Agent *attempt* (not per chat bubble): chat
message, proactive trigger, resume after confirmation or retry each create an
attempt; ``operation_key`` + ``attempt_no`` give the two-level idempotency
(client resends return the first attempt; retries mint a new row under the
same operation). The active-trigger partial unique index dedups proactive
runs per (user, trigger_signature). ``context_snapshot`` stores references
and checksums only — never chat/material originals — so replay answers
``source_deleted`` instead of resurrecting removed data.

``pending_actions`` — the Level 2 confirmation queue (8-state machine,
CONFIRMED never expires per ruling A1). ``idempotency_key`` is fixed at
creation and passed downstream so a retry cannot produce a second side
effect; ``version`` drives optimistic concurrency for confirm/ignore/retry;
``execution_lease`` is the worker claim token watched by the A2 watchdog.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

_RUN_STATUS_VALUES = (
    "'QUEUED', 'RUNNING', 'WAITING_CONFIRMATION', 'SUCCEEDED', 'FAILED', 'CANCELLED'"
)
_INVOCATION_KIND_VALUES = "'chat', 'proactive_trigger', 'pending_action_resume', 'retry'"
_ACTION_STATUS_VALUES = (
    "'PENDING', 'CONFIRMED', 'EXECUTING', 'SUCCEEDED', "
    "'FAILED_RETRYABLE', 'FAILED', 'IGNORED', 'EXPIRED'"
)


class AgentRun(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "agent_runs"
    __table_args__ = (
        UniqueConstraint("user_id", "operation_key", "attempt_no", name="uq_agent_runs_op_attempt"),
        # Client resends of the same logical request must land on the first
        # attempt, never mint a second one.
        Index(
            "uq_agent_runs_client_request",
            "user_id",
            "client_request_id",
            unique=True,
            postgresql_where=text("client_request_id IS NOT NULL"),
        ),
        # Proactive dedup: at most one active run per (user, trigger signature).
        # The expression is parenthesized because PostgreSQL requires parens
        # around index expressions (create_all and the migration must render
        # identical DDL for `alembic check`).
        Index(
            "uq_agent_runs_active_trigger",
            "user_id",
            text("(trigger_ref ->> 'trigger_signature')"),
            unique=True,
            postgresql_where=text(
                "status IN ('QUEUED', 'RUNNING', 'WAITING_CONFIRMATION') "
                "AND trigger_ref ->> 'trigger_signature' IS NOT NULL"
            ),
        ),
        Index("ix_agent_runs_user_created", "user_id", "created_at"),
        Index(
            "ix_agent_runs_unfinished",
            "status",
            postgresql_where=text("status IN ('QUEUED', 'RUNNING', 'WAITING_CONFIRMATION')"),
        ),
        CheckConstraint(f"status IN ({_RUN_STATUS_VALUES})", name="ck_agent_runs_status"),
        CheckConstraint(
            f"invocation_kind IN ({_INVOCATION_KIND_VALUES})",
            name="ck_agent_runs_invocation_kind",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="QUEUED")
    invocation_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    # {kind, event_id?, trigger_signature?, chat_message_id?}
    trigger_ref: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    parent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True
    )
    # Server-side key of the logical workflow; retries keep it, attempts differ.
    operation_key: Mapped[str] = mapped_column(String(255), nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # chat runs derive this as "chat:{session_id}:{client_message_id}" (A2).
    client_request_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    runner_version: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_registry_version: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    # {name, model, capability: "tools"|"text_only"|"none", data_scope, consent_version?}
    provider: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # References + checksums only (state_version, memory/goal/task ids with
    # content revisions, history_message_ids, chunk refs, sections, budget,
    # rendered_context_hash, consents). Never chat/material originals.
    context_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # {basis_version, summary, references[], rule_versions, selected_tool_call_ids}
    decision_basis: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # [{call_id, tool_name, tool_version, args_hash, input_redaction_version,
    #   status, started_at, ended_at, result_ref?, error_code?}]
    tool_calls: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # {claim_token, claimed_by, lease_expires_at, heartbeat_at}
    lease: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # {reserved_total, actual_total}
    budget: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # {input_tokens, output_tokens, tool_tokens}
    usage: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # {summary?, degraded, degrade_code?} — degraded runs are SUCCEEDED with
    # this marker (no DEGRADED terminal state; D-034).
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # {code, retryable, safe_message}
    failure: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class PendingAction(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "pending_actions"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_pending_actions_idem"),
        Index("ix_pending_actions_user_status_created", "user_id", "status", "created_at"),
        Index(
            "ix_pending_actions_expiry",
            "expires_at",
            postgresql_where=text("status = 'PENDING'"),
        ),
        CheckConstraint(f"status IN ({_ACTION_STATUS_VALUES})", name="ck_pending_actions_status"),
        CheckConstraint("required_level BETWEEN 0 AND 3", name="ck_pending_actions_level"),
        CheckConstraint(
            "attempt_count >= 0 AND max_attempts >= 1", name="ck_pending_actions_attempts"
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    agent_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_version: Mapped[str] = mapped_column(String(32), nullable=False)
    tool_title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    # Snapshot of the policy level at creation time: policy revisions must not
    # rewrite how a historical row is interpreted.
    required_level: Mapped[int] = mapped_column(Integer, nullable=False)
    # Redacted, schema-validated intended arguments (never raw model JSON).
    args: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    args_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # {summary, parameters: [{label, value}], impact, risk_note?} — built by
    # the server-side display_builder, safe for direct UI rendering.
    display: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # DecisionBasis: {basis_version, summary, references[], rule_versions,
    # selected_tool_call_ids}. No chain-of-thought.
    basis: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING")
    # Optimistic concurrency for confirm/ignore/retry (409 on mismatch).
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Expiry is settled only from PENDING (ruling A1): once CONFIRMED, the
    # user's intent is settled and time never revokes it.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # {claim_token, claimed_by, lease_expires_at, heartbeat_at}
    execution_lease: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    grant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("permission_grants.id", ondelete="SET NULL"), nullable=True
    )
    # Level 3: {grant_id, scope_hash, checked_at} — re-verified at execution.
    grant_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ignored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    # {code, message} — safe error surfaced to the user (user-attributed
    # subcodes like permission_revoked render as user choices, not faults).
    last_error: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # Action-level structured triple (B1 naming layering: action `result`,
    # tool-call `result_ref`, run-level `result`).
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
