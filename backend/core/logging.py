"""Structured, redaction-friendly logging configuration.

Logs are emitted as single-line key=value pairs so they can be shipped to an
aggregator without a JSON dependency. Never log raw request bodies, chat
content, audio or location data.
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


class KeyValueFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = f"{self.formatTime(record, '%Y-%m-%dT%H:%M:%S%z')} level={record.levelname}"
        base += f" logger={record.name} msg={record.getMessage()!r}"
        extras = {k: v for k, v in record.__dict__.items() if k not in _RESERVED}
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
