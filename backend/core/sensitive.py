"""Detection and rejection of sensitive fields at ingestion boundaries.

Credentials (passwords, cookies, tokens, OTPs) must never enter the Event store
or the logging pipeline. The check is recursive over dict/list structures and
reports only the *path*, never the value, so errors and logs stay safe.
"""

from __future__ import annotations

import json
import re
from typing import Any

SENSITIVE_KEY_PATTERN = re.compile(
    r"^(?:"
    r"password|passwd|pwd|"
    r"cookie|set[_-]?cookie|"
    r"authorization|"
    r"access[_-]?token|refresh[_-]?token|id[_-]?token|token|"
    r"otp|2fa|verification[_-]?code|"
    r"secret|api[_-]?key|client[_-]?secret"
    r")$",
    re.IGNORECASE,
)

MAX_JSON_DEPTH = 20
MAX_JSON_BYTES = 256 * 1024


def find_sensitive_paths(
    value: Any, *, path: str = "$", found: list[str] | None = None
) -> list[str]:
    """Return dotted paths of any keys that look like credentials."""

    if found is None:
        found = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if SENSITIVE_KEY_PATTERN.match(str(key)):
                found.append(child_path)
            find_sensitive_paths(child, path=child_path, found=found)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            find_sensitive_paths(item, path=f"{path}[{index}]", found=found)
    return found


def _depth(value: Any) -> int:
    if isinstance(value, dict) and value:
        return 1 + max(_depth(child) for child in value.values())
    if isinstance(value, list) and value:
        return 1 + max(_depth(child) for child in value)
    return 1


def validate_json_payload(section: str, value: Any) -> str | None:
    """Validate a JSON section; return an error message or ``None`` if safe.

    The message contains only the section name and offending key paths, never
    the values.
    """

    sensitive = find_sensitive_paths(value, path=section)
    if sensitive:
        return f"Sensitive fields are not allowed in events: {', '.join(sensitive)}"

    try:
        encoded = json.dumps(value, default=str).encode("utf-8")
    except (TypeError, ValueError):
        return f"{section} must be JSON-serializable"

    if len(encoded) > MAX_JSON_BYTES:
        return f"{section} exceeds the maximum allowed size of {MAX_JSON_BYTES} bytes"
    if _depth(value) > MAX_JSON_DEPTH:
        return f"{section} exceeds the maximum allowed nesting depth of {MAX_JSON_DEPTH}"
    return None
