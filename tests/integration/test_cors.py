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


def test_unhandled_exception_returns_envelope_with_cors_headers(app) -> None:
    """Unhandled 500s must carry the error envelope and CORS headers (D5).

    The Exception handler runs in ServerErrorMiddleware, outside
    CORSMiddleware: without explicit headers the WebView reports the failure
    as a CORS error, hiding the real 500.
    """

    def _boom() -> None:
        raise RuntimeError("unhandled test failure")

    app.add_api_route("/v1/__test/boom", _boom, methods=["GET"], include_in_schema=False)

    with TestClient(app, raise_server_exceptions=False) as test_client:
        response = test_client.get("/v1/__test/boom", headers={"Origin": CLIENT_ORIGIN})

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert body["error"]["message"] == "Internal server error"
    assert response.headers["access-control-allow-origin"] == CLIENT_ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"


def test_unhandled_exception_omits_cors_headers_for_unknown_origin(app) -> None:
    def _boom() -> None:
        raise RuntimeError("unhandled test failure")

    app.add_api_route("/v1/__test/boom", _boom, methods=["GET"], include_in_schema=False)

    with TestClient(app, raise_server_exceptions=False) as test_client:
        response = test_client.get("/v1/__test/boom", headers={"Origin": "https://evil.example"})

    assert response.status_code == 500
    assert "access-control-allow-origin" not in response.headers
