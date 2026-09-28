from __future__ import annotations

from datetime import timedelta

import pytest

from backend.core.errors import AuthenticationError
from backend.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_password_hash_roundtrip() -> None:
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong password", hashed)


def test_password_hash_is_salted() -> None:
    assert hash_password("same-password") != hash_password("same-password")


def test_verify_password_handles_invalid_hash() -> None:
    assert verify_password("password", "not-a-bcrypt-hash") is False


def test_access_token_roundtrip() -> None:
    token = create_access_token("user-123", extra_claims={"role": "student"})
    payload = decode_access_token(token)
    assert payload["sub"] == "user-123"
    assert payload["role"] == "student"
    assert payload["type"] == "access"


def test_expired_token_is_rejected() -> None:
    token = create_access_token("user-123", expires_delta=timedelta(seconds=-1))
    with pytest.raises(AuthenticationError):
        decode_access_token(token)


def test_tampered_token_is_rejected() -> None:
    token = create_access_token("user-123")
    with pytest.raises(AuthenticationError):
        decode_access_token(token + "tampered")


def test_rate_limiter_allows_within_window_and_blocks_after() -> None:
    from backend.core.rate_limit import RateLimiter

    limiter = RateLimiter(max_requests=2, window_seconds=10)
    assert limiter.hit("k", now=0.0) is True
    assert limiter.hit("k", now=1.0) is True
    assert limiter.hit("k", now=2.0) is False
    assert limiter.retry_after("k", now=2.0) == 9


def test_rate_limiter_window_slides() -> None:
    from backend.core.rate_limit import RateLimiter

    limiter = RateLimiter(max_requests=2, window_seconds=10)
    assert limiter.hit("k", now=0.0) is True
    assert limiter.hit("k", now=1.0) is True
    assert limiter.hit("k", now=2.0) is False
    # The oldest hit has aged out by t=10.5.
    assert limiter.hit("k", now=10.5) is True


def test_rate_limiter_disabled_when_max_zero() -> None:
    from backend.core.rate_limit import RateLimiter

    limiter = RateLimiter(max_requests=0, window_seconds=10)
    assert all(limiter.hit("k") for _ in range(50))
