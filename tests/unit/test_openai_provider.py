"""OpenAI provider adapter unit tests.

The ``store=False`` test is the frozen D-033 §7 constraint: the Responses
request builder hardcodes it and no call site can turn it back on.
"""

from __future__ import annotations

import json

import httpx
import pytest

from backend.adapters.model_provider import (
    EmbeddingResult,
    ModelProviderUnavailable,
    OpenAIProvider,
)


class _RecordingTransport(httpx.MockTransport):
    """MockTransport 没有可记录面；子类声明显式属性让 pyright 可见。"""

    calls: list[dict]

    def __init__(self, handle, recorded: list[dict]) -> None:
        super().__init__(handle)
        self.calls = recorded


def _handler(responses: list[httpx.Response]) -> _RecordingTransport:
    calls: list[dict] = []

    def _transport(request: httpx.Request) -> httpx.Response:
        calls.append(
            {
                "url": str(request.url),
                "body": json.loads(request.content),
                "auth": request.headers.get("Authorization"),
            }
        )
        return responses[len(calls) - 1]

    return _RecordingTransport(_transport, calls)


def _embedding_response(vectors: list[list[float]]) -> httpx.Response:
    data = [
        {"index": len(vectors) - 1 - i, "embedding": vector} for i, vector in enumerate(vectors)
    ]  # deliberately out of order: provider must sort by index
    return httpx.Response(
        200, json={"object": "list", "model": "text-embedding-3-small", "data": data}
    )


def test_responses_request_always_omits_store() -> None:
    provider = OpenAIProvider(api_key="k")
    body = provider.build_responses_request("gpt-4o-mini", "question", "instructions")
    assert body["store"] is False
    # And there is no way to flip it: the signature exposes no store knob.
    import inspect

    params = inspect.signature(provider.build_responses_request).parameters
    assert "store" not in params


async def test_embed_texts_requires_api_key() -> None:
    provider = OpenAIProvider(
        api_key="", transport=httpx.MockTransport(lambda r: httpx.Response(500))
    )
    with pytest.raises(ModelProviderUnavailable):
        await provider.embed_texts(["text"])


async def test_embed_texts_empty_is_noop() -> None:
    provider = OpenAIProvider(
        api_key="k", transport=httpx.MockTransport(lambda r: httpx.Response(500))
    )
    assert await provider.embed_texts([]) == EmbeddingResult(
        vectors=[], model=provider._embedding_model
    )


async def test_embed_texts_batches_and_sorts_by_index() -> None:
    dim = 1536  # the adapter validates the frozen column width
    vectors = [[float(i)] * dim for i in range(4)]
    # One response per batch; indexes are batch-local, deliberately shuffled.
    transport = _handler(
        [
            _embedding_response([vectors[1], vectors[0]]),
            _embedding_response([vectors[3], vectors[2]]),
        ]
    )
    provider = OpenAIProvider(api_key="k", transport=transport)
    provider._batch_size = 2
    provider._max_retries = 0
    result = await provider.embed_texts(["a", "b", "c", "d"])
    assert result.vectors == vectors
    assert len(transport.calls) == 2  # 4 texts / batch size 2
    assert all(call["url"].endswith("/embeddings") for call in transport.calls)
    assert all(call["auth"] == "Bearer k" for call in transport.calls)
    assert transport.calls[0]["body"]["input"] == ["a", "b"]


async def test_embed_texts_retries_on_429(monkeypatch) -> None:
    import backend.adapters.model_provider.openai_provider as mod

    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(mod.asyncio, "sleep", _no_sleep)
    vectors = [[0.5] * 1536]
    transport = _handler([httpx.Response(429), _embedding_response(vectors)])
    provider = OpenAIProvider(api_key="k", transport=transport)
    result = await provider.embed_texts(["a"])
    assert result.vectors == vectors
    assert len(transport.calls) == 2


async def test_embed_texts_fails_on_bad_request(monkeypatch) -> None:
    import backend.adapters.model_provider.openai_provider as mod

    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(mod.asyncio, "sleep", _no_sleep)
    transport = _handler([httpx.Response(400, text="bad model")])
    provider = OpenAIProvider(api_key="k", transport=transport)
    with pytest.raises(mod.ModelProviderError):
        await provider.embed_texts(["a"])
    assert len(transport.calls) == 1  # 4xx (non-429) does not retry


async def test_embed_texts_rejects_wrong_dimension(monkeypatch) -> None:
    import backend.adapters.model_provider.openai_provider as mod

    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(mod.asyncio, "sleep", _no_sleep)
    transport = _handler([_embedding_response([[0.1] * 4])])  # 4 dims, want 1536
    provider = OpenAIProvider(api_key="k", transport=transport)
    provider._max_retries = 0
    with pytest.raises(mod.ModelProviderError, match="dims"):
        await provider.embed_texts(["a"])
