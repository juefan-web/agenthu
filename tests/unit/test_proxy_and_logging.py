"""P0-5 slice 1: zero-trust client-source resolution and the logging extras
allowlist (frozen ruling 2 + ops contract §6 hardening)."""

from __future__ import annotations

import logging

from starlette.requests import Request

from backend.config import Settings
from backend.core import proxy
from backend.core.logging import KeyValueFormatter


def _request(peer: str | None, xff: str | None = None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if xff is not None:
        headers.append((b"x-forwarded-for", xff.encode()))
    scope = {
        "type": "http",
        "client": (peer, 50000) if peer else None,
        "headers": headers,
        "query_string": b"",
        "method": "GET",
        "path": "/",
    }
    return Request(scope)


def _settings(trusted: list[str]) -> Settings:
    return Settings(environment="local", trusted_proxies=trusted)


def test_xff_ignored_without_trusted_proxies(monkeypatch) -> None:
    monkeypatch.setattr(proxy, "get_settings", lambda: _settings([]))
    assert proxy.client_ip(_request("203.0.113.7", "198.51.100.9")) == "203.0.113.7"


def test_trusted_peer_uses_rightmost_untrusted_xff(monkeypatch) -> None:
    monkeypatch.setattr(proxy, "get_settings", lambda: _settings(["203.0.113.7"]))
    # Chain "client, trusted-proxy": the proxy attests the client address.
    assert proxy.client_ip(_request("203.0.113.7", "198.51.100.9, 203.0.113.7")) == "198.51.100.9"
    # Single-entry chain appended by the proxy.
    assert proxy.client_ip(_request("203.0.113.7", "198.51.100.9")) == "198.51.100.9"


def test_all_trusted_chain_falls_back_to_peer(monkeypatch) -> None:
    monkeypatch.setattr(proxy, "get_settings", lambda: _settings(["198.51.100.9", "203.0.113.7"]))
    assert proxy.client_ip(_request("203.0.113.7", "198.51.100.9, 203.0.113.7")) == "203.0.113.7"


def test_untrusted_peer_ignores_xff_entirely(monkeypatch) -> None:
    monkeypatch.setattr(proxy, "get_settings", lambda: _settings(["10.0.0.1"]))
    assert proxy.client_ip(_request("203.0.113.7", "198.51.100.9")) == "203.0.113.7"


def test_malformed_xff_falls_back_to_peer(monkeypatch) -> None:
    monkeypatch.setattr(proxy, "get_settings", lambda: _settings(["203.0.113.7"]))
    assert proxy.client_ip(_request("203.0.113.7", "  ")) == "203.0.113.7"


def test_missing_client_is_unknown(monkeypatch) -> None:
    monkeypatch.setattr(proxy, "get_settings", lambda: _settings([]))
    assert proxy.client_ip(_request(None, "198.51.100.9")) == "unknown"


def test_extras_allowlist_keeps_correlation_fields() -> None:
    record = logging.LogRecord(
        "agenthu.test", logging.INFO, "path.py", 1, "extraction finished", None, None
    )
    record.file_id = "0e6f7ac0-1bd6-4c9e-9a72-000000000001"
    record.clean = 3
    record.flagged = 1
    assert "file_id='0e6f7ac0" in KeyValueFormatter().format(record)
    assert "clean=3" in KeyValueFormatter().format(record)


def test_extras_allowlist_drops_identity_and_content_fields() -> None:
    record = logging.LogRecord(
        "agenthu.test", logging.INFO, "path.py", 1, "trigger evaluation failed", None, None
    )
    record.user_id = "11111111-1111-1111-1111-111111111111"
    record.course_name = "Machine Learning"
    rendered = KeyValueFormatter().format(record)
    assert "user_id" not in rendered
    assert "course_name" not in rendered
    assert "11111111" not in rendered
    assert "Machine Learning" not in rendered
