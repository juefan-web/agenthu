"""Authentication contract tests (DECISIONS.md D-018).

Covers the stable `/register`, `/login`, `/token` and `/me` fixtures plus the
missing / invalid / expired Bearer token semantics: every rejection is a `401`
with the frozen error envelope and a `WWW-Authenticate: Bearer` header.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


def _assert_unauthorized(response) -> None:
    assert response.status_code == 401, response.text
    body = response.json()
    assert set(body) == {"error"}
    error = body["error"]
    assert error["code"] == "unauthenticated"
    assert isinstance(error["message"], str) and error["message"]
    assert error["details"] == {}
    assert response.headers.get("WWW-Authenticate") == "Bearer"


def test_register_login_and_me(client, register_user) -> None:
    payload = register_user()
    login = client.post(
        "/v1/auth/login",
        json={"email": payload["email"], "password": payload["password"]},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]

    me = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    body = me.json()
    assert body["email"] == payload["email"]
    assert "hashed_password" not in body
    assert "password" not in body


def test_register_response_is_the_public_user_shape(client, register_user) -> None:
    user = register_user()
    assert set(user) >= {"id", "email", "display_name", "is_active"}
    assert user["is_active"] is True
    assert "hashed_password" not in user


def test_login_response_shape(client, register_user) -> None:
    payload = register_user()
    response = client.post(
        "/v1/auth/login",
        json={"email": payload["email"], "password": payload["password"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"access_token", "token_type", "expires_in"}
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0


def test_login_token_headers_fixture_calls_me(client, login_token_headers) -> None:
    response = client.get("/v1/auth/me", headers=login_token_headers)
    assert response.status_code == 200
    assert response.json()["is_active"] is True


def test_oauth2_form_token_fixture_calls_me(client, oauth_token_headers) -> None:
    response = client.get("/v1/auth/me", headers=oauth_token_headers)
    assert response.status_code == 200
    assert "hashed_password" not in response.json()


def test_register_is_case_insensitive_for_email(client, register_user) -> None:
    payload = register_user(email="MixedCase@Example.com")
    assert payload["email"] == "mixedcase@example.com"
    duplicate = client.post("/v1/auth/register", json={**payload, "email": "MIXEDCASE@example.com"})
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "conflict"


def test_login_with_wrong_password_is_rejected(client, register_user) -> None:
    payload = register_user()
    response = client.post(
        "/v1/auth/login",
        json={"email": payload["email"], "password": "not-the-password"},
    )
    _assert_unauthorized(response)


def test_missing_token_returns_401_envelope(client) -> None:
    _assert_unauthorized(client.get("/v1/auth/me"))
    _assert_unauthorized(client.get("/v1/tasks"))


def test_invalid_token_returns_401_envelope(client) -> None:
    response = client.get("/v1/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    _assert_unauthorized(response)


def test_malformed_authorization_header_returns_401_envelope(client) -> None:
    response = client.get("/v1/auth/me", headers={"Authorization": "not-a-bearer-token"})
    _assert_unauthorized(response)


def test_expired_token_returns_401_envelope(client, expired_token_headers) -> None:
    response = client.get("/v1/auth/me", headers=expired_token_headers)
    _assert_unauthorized(response)
    assert "expired" in response.json()["error"]["message"].lower()


def test_expired_raw_token_is_rejected(client, expired_access_token) -> None:
    response = client.get("/v1/tasks", headers={"Authorization": f"Bearer {expired_access_token}"})
    _assert_unauthorized(response)


def test_oauth2_form_token_endpoint(client, register_user) -> None:
    payload = register_user()
    response = client.post(
        "/v1/auth/token",
        data={"username": payload["email"], "password": payload["password"]},
    )
    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"


def test_oauth2_form_token_rejects_bad_credentials(client: TestClient) -> None:
    response = client.post(
        "/v1/auth/token",
        data={"username": "nobody@example.com", "password": "wrong-password"},
    )
    _assert_unauthorized(response)


def test_login_is_rate_limited_per_client_ip(client: TestClient, register_user) -> None:
    """Brute-force protection: over-limit auth attempts get 429 + Retry-After."""

    import backend.api.v1.auth as auth_module
    from backend.core.rate_limit import RateLimiter

    original = auth_module._auth_limiter
    auth_module._auth_limiter = RateLimiter(max_requests=3, window_seconds=60)
    try:
        payload = {"email": "rl@example.com", "password": "password123"}
        codes = [client.post("/v1/auth/login", json=payload).status_code for _ in range(5)]
        assert codes[:3] == [401, 401, 401]
        assert codes[3] == 429
        assert codes[4] == 429

        throttled = client.post("/v1/auth/login", json=payload)
        assert throttled.status_code == 429
        assert throttled.json()["error"]["code"] == "rate_limited"
        assert int(throttled.headers["Retry-After"]) >= 1
    finally:
        auth_module._auth_limiter = original


def test_register_is_rate_limited(client: TestClient) -> None:
    import backend.api.v1.auth as auth_module
    from backend.core.rate_limit import RateLimiter

    original = auth_module._auth_limiter
    auth_module._auth_limiter = RateLimiter(max_requests=2, window_seconds=60)
    try:
        codes = [
            client.post(
                "/v1/auth/register",
                json={
                    "email": f"u{i}@example.com",
                    "password": "password123",
                    "display_name": "Rate Limit Probe",
                },
            ).status_code
            for i in range(3)
        ]
        assert codes == [201, 201, 429]
    finally:
        auth_module._auth_limiter = original


def test_jobs_status_hides_other_users_jobs(client: TestClient, auth_factory) -> None:
    """Job ids are user-scoped; another user's job id is a 404, not a leak."""

    alice = auth_factory()
    bob = auth_factory()
    me = client.get("/v1/auth/me", headers=alice).json()
    foreign_id = f"{me['id']}:ping:abc123"

    # Ownership is enforced before any Redis round-trip, so no queue is needed.
    response = client.get(f"/v1/jobs/{foreign_id}", headers=bob)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"

    own = client.get(f"/v1/jobs/{foreign_id}", headers=alice)
    assert own.status_code in (200, 503)
