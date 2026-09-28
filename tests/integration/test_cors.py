from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration

CLIENT_ORIGIN = "http://localhost:5173"
FROZEN_CLIENT_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "tauri://localhost",
    "http://tauri.localhost",
)


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


@pytest.mark.parametrize("origin", FROZEN_CLIENT_ORIGINS)
def test_preflight_allows_every_frozen_client_origin(client, origin: str) -> None:
    response = client.options(
        "/v1/plans/today",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert response.status_code == 200, response.text
    assert response.headers["access-control-allow-origin"] == origin
    assert "authorization" in response.headers["access-control-allow-headers"].lower()


@pytest.mark.parametrize("method", ["POST", "PATCH"])
def test_preflight_allows_bearer_requests_for_write_methods(client, method: str) -> None:
    # Bearer JWT (D-018) is sent via the Authorization header, including on writes.
    response = client.options(
        "/v1/tasks",
        headers={
            "Origin": CLIENT_ORIGIN,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert response.status_code == 200, response.text
    assert response.headers["access-control-allow-origin"] == CLIENT_ORIGIN
    allowed_headers = response.headers["access-control-allow-headers"].lower()
    assert "authorization" in allowed_headers
    assert method in response.headers["access-control-allow-methods"]


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


def test_wildcard_origin_disables_credentials(monkeypatch) -> None:
    """A `*` origin cannot be combined with credentials; the app fails safe."""

    from backend.config import clear_settings_cache
    from backend.main import create_app

    monkeypatch.setenv("CORS_ORIGINS", '["*"]')
    monkeypatch.setenv("CORS_ALLOW_CREDENTIALS", "true")
    clear_settings_cache()
    try:
        application = create_app()
        with TestClient(application) as test_client:
            response = test_client.options(
                "/v1/tasks",
                headers={
                    "Origin": "http://example.com",
                    "Access-Control-Request-Method": "GET",
                },
            )
        assert response.headers["access-control-allow-origin"] == "*"
        assert "access-control-allow-credentials" not in {key.lower() for key in response.headers}
    finally:
        clear_settings_cache()
