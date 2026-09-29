from __future__ import annotations

from backend.main import app


def test_openapi_contains_frozen_contract_paths() -> None:
    schema = app.openapi()
    paths = schema["paths"]
    expected = {
        # Client contract (packages/contracts + apps/desktop/src/backend/client.ts)
        "/v1/events/batch",
        "/v1/tasks",
        "/v1/current-state",
        "/v1/plans/today",
        "/v1/plans/{plan_id}/confirm",
        "/v1/focus-sessions",
        "/v1/focus-sessions/{session_id}",
        # Internal/core surface
        "/v1/auth/register",
        "/v1/auth/login",
        "/v1/auth/me",
        "/v1/events",
        "/v1/goals",
        "/v1/memory",
        "/v1/plans",
        "/v1/plans/generate",
        "/v1/files",
        "/v1/permissions/policy",
        "/v1/audit",
        "/v1/jobs/ping",
        "/health",
        "/health/ready",
    }
    missing = expected - set(paths)
    assert not missing, f"Missing OpenAPI paths: {sorted(missing)}"


def test_openapi_error_envelope_is_documented() -> None:
    schema = app.openapi()
    components = schema["components"]["schemas"]
    assert "ErrorResponse" in components
    assert "ErrorBody" in components


def test_openapi_prefix_is_v1() -> None:
    paths = app.openapi()["paths"]
    assert not [path for path in paths if path.startswith("/api/")]


def test_openapi_oauth2_token_url_matches_api_prefix() -> None:
    schema = app.openapi()
    flows = schema["components"]["securitySchemes"]["OAuth2PasswordBearer"]["flows"]
    token_url = flows["password"]["tokenUrl"]
    assert token_url == "/v1/auth/token"
    assert token_url in schema["paths"]
    assert not token_url.startswith("/api/")
