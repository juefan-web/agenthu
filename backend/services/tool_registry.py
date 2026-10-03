"""Server-side, versioned tool registry (D-034 §4).

The registry is code configuration: neither the model nor the client can
register tools. Every ``ToolDefinition`` resolves its required level from
``ACTION_POLICY`` and is cross-validated at import time — a registry entry
whose declared level disagrees with policy fails the process at startup, not
at the first sensitive call.

The runner funnels EVERY model-initiated call through one interception point
in a fixed order (contract §6.2): ``input_schema`` → permission →
``display_builder``. Tool implementations never write business tables
directly on the model's behalf without passing through that point.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel

from backend.services.permissions import ACTION_POLICY, required_level_for

IdempotencyMode = Literal["none", "required", "natural"]
FailureMode = Literal["fail_closed", "create_pending", "deterministic_fallback"]

RUNNER_VERSION = "a2.1"
TOOL_REGISTRY_VERSION = "m4-a2.1"
# Version of the recursive-allowlist redaction applied to tool arguments
# before they touch audit surfaces (services.audit.redact_allowlist).
INPUT_REDACTION_VERSION = "rec-v2"


class ToolError(Exception):
    """Tool execution failure with a safe, classifiable error code."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message
        self.retryable = retryable


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    version: str
    description: str
    # Strict Pydantic shape: unknown fields are rejected before anything else.
    input_model: type[BaseModel]
    side_effect: bool
    idempotency: IdempotencyMode = "none"
    idempotency_key: Callable[[Any], str] | None = None
    timeout_seconds: int = 30
    max_attempts: int = 3
    backoff_seconds: float = 2.0
    failure_mode: FailureMode = "fail_closed"
    # Arg keys allowed to appear in audit details (recursive allowlist input).
    audit_fields: frozenset[str] = field(default_factory=frozenset)
    # {summary, parameters: [{label, value}], impact, risk_note?} — server-
    # built safe display; model prose never reaches the UI raw.
    display_builder: Callable[[Any], dict[str, Any]] | None = None
    # Data categories this tool reads AND could send to a provider; empty
    # means local-only. Gates the consent check in context assembly.
    data_scope: frozenset[str] = field(default_factory=frozenset)
    # Grant-scope validator for Level 3 tools (§5.3): strict schema, no
    # wildcards, unknown fields deny.
    scope_validator: Callable[[dict | None], bool] | None = None
    # Value-level grant-scope match for Level 3 tools (§5.3, coordinator
    # ruling 2026-10-04): the grant must cover THIS call's argument values
    # (e.g. ``args.category in grant.scope["categories"]``), not merely have
    # a well-formed scope. A Level-3 grant scoped to "deadline" pushes must
    # not auto-execute a "replan" push — that becomes a PENDING card.
    # ``validate_registry`` requires this for every Level-3 tool.
    scope_matcher: Callable[[dict | None, Any], bool] | None = None
    execute: Callable[..., Awaitable[dict[str, Any]]] | None = None

    @property
    def required_level(self) -> int:
        entry = ACTION_POLICY.get(self.name)
        if entry is None:
            raise KeyError(f"Tool {self.name!r} has no ACTION_POLICY row")
        return entry[0]

    def tool_schemas(self) -> dict[str, Any]:
        """Minimal JSON-schema description handed to providers (§6.2)."""

        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_model.model_json_schema(),
        }


_REGISTRY: dict[str, ToolDefinition] = {}


def register_tool(tool: ToolDefinition) -> ToolDefinition:
    if tool.name in _REGISTRY:
        raise ValueError(f"Tool {tool.name!r} registered twice")
    if tool.execute is None:
        raise ValueError(f"Tool {tool.name!r} has no implementation")
    if tool.failure_mode == "create_pending" and tool.display_builder is None:
        raise ValueError(f"Level-2 tool {tool.name!r} needs a display_builder")
    if tool.idempotency == "required" and tool.idempotency_key is None:
        raise ValueError(f"Tool {tool.name!r} requires an idempotency key builder")
    _REGISTRY[tool.name] = tool
    return tool


def get_tool(name: str) -> ToolDefinition | None:
    return _REGISTRY.get(name)


def all_tools() -> dict[str, ToolDefinition]:
    return dict(_REGISTRY)


def validate_registry() -> list[str]:
    """Cross-check registry vs ACTION_POLICY. Returns the sorted tool names
    on success; raises on any disagreement (called at startup + in tests)."""

    problems: list[str] = []
    for name, tool in _REGISTRY.items():
        if name not in ACTION_POLICY:
            problems.append(f"{name}: no ACTION_POLICY row")
            continue
        # Every registry entry re-derives its level from policy via the
        # required_level property; a missing row already raised above.
        if tool.side_effect and tool.idempotency == "none":
            problems.append(f"{name}: side-effect tools must declare an idempotency mode")
        # §5.3 fail-closed: auto-execution must be shape- AND value-scoped;
        # a Level-3 tool without both gates cannot register.
        if tool.required_level == 3 and (
            tool.scope_validator is None or tool.scope_matcher is None
        ):
            problems.append(f"{name}: level-3 tools must declare scope_validator and scope_matcher")
        if tool.required_level == 2:
            # Level 2 only ever creates pending actions: the model's proposal
            # lands in the confirmation queue, so the failure mode is fixed
            # and every row needs a stable idempotency key.
            if tool.failure_mode != "create_pending":
                problems.append(f"{name}: level-2 tools must fail into create_pending")
            if tool.idempotency != "required":
                problems.append(f"{name}: level-2 tools must require idempotency keys")
    # Agent-executable policy rows that lack a registry entry are listed but
    # tolerated (registered incrementally); the reverse direction is fatal.
    if problems:
        raise ValueError("Tool registry validation failed: " + "; ".join(problems))
    return sorted(_REGISTRY)


def strict_scope_validator(
    allowed_keys: frozenset[str],
    *,
    list_keys: frozenset[str] = frozenset(),
    reject_wildcards: bool = True,
) -> Callable[[dict | None], bool]:
    """Build a §5.3 scope validator: unknown fields, empty scope and ``*``
    wildcards all deny. ``list_keys`` must be non-empty lists of safe tokens
    when present."""

    def validate(scope: dict | None) -> bool:
        if not isinstance(scope, dict) or not scope:
            return False
        for key in scope:
            if key not in allowed_keys:
                return False
        for key in list_keys:
            if key not in scope:
                return False
            values = scope[key]
            if not isinstance(values, list) or not values:
                return False
            if any(not isinstance(v, str) or (reject_wildcards and v == "*") for v in values):
                return False
        if reject_wildcards:
            for value in scope.values():
                if value == "*":
                    return False
        return True

    return validate


__all__ = [
    "RUNNER_VERSION",
    "TOOL_REGISTRY_VERSION",
    "ToolDefinition",
    "ToolError",
    "all_tools",
    "get_tool",
    "register_tool",
    "required_level_for",
    "strict_scope_validator",
    "validate_registry",
]
