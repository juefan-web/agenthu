"""Provider-agnostic model interface.

D-033 §3/§7 constraints that live here for every implementation:

- Sending text to the provider is a *privileged* action gated by per-course
  consent upstream; adapters never decide policy, they only execute calls
  they are given (and must fail closed when unconfigured).
- ``build_responses_request`` pins ``store=False`` for Responses API calls —
  provider-side application state would otherwise add a second ≤30-day
  retention surface beyond the unavoidable abuse-monitoring logs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class EmbeddingResult:
    vectors: list[list[float]]
    model: str


class ModelProviderError(Exception):
    """A model call failed after exhausting retries (4xx / repeated 5xx)."""


class ModelProviderUnavailable(ModelProviderError):
    """The provider is not configured (e.g. missing API key).

    Distinct from transient failures: retrying cannot help, and callers must
    treat it as fail-closed, never as "already embedded".
    """


@dataclass(frozen=True)
class ProviderCapabilities:
    """Capability negotiation (D-034 §6.2): the runner asks, never parses
    natural language to discover what a provider can do."""

    text_generation: bool = True
    tool_calls: bool = False
    structured_output: bool = False


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments_json: str


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    status: str  # "succeeded" | "failed"
    safe_result_json: str


@dataclass(frozen=True)
class TurnContext:
    """Replay context for multi-turn tool loops (audit beta, ruling 2a).

    ``store=False`` means the server keeps no conversation state, so the
    provider needs the original prompt, instructions and tool schemas to
    rebuild each follow-up request. ``history`` accumulates the wire items
    of every completed round so Turn N replays rounds 1..N-1 in full
    (ruling-2 revision). This payload is in-process only — it rides the
    ModelTurn between calls and must never be logged or attached to
    traces/spans (AllowlistSpanExporter discipline, #78).
    """

    input_text: str
    instructions: str | None = None
    tool_schemas: list[dict[str, Any]] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ModelTurn:
    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    provider_request_id: str | None = None
    finish_reason: str | None = None
    context: TurnContext | None = None


class ModelProvider(Protocol):
    name: str

    async def embed_texts(self, texts: list[str]) -> EmbeddingResult: ...

    async def generate(self, input_text: str, instructions: str | None = None) -> str: ...

    def build_responses_request(
        self, model: str, input_text: str, instructions: str | None = None
    ) -> dict[str, object]: ...

    def capabilities(self) -> ProviderCapabilities: ...

    async def generate_with_tools(
        self,
        input_text: str,
        instructions: str | None,
        tool_schemas: list[dict[str, Any]],
    ) -> ModelTurn: ...

    async def continue_with_tool_results(
        self, turn: ModelTurn, results: list[ToolResult]
    ) -> ModelTurn: ...
