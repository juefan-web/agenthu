"""P0-5 slice 1: the OTel skeleton's privacy and liveness contracts.

These pin the frozen rulings mechanically: the allowlist is the only channel
(non-allowlisted attributes never leave the process, events and status
descriptions are stripped), exporter outage never blocks a request, telemetry
stays disabled by default, and the five-layer chain correlates within one
request via parent/child span contexts. Assertions flush the batch processor
first — production batching is asynchronous by design.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace.status import StatusCode

from backend.core import telemetry

SECRET_QUERY = "supersecretvalue@example.com"
SECRET_HEADER = "topsecret-token"


@contextmanager
def _local_provider_server() -> Iterator[int]:
    """A loopback HTTP stand-in for the model provider.

    The official httpx instrumentation wraps ``AsyncHTTPTransport`` (the
    transport layer), so a MockTransport would never emit a client span —
    tests exercise the provider face against a real loopback server instead.
    """

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *args: object) -> None:
            return None

    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def mem_exporter() -> InMemorySpanExporter:
    return InMemorySpanExporter()


@pytest.fixture
def otel_app(
    mem_exporter: InMemorySpanExporter,
) -> Iterator[tuple[FastAPI, TracerProvider]]:
    telemetry.shutdown_telemetry()
    provider = telemetry.configure_telemetry("test-api", exporter=mem_exporter, force=True)
    assert provider is not None
    telemetry.instrument_outbound_clients(provider)
    app = FastAPI()

    @app.get("/items/{item_id}")
    async def read_item(item_id: str, q: str | None = None) -> dict[str, str]:
        with telemetry.stage_span(
            "operation", "test.operation", **{"correlation.id": "op-123", "usage.calls": 2}
        ):
            pass
        # Provider face: an instrumented httpx client span joins the same
        # trace as the server span and the operation span (loopback server —
        # MockTransport bypasses the wrapped transport class).
        with _local_provider_server() as port:
            async with httpx.AsyncClient() as client:
                await client.get(f"http://127.0.0.1:{port}/v1/embeddings")
        return {"item_id": item_id}

    telemetry.instrument_http_server(app, provider)
    yield app, provider
    telemetry.shutdown_telemetry()


def _attrs(span: ReadableSpan) -> dict[str, object]:
    return dict(span.attributes or {})


def test_allowlist_strips_query_strings_headers_and_unlisted_keys(
    otel_app: tuple[FastAPI, TracerProvider], mem_exporter: InMemorySpanExporter
) -> None:
    app, provider = otel_app
    client = TestClient(app)
    response = client.get(
        "/items/abc",
        params={"q": SECRET_QUERY},
        headers={"x-api-key": SECRET_HEADER},
    )
    assert response.status_code == 200
    provider.force_flush()

    spans = mem_exporter.get_finished_spans()
    assert spans, "server span must be exported"
    for span in spans:
        for key, value in _attrs(span).items():
            assert key in telemetry.SPAN_ATTRIBUTE_ALLOWLIST, key
            rendered = repr(value)
            assert SECRET_QUERY not in rendered
            assert SECRET_HEADER not in rendered
        # No URL-shaped keys survive: paths and query strings are banned.
        assert not any(
            key for key in _attrs(span) if "url" in key or key in {"http.target", "full_url"}
        )
        # Automatic exception capture is off: no events at all.
        assert span.events == ()


def test_chain_correlates_within_one_request(
    otel_app: tuple[FastAPI, TracerProvider], mem_exporter: InMemorySpanExporter
) -> None:
    app, provider = otel_app
    client = TestClient(app)
    assert client.get("/items/abc").status_code == 200
    provider.force_flush()

    spans = mem_exporter.get_finished_spans()
    server = next(s for s in spans if _attrs(s).get("http.route") == "/items/{item_id}")
    operation = next(s for s in spans if _attrs(s).get("stage") == "operation")
    # The client span carries http.method but no route (it is not a server
    # face); the framework's internal send/receive spans have neither.
    provider_call = next(
        s for s in spans if "http.method" in _attrs(s) and "http.route" not in _attrs(s)
    )

    # Same trace, direct parent/child: server -> operation; provider call is
    # under the server span's trace too (the request's tracecontext).
    server_ctx = server.get_span_context()
    operation_ctx = operation.get_span_context()
    provider_ctx = provider_call.get_span_context()
    parent = operation.parent
    assert server_ctx is not None
    assert operation_ctx is not None
    assert provider_ctx is not None
    assert parent is not None
    assert operation_ctx.trace_id == server_ctx.trace_id
    assert parent.span_id == server_ctx.span_id
    assert provider_ctx.trace_id == server_ctx.trace_id
    # The server span carries the request correlation id.
    assert _attrs(server).get("correlation.id")


def test_stage_span_drops_non_allowlisted_fields(
    otel_app: tuple[FastAPI, TracerProvider],
    mem_exporter: InMemorySpanExporter,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _app, provider = otel_app
    with (
        caplog.at_level(logging.WARNING, logger="backend.core.telemetry"),
        telemetry.stage_span(
            "run",
            "agent.run",
            **{
                "correlation.id": "run-1",
                "user_id": "11111111-1111-1111-1111-111111111111",
                "prompt": "write my homework",
            },
        ),
    ):
        pass
    provider.force_flush()
    spans = [s for s in mem_exporter.get_finished_spans() if _attrs(s).get("stage") == "run"]
    assert len(spans) == 1
    attrs = _attrs(spans[0])
    assert attrs.get("correlation.id") == "run-1"
    assert "user_id" not in attrs
    assert "prompt" not in attrs
    assert any("user_id" in message for message in caplog.messages)


def test_stage_span_records_bounded_error_code_and_reraises(
    otel_app: tuple[FastAPI, TracerProvider], mem_exporter: InMemorySpanExporter
) -> None:
    _app, provider = otel_app

    class DomainFailure(RuntimeError):
        pass

    with (
        pytest.raises(DomainFailure),
        telemetry.stage_span("run", "agent.run", **{"correlation.id": "run-2"}),
    ):
        raise DomainFailure("model content must not reach the span")
    provider.force_flush()
    span = next(s for s in mem_exporter.get_finished_spans() if _attrs(s).get("stage") == "run")
    attrs = _attrs(span)
    assert attrs.get("error.code") == "DomainFailure"
    # The exception message (potential user content) is not an attribute...
    assert "model content" not in str(attrs)
    # ...and the status description is blanked by the exporter.
    assert span.status.status_code == StatusCode.ERROR
    assert not span.status.description
    assert span.events == ()


def test_traced_job_opens_worker_span(
    mem_exporter: InMemorySpanExporter,
) -> None:
    telemetry.shutdown_telemetry()
    provider = telemetry.configure_telemetry("test-worker", exporter=mem_exporter, force=True)
    assert provider is not None

    @telemetry.traced_job
    async def sample_task(ctx: dict[str, object] | None, x: int) -> dict[str, int]:
        return {"x": x}

    result = asyncio.run(sample_task({"job_id": "job-1", "job_try": 2}, 5))
    assert result == {"x": 5}
    provider.force_flush()
    span = next(s for s in mem_exporter.get_finished_spans() if s.name == "worker.sample_task")
    attrs = _attrs(span)
    assert attrs.get("stage") == "worker"
    assert attrs.get("correlation.id") == "job-1"
    assert attrs.get("job.try") == 2
    telemetry.shutdown_telemetry()


def test_traced_job_tolerates_missing_context(mem_exporter: InMemorySpanExporter) -> None:
    telemetry.shutdown_telemetry()
    provider = telemetry.configure_telemetry("test-worker", exporter=mem_exporter, force=True)
    assert provider is not None

    @telemetry.traced_job
    async def bare_task(ctx: dict[str, object] | None) -> str:
        return "ok"

    assert asyncio.run(bare_task(None)) == "ok"
    provider.force_flush()
    span = next(s for s in mem_exporter.get_finished_spans() if s.name == "worker.bare_task")
    assert _attrs(span).get("stage") == "worker"
    telemetry.shutdown_telemetry()


class _RaisingExporter(SpanExporter):
    """Simulates a dead collector: every export raises."""

    def __init__(self) -> None:
        self.attempts = 0

    def export(self, spans) -> SpanExportResult:  # type: ignore[no-untyped-def]
        self.attempts += 1
        raise RuntimeError("collector down")

    def shutdown(self) -> None:
        return None


def test_exporter_outage_does_not_block_requests() -> None:
    telemetry.shutdown_telemetry()
    raising = _RaisingExporter()
    provider = telemetry.configure_telemetry("test-api", exporter=raising, force=True)
    assert provider is not None
    app = FastAPI()

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    telemetry.instrument_http_server(app, provider)
    client = TestClient(app)
    for _ in range(3):
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
    # Spans were produced and the exporter was invoked (and failed) without
    # any of it surfacing on the request path.
    provider.force_flush()
    assert raising.attempts >= 1
    telemetry.shutdown_telemetry()


def test_disabled_by_default_is_a_no_op(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.config import clear_settings_cache

    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    clear_settings_cache()
    telemetry.shutdown_telemetry()
    assert telemetry.configure_telemetry("test-api", force=True) is None
    with telemetry.stage_span("run", "agent.run", **{"correlation.id": "c1"}) as span:
        assert not span.is_recording()
    telemetry.shutdown_telemetry()
