"""M4 agent contract read shapes (D-034; mirrors the frozen client Zod).

These are the authoritative OpenAPI components for the M4 surface. The
frozen client Zod lives in ``tests/fixtures/client_contract.ts`` (and, once
B1 lands, ``packages/contracts/src/index.ts``) — field-for-field identical,
direction registered in ``backend/scripts/check_contract_drift.py``.

Constraints baked into the shapes (contract §2/§3):
- No chain-of-thought, no prompts, no chat/material originals, no tool
  argument bodies: ``decision_basis`` carries references + rule versions,
  ``tool_calls`` carries the audit skeleton only.
- ``expires_at`` is required and never null (ruling: "confirmed stops
  expiring" is state-machine behavior, not a nulled field).
- ``result.degraded``/``degrade_code`` mark deterministic-fallback success
  (there is no DEGRADED terminal status).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, cast

from pydantic import BaseModel

from backend.models.agent import PendingAction as PendingActionORM
from backend.schemas.common import ORMModel

ReferenceKind = Literal[
    "event",
    "memory",
    "goal",
    "plan",
    "task",
    "material",
    "chat_message",
    "current_state",
]
ReferenceState = Literal["available", "source_deleted", "version_mismatch"]
RunStatus = Literal["QUEUED", "RUNNING", "WAITING_CONFIRMATION", "SUCCEEDED", "FAILED", "CANCELLED"]
InvocationKind = Literal["chat", "proactive_trigger", "pending_action_resume", "retry"]
ProviderCapability = Literal["tools", "text_only", "none"]
PendingStatus = Literal[
    "PENDING",
    "CONFIRMED",
    "EXECUTING",
    "SUCCEEDED",
    "FAILED_RETRYABLE",
    "FAILED",
    "IGNORED",
    "EXPIRED",
]


class DecisionLocator(BaseModel):
    """Position-only locator: identifies a source, never copies its body."""

    page: int | None = None
    quote: str | None = None
    occurred_at: datetime | None = None
    file_id: str | None = None
    checksum: str | None = None
    chunk_id: str | None = None
    span_start: int | None = None
    span_end: int | None = None
    # chat_message references (B4-1): locator only, no content.
    message_id: str | None = None
    # current_state references (B4-2): the projection version at decision time.
    state_version: int | None = None


class DecisionReference(BaseModel):
    kind: ReferenceKind
    id: str
    label: str
    state: ReferenceState | None = None
    locator: DecisionLocator | None = None


class DecisionBasis(BaseModel):
    basis_version: str
    summary: str
    references: list[DecisionReference] = []
    rule_versions: dict[str, str] = {}
    # Server-side field (B1): the UI does not render it, the drift check
    # needs it so both sources stay identical.
    selected_tool_call_ids: list[str] = []


class ProviderInfo(BaseModel):
    name: str
    model: str
    capability: ProviderCapability


class TriggerRef(BaseModel):
    kind: str
    event_id: str | None = None
    trigger_signature: str | None = None
    chat_message_id: str | None = None


class AgentRunToolCallRead(BaseModel):
    """Audit skeleton of one tool call (review-point-6 condition: the
    user-visible audit face must be able to join the run's tool sequence)."""

    call_id: str
    tool_name: str
    tool_version: str
    status: str
    started_at: datetime | None = None
    ended_at: datetime | None = None
    error_code: str | None = None


class RunUsage(BaseModel):
    input_tokens: int
    output_tokens: int
    tool_tokens: int


class RunResult(BaseModel):
    summary: str | None = None
    degraded: bool = False
    degrade_code: str | None = None


class RunFailure(BaseModel):
    code: str
    retryable: bool
    safe_message: str


class AgentRunRead(ORMModel):
    id: uuid.UUID
    status: RunStatus
    invocation_kind: InvocationKind
    trigger_ref: TriggerRef
    provider: ProviderInfo
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    tool_calls: list[AgentRunToolCallRead] = []
    decision_basis: DecisionBasis | None = None
    pending_action_ids: list[str] = []
    usage: RunUsage | None = None
    result: RunResult | None = None
    failure: RunFailure | None = None


class ToolSummary(BaseModel):
    name: str
    version: str
    title: str


class DisplayParameter(BaseModel):
    label: str
    value: str


class ActionDisplay(BaseModel):
    summary: str
    parameters: list[DisplayParameter] = []
    impact: str
    risk_note: str | None = None


class SafeError(BaseModel):
    code: str
    message: str


class ActionResult(BaseModel):
    summary: str
    resource_type: str | None = None
    resource_id: str | None = None


class PendingActionRead(ORMModel):
    id: uuid.UUID
    version: int
    status: PendingStatus
    required_level: int
    tool: ToolSummary
    display: ActionDisplay
    basis: DecisionBasis
    expires_at: datetime
    retryable: bool
    safe_error: SafeError | None = None
    result: ActionResult | None = None
    created_at: datetime
    updated_at: datetime


def pending_action_read(row: PendingActionORM) -> PendingActionRead:
    """Project a ``PendingAction`` ORM row into the frozen read shape.

    Kept as a function (not a from_attributes hop) because the frozen shape
    restructures columns: ``tool_*`` -> ``tool`` triple, JSONB ``display`` /
    ``basis`` / ``last_error`` / ``result`` -> validated nested models, and
    ``retryable`` is derived from the state machine rather than stored.
    """

    return PendingActionRead(
        id=row.id,
        version=row.version,
        status=cast(PendingStatus, row.status),
        required_level=row.required_level,
        tool=ToolSummary(name=row.tool_name, version=row.tool_version, title=row.tool_title),
        display=ActionDisplay.model_validate(row.display),
        basis=DecisionBasis.model_validate(row.basis),
        expires_at=row.expires_at,
        retryable=row.status == "FAILED_RETRYABLE",
        safe_error=SafeError.model_validate(row.last_error) if row.last_error else None,
        result=ActionResult.model_validate(row.result) if row.result else None,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
