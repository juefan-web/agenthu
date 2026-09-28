from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.config import DEFAULT_SECRET_KEY, Settings


def test_default_cors_origins_are_explicit() -> None:
    settings = Settings()
    assert "*" not in settings.cors_origins


def test_default_cors_origins_include_client_dev_url() -> None:
    # apps/desktop/src-tauri/tauri.conf.json sets devUrl http://localhost:5173.
    settings = Settings()
    assert "http://localhost:5173" in settings.cors_origins


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


@pytest.mark.parametrize("timezone", ["UTC", "Asia/Shanghai", "America/New_York"])
def test_valid_default_timezone_is_accepted(timezone: str) -> None:
    assert Settings(default_timezone=timezone).default_timezone == timezone


@pytest.mark.parametrize("timezone", ["Not/AZone", "", "UTC+8"])
def test_invalid_default_timezone_fails_at_settings_load(timezone: str) -> None:
    # Must fail when settings load, not later as a 500 on a plans request.
    with pytest.raises(ValidationError):
        Settings(default_timezone=timezone)
