from __future__ import annotations

from backend.main import app


def test_openapi_contains_frozen_contract_paths() -> None:
    schema = app.openapi()
    paths = schema["paths"]
    expected = {
        "/api/v1/auth/register",
        "/api/v1/auth/login",
        "/api/v1/auth/me",
        "/api/v1/events",
        "/api/v1/tasks",
        "/api/v1/goals",
        "/api/v1/current-state",
        "/api/v1/memory",
        "/api/v1/plans",
        "/api/v1/plans/generate",
        "/api/v1/files",
        "/api/v1/permissions/policy",
        "/api/v1/audit",
        "/api/v1/jobs/ping",
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
