"""OpenTelemetry skeleton for the API and worker (P0-5 slice 1).

Shaped by the four frozen rulings (coordinator, 2026-10-06):

1. Standard ``opentelemetry-sdk`` plus the official instrumentation libraries,
   OTLP/HTTP as the only wire format, a Collector container in the alpha
   compose stack, automatic capture off — the allowlist below is the ONLY
   channel through which fields reach an exporter.
2. Trusted proxies are explicit opt-in configuration (see ``core/proxy.py``);
   the default ignores X-Forwarded-For everywhere.
3. The multi-process compose override is slice 3 / E7-9 territory; this module
   stays single-process-safe and CI keeps its single-process shape.
4. Rate-limit bucket accounting is a slice-2 seam; nothing here consumes it.

The enforcement point is the exporter boundary: ``AllowlistSpanExporter``
strips every span attribute whose key is not allowlisted, drops span events
(the SDK's automatic exception capture), blanks status descriptions and
rebuilds links from their span context only — link attributes never pass
through the key filter, so they are dropped wholesale — before anything is
serialized. Instrumentation libraries may therefore record whatever they
want internally — only allowlisted keys leave the process.

Allowlisted values are bounded by construction: framework route templates
(never instantiated paths), HTTP methods, status codes, counters, durations
and random per-incident correlation ids (request/job/run/operation ids — uuid4
values minted per event, not stable identity UUIDs like user_id, which stay
out of telemetry entirely).

Trace is not a fact layer (ops contract §6): no business decision may read
span or tracer state. Telemetry is disabled unless ``OTEL_ENABLED`` is set;
the OpenTelemetry API then returns no-op tracers and nothing is wired.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from functools import wraps
from typing import Any

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.botocore import BotocoreInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.propagate import set_global_textmap
from opentelemetry.propagators.composite import CompositePropagator
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
from opentelemetry.trace import Link, Status, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from backend import __version__
from backend.config import get_settings

logger = logging.getLogger(__name__)

SPAN_ATTRIBUTE_ALLOWLIST = frozenset(
    {
        # HTTP face (framework-filled; route is the template, not the path).
        "http.method",
        "http.route",
        "http.status_code",
        # Stage taxonomy and random per-incident correlation ids.
        "stage",
        "correlation.id",
        # Retry / timeout / usage counters (ints and floats only).
        "retry.count",
        "retry.max",
        "timeout.seconds",
        "usage.tokens",
        "usage.calls",
        "items.count",
        "job.try",
        # Bounded error taxonomy: exception class name or stable code, never
        # the message (messages can embed user content).
        "error.code",
        # Storage/provider client face: bounded method/service names.
        "rpc.system",
        "rpc.service",
        "rpc.method",
    }
)

_dropped_reported: set[str] = set()
_events_drop_reported = False
_link_attributes_drop_reported = False

_provider: TracerProvider | None = None
_outbound_instrumented = False


def _report_dropped(key: str, face: str) -> None:
    if key not in _dropped_reported:
        _dropped_reported.add(key)
        logger.warning(
            "Dropping non-allowlisted %s %r — the allowlist is the only channel (ops contract §6)",
            face,
            key,
        )


class AllowlistSpanExporter(SpanExporter):
    """Sanitize spans before they reach the wire.

    Everything an instrumentation library (or a future careless call site)
    records is filtered here: non-allowlisted attribute keys are dropped, span
    events are removed entirely (automatic exception capture off), status
    descriptions are blanked — they carry exception messages, which may embed
    user content — and links are rebuilt carrying only their span context:
    a link's identity is its trace/span ids, and its attributes (which never
    pass through the key filter) are dropped wholesale.
    """

    def __init__(self, inner: SpanExporter) -> None:
        self._inner = inner

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        return self._inner.export([self._sanitize(span) for span in spans])

    def _sanitize(self, span: ReadableSpan) -> ReadableSpan:
        global _events_drop_reported, _link_attributes_drop_reported
        attributes = span.attributes or {}
        kept = {k: v for k, v in attributes.items() if k in SPAN_ATTRIBUTE_ALLOWLIST}
        for key in attributes.keys() - kept.keys():
            _report_dropped(key, "span attribute")
        if span.events and not _events_drop_reported:
            _events_drop_reported = True
            logger.warning(
                "Dropping span events — SDK automatic exception capture is off (ops contract §6)"
            )
        if any(link.attributes for link in span.links) and not _link_attributes_drop_reported:
            _link_attributes_drop_reported = True
            logger.warning(
                "Dropping span link attributes — a link keeps its context, "
                "never attributes (ops contract §6)"
            )
        status = span.status
        return ReadableSpan(
            name=span.name,
            context=span.get_span_context(),
            parent=span.parent,
            resource=span.resource,
            attributes=kept,
            events=(),
            # Rebuilt, not passed through: the key filter above never sees
            # link attributes, so a link keeps only its context (its identity
            # is the trace/span ids) and drops its attributes wholesale.
            links=tuple(Link(link.context) for link in span.links),
            kind=span.kind,
            status=Status(status.status_code),
            start_time=span.start_time,
            end_time=span.end_time,
            instrumentation_scope=span.instrumentation_scope,
        )

    def shutdown(self) -> None:
        self._inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._inner.force_flush(timeout_millis)


def configure_telemetry(
    service_name: str,
    *,
    exporter: SpanExporter | None = None,
    force: bool = False,
) -> TracerProvider | None:
    """Wire the tracer pipeline; a no-op unless telemetry is enabled.

    ``exporter`` overrides the OTLP exporter (tests inject an in-memory
    exporter) and also bypasses the enabled gate for the test path. ``force``
    replaces an existing pipeline after shutting it down.
    """

    global _provider
    if _provider is not None and not force:
        return _provider
    settings = get_settings()
    if exporter is None and not settings.otel_enabled:
        return None
    if _provider is not None:
        try:
            _provider.shutdown()
        except Exception:  # pragma: no cover - shutdown is best-effort
            logger.warning("Prior telemetry pipeline shutdown failed", exc_info=True)

    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": __version__,
            "deployment.environment": settings.environment,
        }
    )
    provider = TracerProvider(
        resource=resource,
        sampler=ParentBased(TraceIdRatioBased(settings.otel_sample_ratio)),
    )
    inner = exporter
    if inner is None:
        inner = OTLPSpanExporter(
            endpoint=settings.otel_exporter_otlp_endpoint,
            timeout=settings.otel_export_timeout_seconds,
        )
    provider.add_span_processor(BatchSpanProcessor(AllowlistSpanExporter(inner)))
    # tracecontext only, deliberately without baggage: inbound baggage can
    # never smuggle fields into telemetry context (fail closed).
    set_global_textmap(CompositePropagator([TraceContextTextMapPropagator()]))
    _provider = provider
    return provider


def shutdown_telemetry() -> None:
    """Flush and tear down the pipeline (best-effort, never raises)."""

    global _provider, _outbound_instrumented
    provider, _provider = _provider, None
    if provider is not None:
        try:
            provider.shutdown()
        except Exception:  # pragma: no cover - shutdown is best-effort
            logger.warning("Telemetry shutdown failed", exc_info=True)
    if _outbound_instrumented:
        HTTPXClientInstrumentor().uninstrument()
        BotocoreInstrumentor().uninstrument()
        _outbound_instrumented = False


def instrument_http_server(app: Any, provider: TracerProvider) -> None:
    """Attach the official FastAPI server-span instrumentation.

    Header capture stays off (the capture_headers knobs default to None) —
    request headers are on the banned list, so the hook only adds the random
    correlation id.
    """

    FastAPIInstrumentor().instrument_app(
        app, tracer_provider=provider, server_request_hook=_request_id_hook
    )


def instrument_outbound_clients(provider: TracerProvider) -> None:
    """Attach the official httpx/botocore client-span instrumentation.

    Covers the provider face (httpx) and the storage face (boto3) wherever
    they are constructed in this process.
    """

    global _outbound_instrumented
    if _outbound_instrumented:
        return
    HTTPXClientInstrumentor().instrument(tracer_provider=provider)
    BotocoreInstrumentor().instrument(tracer_provider=provider)
    _outbound_instrumented = True


def _request_id_hook(span: trace.Span, scope: dict[str, Any]) -> None:
    """Attach the request's random correlation id to the server span.

    Robust to middleware ordering: if RequestContextMiddleware has not run
    yet, a fresh id is seeded into the scope headers so the middleware and
    the span share one value; if it already ran, its state is reused.
    """

    state = scope.get("state")
    if isinstance(state, dict) and state.get("request_id"):
        span.set_attribute("correlation.id", str(state["request_id"]))
        return
    headers = list(scope.get("headers") or [])
    for key, value in headers:
        if key == b"x-request-id":
            span.set_attribute("correlation.id", value.decode("latin-1"))
            return
    request_id = uuid.uuid4().hex
    headers.append((b"x-request-id", request_id.encode("latin-1")))
    scope["headers"] = headers
    span.set_attribute("correlation.id", request_id)


def _tracer() -> trace.Tracer:
    if _provider is not None:
        return _provider.get_tracer("agenthu.core")
    return trace.get_tracer("agenthu.core")


@contextmanager
def stage_span(stage: str, name: str, **fields: Any) -> Iterator[trace.Span]:
    """Open a span carrying ONLY allowlisted attributes.

    Non-allowlisted keys are dropped with a one-time warning (privacy must
    fail closed, not crash). On exception the span records a bounded error
    code (exception class name) and re-raises — messages and events stay out.

    Deliberately no keyword-only ``context`` parameter for the cross-process
    seam: every existing caller passes fields via a ``**{...}`` dict splat,
    and a typed non-str keyword parameter makes those splats a type error.
    ``traced_job`` (the only parent-override call site) starts its span
    directly instead.
    """

    span = _tracer().start_span(name)
    with trace.use_span(span, end_on_exit=True) as active:
        active.set_attribute("stage", stage)
        for key, value in fields.items():
            if key not in SPAN_ATTRIBUTE_ALLOWLIST:
                _report_dropped(key, "span attribute")
                continue
            active.set_attribute(key, value)
        try:
            yield active
        except Exception as exc:
            active.set_status(Status(StatusCode.ERROR))
            active.set_attribute("error.code", type(exc).__name__)
            raise


def traced_job(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap an arq task so each execution opens a worker-attempt span.

    Not generic on purpose: arq calls tasks positionally with ``ctx`` first,
    and ``functools.wraps`` keeps the module-qualified name the cron
    uniqueness keys derive from, so a plain callable signature is the honest
    shape here.

    Cross-process continuation (P0-5 slice 3): the enqueue seam injects the
    producer's traceparent as an ordinary job kwarg (arq jobs carry no
    headers), and it is extracted here as the worker span's parent so the
    api→worker hop keeps one trace id. The kwarg is popped before the call —
    task signatures never see it — and a malformed value degrades to a root
    span rather than an error.
    """

    name = getattr(fn, "__name__", "job")

    @wraps(fn)
    async def wrapper(ctx: dict[str, Any] | None, *args: Any, **kwargs: Any) -> Any:
        fields: dict[str, Any] = {}
        if isinstance(ctx, dict):
            if ctx.get("job_id") is not None:
                fields["correlation.id"] = str(ctx["job_id"])
            if ctx.get("job_try") is not None:
                fields["job.try"] = int(ctx["job_try"])
        parent_context: Context | None = None
        traceparent = kwargs.pop("_traceparent", None)
        if isinstance(traceparent, str):
            parent_context = TraceContextTextMapPropagator().extract(
                carrier={"traceparent": traceparent}
            )
        # Started directly rather than via stage_span: this is the one span
        # whose parent comes from elsewhere (a remote producer), and adding
        # a typed keyword parameter to stage_span breaks its dict-splat
        # callers. The attribute face stays identical: "stage" plus the two
        # fields above, both allowlisted by construction, and the same
        # bounded error code on exception.
        span = _tracer().start_span(f"worker.{name}", context=parent_context)
        with trace.use_span(span, end_on_exit=True) as active:
            active.set_attribute("stage", "worker")
            for key, value in fields.items():
                active.set_attribute(key, value)
            try:
                return await fn(ctx, *args, **kwargs)
            except Exception as exc:
                active.set_status(Status(StatusCode.ERROR))
                active.set_attribute("error.code", type(exc).__name__)
                raise

    return wrapper
