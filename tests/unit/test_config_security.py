from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.config import DEFAULT_SECRET_KEY, Settings


def test_local_environment_allows_default_secret() -> None:
    settings = Settings(environment="local", secret_key=DEFAULT_SECRET_KEY)
    assert settings.is_local


def test_non_local_environment_rejects_default_secret() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="production", secret_key=DEFAULT_SECRET_KEY)


def test_non_local_environment_rejects_short_secret() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="production", secret_key="too-short")


def test_non_local_environment_accepts_strong_secret() -> None:
    settings = Settings(
        environment="production",
        secret_key="a-very-strong-and-long-secret-key-value-1234567890",
    )
    assert not settings.is_local
