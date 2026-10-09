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
    # Bounds both connect and socket timeouts on the rate-limit ledger: a
    # request must fail closed quickly, not hang on a dead Redis.
    rate_limit_redis_timeout_seconds: float = Field(default=0.5, gt=0.0)

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

    # --- Model provider (D-033; first implementation: OpenAI) --------------
    # Empty key = fail-closed: embedding calls raise ModelProviderUnavailable
    # instead of silently skipping (never report "embedded" without a call).
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    embedding_model: str = "text-embedding-3-small"
    responses_model: str = "gpt-4o-mini"
    responses_timeout_seconds: float = 60.0
    embedding_batch_size: int = 64
    embedding_timeout_seconds: float = 30.0
    embedding_max_retries: int = 3

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
    # P0-5 slice 1 (frozen ruling 1): standard OTel SDK + official
    # instrumentation, OTLP/HTTP the only wire format. Disabled by default —
    # dev/test/CI emit nothing until the alpha stack opts in; when enabled,
    # the span-attribute allowlist in core/telemetry.py is the only channel.
    otel_enabled: bool = False
    otel_exporter_otlp_endpoint: str = "http://127.0.0.1:4318/v1/traces"
    otel_sample_ratio: float = Field(default=1.0, ge=0.0, le=1.0)
    otel_export_timeout_seconds: float = 2.0
    # P0-5 slice 1 (frozen ruling 2): zero-trust proxy boundary — the socket
    # peer is the client source; X-Forwarded-For is honoured only when the
    # peer is explicitly listed here (rightmost entry). Empty (default)
    # ignores the header everywhere: fail closed against spoofed sources.
    trusted_proxies: list[str] = Field(default_factory=list)

    # --- Agent runtime (D-034 §5.1/§6 defaults; review point 8) -----------
    # Pending-action TTL: 24h, tools may shorten but never below the floor.
    agent_pending_ttl_hours: int = 24
    agent_pending_min_ttl_minutes: int = 5
    # Worker claim leases: run execution and pending-action execution.
    agent_run_lease_seconds: int = 300
    agent_execution_lease_seconds: int = 300
    # Provider tool-call loop caps (§6.2): 4 model turns, 8 tool calls.
    agent_max_model_turns: int = 4
    agent_max_tool_calls: int = 8
    # Context assembly (§6.1): token budget with the reserved head for
    # policy/tool-schema/rules; chunk render cap keeps one chunk bounded.
    agent_context_token_budget: int = 8000
    agent_context_reserved_tokens: int = 1200
    agent_history_window: int = 10
    agent_chunk_render_char_cap: int = 2000

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
