"""Application settings.

All runtime configuration is resolved from environment variables (or a local `.env`
file). Secrets never live in code. Field names map to upper-case env vars, e.g.
``database_url`` <- ``DATABASE_URL``.
"""

from __future__ import annotations

from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SECRET_KEY = "dev-insecure-change-me"
MIN_SECRET_KEY_LENGTH = 32
# Fail closed: an operator who configures nothing must not silently get a
# forgeable JWT key or the development object-storage credential.
DEFAULT_ENVIRONMENT = "production"
_WEAK_SECRET_KEYS = {DEFAULT_SECRET_KEY, "", "secret", "changeme"}
_WEAK_S3_SECRET_KEYS = {"agenthu123", "", "secret", "changeme"}
MIN_S3_SECRET_KEY_LENGTH = 16


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Application -------------------------------------------------------
    app_name: str = "AgentHU"
    # Defaults to "production": forgetting to set ENVIRONMENT must fail closed
    # (weak SECRET_KEY / S3_SECRET_KEY rejected), not silently pass. Local
    # development opts in explicitly via ENVIRONMENT=local (see .env.example).
    environment: str = DEFAULT_ENVIRONMENT
    debug: bool = False
    log_level: str = "INFO"
    api_v1_prefix: str = "/v1"
    # Timezone used to decide the "today" boundary for plans.
    default_timezone: str = "Asia/Shanghai"

    # --- Database ----------------------------------------------------------
    # 127.0.0.1 (not "localhost") avoids IPv6/IPv4 ambiguity on Windows, where
    # async clients may resolve localhost to ::1 while Docker maps IPv4 only.
    database_url: str = "postgresql+psycopg://agenthu:agenthu@127.0.0.1:5432/agenthu"
    test_database_url: str = "postgresql+psycopg://agenthu:agenthu@127.0.0.1:5432/agenthu_test"
    db_echo: bool = False
    db_pool_size: int = 5
    db_max_overflow: int = 10

    # --- Redis / Arq -------------------------------------------------------
    redis_url: str = "redis://127.0.0.1:6379/0"
    arq_queue_name: str = "arq:queue"

    # --- Auth --------------------------------------------------------------
    auth_rate_limit_max: int = 10
    auth_rate_limit_window_seconds: int = 60
    secret_key: str = DEFAULT_SECRET_KEY
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7

    # --- Object storage ----------------------------------------------------
    storage_backend: str = "minio"  # "minio" | "memory"
    s3_endpoint_url: str = "http://127.0.0.1:9000"
    s3_access_key: str = "agenthu"
    s3_secret_key: str = "agenthu123"
    s3_bucket: str = "agenthu"
    s3_region: str = "us-east-1"
    s3_use_ssl: bool = False
    signed_url_expire_seconds: int = 3600
    max_upload_bytes: int = 50 * 1024 * 1024

    # --- CORS --------------------------------------------------------------
    # Explicit origins, never "*" together with credentialed requests: browsers
    # reject `Access-Control-Allow-Origin: *` when credentials are included.
    # Tauri uses the dev server origin (Vite) and the `tauri://localhost` origin.
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            # Tauri devUrl (apps/desktop/src-tauri/tauri.conf.json).
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            # Tauri production webview origins.
            "tauri://localhost",
            "http://tauri.localhost",
        ]
    )
    cors_allow_credentials: bool = True

    # --- Observability -----------------------------------------------------
    audit_enabled: bool = True

    @property
    def is_local(self) -> bool:
        return self.environment.lower() in {"local", "dev", "development", "test"}

    @field_validator("default_timezone")
    @classmethod
    def _validate_default_timezone(cls, value: str) -> str:
        # Fail at settings load, not on the first `/v1/plans/today` request,
        # where an invalid zone would surface as an opaque 500.
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"Invalid DEFAULT_TIMEZONE {value!r}: {exc}") from exc
        return value

    @model_validator(mode="after")
    def _enforce_strong_secrets_outside_local(self) -> Settings:
        if self.is_local:
            return self
        if self.secret_key in _WEAK_SECRET_KEYS:
            raise ValueError(
                "SECRET_KEY must be set to a strong, unique value outside local environments"
            )
        if len(self.secret_key) < MIN_SECRET_KEY_LENGTH:
            raise ValueError(
                f"SECRET_KEY must be at least {MIN_SECRET_KEY_LENGTH} characters outside "
                "local environments"
            )
        if self.s3_secret_key in _WEAK_S3_SECRET_KEYS or (
            len(self.s3_secret_key) < MIN_S3_SECRET_KEY_LENGTH
        ):
            raise ValueError(
                "S3_SECRET_KEY must be set to a strong, unique value outside local environments"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Return a cached ``Settings`` instance."""

    return Settings()


def clear_settings_cache() -> None:
    """Reset the cached settings (used by tests)."""

    get_settings.cache_clear()
