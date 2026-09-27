from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration

CLIENT_ORIGIN = "http://localhost:5173"


def test_preflight_allows_client_dev_origin_with_credentials(client) -> None:
    response = client.options(
        "/v1/tasks",
        headers={
            "Origin": CLIENT_ORIGIN,
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == CLIENT_ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"


def test_simple_request_echoes_allowed_origin(client) -> None:
    response = client.get("/health", headers={"Origin": CLIENT_ORIGIN})
    assert response.headers["access-control-allow-origin"] == CLIENT_ORIGIN


def test_disallowed_origin_is_not_allowed(client) -> None:
    response = client.options(
        "/v1/tasks",
        headers={
            "Origin": "http://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" not in {key.lower() for key in response.headers}
