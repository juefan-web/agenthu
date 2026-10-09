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
from dataclasses import replace

import httpx

from backend.adapters.model_provider.base import (
    EmbeddingResult,
    ModelProviderError,
    ModelProviderUnavailable,
    ModelTurn,
    ProviderCapabilities,
    ToolCall,
    ToolResult,
    TurnContext,
)
from backend.config import get_settings

logger = logging.getLogger(__name__)

EMBEDDING_DIMENSIONS = 1536


def _aggregate_output_text(payload: dict) -> str:
    """Concatenate an item's output_text parts (Responses API wire format).

    The convenience ``output_text`` field exists on SDK objects, not on the
    raw HTTP payload; the structure is output[].content[] with type
    ``output_text`` entries.
    """

    parts: list[str] = []
    for item in payload.get("output", []):
        for block in item.get("content", []):
            if block.get("type") == "output_text":
                parts.append(block.get("text", ""))
    return "".join(parts)


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
        self._generation_timeout = settings.responses_timeout_seconds
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

    async def generate(self, input_text: str, instructions: str | None = None) -> str:
        """One Responses API call; returns the aggregated output text.

        Fails closed like embed_texts: no key -> unavailable, transport/5xx
        exhausted -> error. Callers surface failures as errors (never a
        smooth ungrounded answer — TASKS/m3-grounded-answers.md §5).
        """

        if not self._api_key:
            raise ModelProviderUnavailable(
                "OpenAI API key is not configured; generation requires provider"
                " consent + configuration (fail-closed, D-033)"
            )
        body = self.build_responses_request(
            get_settings().responses_model, input_text, instructions
        )
        url = f"{self._base_url}/responses"
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            if attempt:
                await asyncio.sleep(min(2**attempt, 8))
            try:
                async with httpx.AsyncClient(
                    timeout=self._generation_timeout, transport=self._transport
                ) as client:
                    response = await client.post(
                        url,
                        headers={"Authorization": f"Bearer {self._api_key}"},
                        json=body,
                    )
                if response.status_code == 200:
                    return _aggregate_output_text(response.json())
                if response.status_code == 429 or response.status_code >= 500:
                    last_error = ModelProviderError(
                        f"Responses call failed: HTTP {response.status_code}"
                    )
                    continue
                raise ModelProviderError(
                    f"Responses call rejected: HTTP {response.status_code} {response.text[:200]}"
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                continue
        raise ModelProviderError(
            f"Generation failed after {self._max_retries + 1} attempts"
        ) from last_error

    @property
    def model_name(self) -> str:
        return get_settings().responses_model

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(text_generation=True, tool_calls=True)

    def _tool_wire(self, tool_schemas: list[dict[str, object]]) -> list[dict[str, object]]:
        return [
            {
                "type": "function",
                "name": schema["name"],
                "description": schema.get("description", ""),
                "parameters": schema.get("input_schema", {"type": "object"}),
            }
            for schema in tool_schemas
        ]

    @staticmethod
    def _parse_turn(payload: dict) -> ModelTurn:
        text_parts: list[str] = []
        calls: list[ToolCall] = []
        for item in payload.get("output", []):
            if item.get("type") == "function_call":
                calls.append(
                    ToolCall(
                        call_id=item.get("call_id", ""),
                        name=item.get("name", ""),
                        arguments_json=item.get("arguments", "{}"),
                    )
                )
                continue
            for block in item.get("content", []):
                if block.get("type") == "output_text":
                    text_parts.append(block.get("text", ""))
        usage = payload.get("usage") or {}
        return ModelTurn(
            text="".join(text_parts) or None,
            tool_calls=calls,
            usage={
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
            },
            provider_request_id=payload.get("id"),
            finish_reason=payload.get("status"),
        )

    async def _post_responses(self, body: dict[str, object]) -> dict:
        if not self._api_key:
            raise ModelProviderUnavailable(
                "OpenAI API key is not configured; tool calls require provider"
                " consent + configuration (fail-closed, D-033)"
            )
        url = f"{self._base_url}/responses"
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            if attempt:
                await asyncio.sleep(min(2**attempt, 8))
            try:
                async with httpx.AsyncClient(
                    timeout=self._generation_timeout, transport=self._transport
                ) as client:
                    response = await client.post(
                        url,
                        headers={"Authorization": f"Bearer {self._api_key}"},
                        json=body,
                    )
                if response.status_code == 200:
                    return response.json()
                if response.status_code == 429 or response.status_code >= 500:
                    last_error = ModelProviderError(
                        f"Responses call failed: HTTP {response.status_code}"
                    )
                    continue
                raise ModelProviderError(
                    f"Responses call rejected: HTTP {response.status_code} {response.text[:200]}"
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                continue
        raise ModelProviderError(
            f"Tool-call turn failed after {self._max_retries + 1} attempts"
        ) from last_error

    async def generate_with_tools(
        self,
        input_text: str,
        instructions: str | None,
        tool_schemas: list[dict[str, object]],
    ) -> ModelTurn:
        """First tool-capable turn. ``store=False`` stays hardcoded (D-033).

        The returned turn carries the replay context (ruling 2a) so
        ``continue_with_tool_results`` can rebuild the full request.
        """

        body = self.build_responses_request(
            get_settings().responses_model, input_text, instructions
        )
        body["tools"] = self._tool_wire(tool_schemas)
        turn = self._parse_turn(await self._post_responses(body))
        return replace(
            turn,
            context=TurnContext(
                input_text=input_text,
                instructions=instructions,
                tool_schemas=list(tool_schemas),
            ),
        )

    @staticmethod
    def _call_item(call: ToolCall) -> dict[str, object]:
        return {
            "type": "function_call",
            "call_id": call.call_id,
            "name": call.name,
            "arguments": call.arguments_json,
        }

    @staticmethod
    def _output_item(result: ToolResult) -> dict[str, object]:
        return {
            "type": "function_call_output",
            "call_id": result.call_id,
            "output": result.safe_result_json,
        }

    async def continue_with_tool_results(
        self, turn: ModelTurn, results: list[ToolResult]
    ) -> ModelTurn:
        """Next turn feeding safe tool results back (§6.2: only schema-safe
        results ever travel back to the provider).

        Under ``store=False`` the server holds no conversation state, so the
        original prompt (as the first input item), the instructions and the
        tool schemas are replayed from the turn's in-process context —
        without them Turn 2+ would be a beheaded request that can never
        issue another tool call (audit beta). Per the ruling-2 revision the
        replay accumulates across rounds: Turn N carries the prompt plus
        every function_call / function_call_output item of rounds 1..N-1.
        The context rides the ModelTurn only and never reaches logs or
        spans.
        """

        context = turn.context
        round_items: list[dict[str, object]] = [
            self._call_item(call) for call in turn.tool_calls
        ] + [self._output_item(result) for result in results]
        input_items: list[dict[str, object]] = []
        if context is not None:
            if context.input_text:
                input_items.append(
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": context.input_text}],
                    }
                )
            input_items.extend(context.history)
        input_items.extend(round_items)
        body: dict[str, object] = {
            "model": get_settings().responses_model,
            "store": False,
            "input": input_items,
        }
        if context is not None:
            if context.instructions is not None:
                body["instructions"] = context.instructions
            if context.tool_schemas:
                body["tools"] = self._tool_wire(context.tool_schemas)
        next_turn = self._parse_turn(await self._post_responses(body))
        if context is None:
            return next_turn
        # The original turn's context stays untouched (frozen); the next
        # turn carries the extended history for the following replay.
        extended = replace(context, history=[*context.history, *round_items])
        return replace(next_turn, context=extended)

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
