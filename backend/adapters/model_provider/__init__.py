"""Model provider adapters (TECH_STACK: all model calls go through adapters).

Business logic must never bind to OpenAI or any specific vendor API; it sees
the protocol in ``base``. ``get_model_provider`` is the single construction
point, driven by settings, so tests and future vendor swaps have one seam.
"""

from backend.adapters.model_provider.base import (
    EmbeddingResult,
    ModelProvider,
    ModelProviderError,
    ModelProviderUnavailable,
    TurnContext,
)
from backend.adapters.model_provider.openai_provider import (
    OpenAIProvider,
    get_model_provider,
    reset_model_provider,
)

__all__ = [
    "EmbeddingResult",
    "ModelProvider",
    "ModelProviderError",
    "ModelProviderUnavailable",
    "OpenAIProvider",
    "TurnContext",
    "get_model_provider",
    "reset_model_provider",
]
