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

from dataclasses import dataclass
from typing import Protocol


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


class ModelProvider(Protocol):
    name: str

    async def embed_texts(self, texts: list[str]) -> EmbeddingResult: ...

    def build_responses_request(
        self, model: str, input_text: str, instructions: str | None = None
    ) -> dict[str, object]: ...
