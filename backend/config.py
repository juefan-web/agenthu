"""Application settings.

All runtime configuration is resolved from environment variables (or a local `.env`
file). Secrets never live in code. Field names map to upper-case env vars, e.g.
``database_url`` <- ``DATABASE_URL``.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Application -------------------------------------------------------
    app_name: str = "AgentHU"
    environment: str = "local"
    debug: bool = False
    log_level: str = "INFO"
    api_v1_prefix: str = "/api/v1"

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
    secret_key: str = "dev-insecure-change-me"
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
    cors_origins: list[str] = Field(default_factory=lambda: ["*"])

    # --- Observability -----------------------------------------------------
    audit_enabled: bool = True

    @property
    def is_local(self) -> bool:
        return self.environment.lower() in {"local", "dev", "development", "test"}


@lru_cache
def get_settings() -> Settings:
    """Return a cached ``Settings`` instance."""

    return Settings()


def clear_settings_cache() -> None:
    """Reset the cached settings (used by tests)."""

    get_settings.cache_clear()
