"""Structured, redaction-friendly logging configuration.

Logs are emitted as single-line key=value pairs so they can be shipped to an
aggregator without a JSON dependency. Never log raw request bodies, chat
content, audio or location data.

P0-5 slice 1 hardening: extras are allowlisted on the same family as the
span-attribute allowlist (ops contract §6) — random correlation ids, bounded
labels/enums, counters and durations. Anything else attached via ``extra=``
is DROPPED (silently, by design — privacy fails closed). Notably user_id
(a stable identity UUID), course_name (user content) and the audit "action"
string (method + instantiated path) fall outside the allowlist and no longer
render; use route templates and correlation ids instead.
"""

from __future__ import annotations

import logging
import sys

from backend.config import get_settings

_RESERVED = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "taskName",
    "message",
}

LOG_FIELD_ALLOWLIST = frozenset(
    {
        # Random per-incident correlation ids (uuid4 minted per event — not
        # stable identity UUIDs like user_id).
        "request_id",
        "job_id",
        "run_id",
        "operation_id",
        "file_id",
        "item_id",
        "event_id",
        "chat_id",
        # Bounded labels and enums.
        "event_type",
        "status",
        "stage",
        "method",
        "route",
        "error_code",
        "worker",
        "service_version",
        # Counters and durations.
        "status_code",
        "duration_ms",
        "scan_ms",
        "embed_ms",
        "retry_count",
        "timeout_seconds",
        "usage_tokens",
        "usage_calls",
        "job_try",
        "vector_candidates",
        "keyword_candidates",
        "selected",
        "items_count",
        "clean",
        "flagged",
        "blocked",
        "replaced",
    }
)


class KeyValueFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = f"{self.formatTime(record, '%Y-%m-%dT%H:%M:%S%z')} level={record.levelname}"
        base += f" logger={record.name} msg={record.getMessage()!r}"
        extras = {
            k: v
            for k, v in record.__dict__.items()
            if k not in _RESERVED and k in LOG_FIELD_ALLOWLIST
        }
        for key, value in extras.items():
            base += f" {key}={value!r}"
        if record.exc_info:
            base += f" exc={self.formatException(record.exc_info)!r}"
        return base


def configure_logging() -> None:
    settings = get_settings()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(KeyValueFormatter())

    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(settings.log_level.upper())

    # SQLAlchemy echo is configured on the engine, avoid duplicate noisy logs.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
