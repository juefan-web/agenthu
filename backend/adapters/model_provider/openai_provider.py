"""OpenAI provider adapter (first implementation, D-033 §7 first-check).

- Embeddings: ``POST /embeddings`` with ``text-embedding-3-small`` (1536
  dims, matching the frozen column width). The endpoint has no ``store``
  parameter — it is ZDR-eligible at the account/endpoint level (verified
  2026-10-02, PR #36) — so nothing to disable per request.
- Responses: ``build_responses_request`` constructs the request body used by
  the (later) grounded-answer slice with ``store=False`` hardcoded. The full
  generate() arrives with that slice; the constraint and its regression test
  land NOW so no future call site can forget it.

Fail-closed: no API key → ``ModelProviderUnavailable``. Timeouts and
retryable statuses back off up to ``embedding_max_retries``; 4xx (except
429) fail immediately — retrying a bad request only burns quota.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from backend.adapters.model_provider.base import (
    EmbeddingResult,
    ModelProviderError,
    ModelProviderUnavailable,
)
from backend.config import get_settings

logger = logging.getLogger(__name__)

EMBEDDING_DIMENSIONS = 1536


class OpenAIProvider:
    name = "openai"

    def __init__(
        self,
        api_key: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        settings = get_settings()
        self._api_key = api_key if api_key is not None else settings.openai_api_key
        self._base_url = settings.openai_base_url.rstrip("/")
        self._embedding_model = settings.embedding_model
        self._batch_size = settings.embedding_batch_size
        self._timeout = settings.embedding_timeout_seconds
        self._max_retries = settings.embedding_max_retries
        # Test seam only: inject a MockTransport instead of hitting the wire.
        self._transport = transport

    def build_responses_request(
        self, model: str, input_text: str, instructions: str | None = None
    ) -> dict[str, object]:
        """Responses API body. ``store=False`` is a frozen D-033 §7 constraint.

        Do not make it a parameter — the whole point is that no call site can
        turn application-state retention back on by accident.
        """

        body: dict[str, object] = {"model": model, "input": input_text, "store": False}
        if instructions is not None:
            body["instructions"] = instructions
        return body

    async def embed_texts(self, texts: list[str]) -> EmbeddingResult:
        if not texts:
            return EmbeddingResult(vectors=[], model=self._embedding_model)
        if not self._api_key:
            raise ModelProviderUnavailable(
                "OpenAI API key is not configured; embedding requires provider consent"
                " + configuration (fail-closed, D-033)"
            )

        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            batch = texts[start : start + self._batch_size]
            vectors.extend(await self._embed_batch(batch))
        return EmbeddingResult(vectors=vectors, model=self._embedding_model)

    async def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        url = f"{self._base_url}/embeddings"
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            if attempt:
                await asyncio.sleep(min(2**attempt, 8))
            try:
                async with httpx.AsyncClient(
                    timeout=self._timeout, transport=self._transport
                ) as client:
                    response = await client.post(
                        url,
                        headers={"Authorization": f"Bearer {self._api_key}"},
                        json={"model": self._embedding_model, "input": batch},
                    )
                if response.status_code == 200:
                    payload = response.json()
                    rows = sorted(payload["data"], key=lambda r: r["index"])
                    vectors = [row["embedding"] for row in rows]
                    for vector in vectors:
                        if len(vector) != EMBEDDING_DIMENSIONS:
                            raise ModelProviderError(
                                f"Provider returned {len(vector)} dims, expected"
                                f" {EMBEDDING_DIMENSIONS}"
                            )
                    return vectors
                if response.status_code == 429 or response.status_code >= 500:
                    last_error = ModelProviderError(
                        f"Embedding call failed: HTTP {response.status_code}"
                    )
                    continue
                raise ModelProviderError(
                    f"Embedding call rejected: HTTP {response.status_code} {response.text[:200]}"
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                continue
        raise ModelProviderError(
            f"Embedding failed after {self._max_retries + 1} attempts"
        ) from last_error


_provider: OpenAIProvider | None = None


def get_model_provider() -> OpenAIProvider:
    """Single construction point (settings-driven; tests monkeypatch this)."""

    global _provider
    if _provider is None:
        _provider = OpenAIProvider()
    return _provider


def reset_model_provider() -> None:
    global _provider
    _provider = None
