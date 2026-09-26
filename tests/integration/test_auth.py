from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


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
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


def test_protected_route_requires_authentication(client) -> None:
    response = client.get("/v1/events")
    assert response.status_code == 401


def test_oauth2_form_token_endpoint(client, register_user) -> None:
    payload = register_user()
    response = client.post(
        "/v1/auth/token",
        data={"username": payload["email"], "password": payload["password"]},
    )
    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
