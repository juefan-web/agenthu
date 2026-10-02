"""Shared test fixtures.

Integration tests run against a real PostgreSQL database (``TEST_DATABASE_URL``)
and are skipped automatically when it is unavailable. Each test runs inside an
outer transaction that is rolled back, so tests are isolated and order-independent.
"""

from __future__ import annotations

import os

# Must be set before importing backend modules (Settings is cached).
_DEFAULT_TEST_DB = "postgresql+psycopg://agenthu:agenthu@127.0.0.1:5432/agenthu_test"
os.environ.setdefault("TEST_DATABASE_URL", _DEFAULT_TEST_DB)
os.environ.setdefault("DATABASE_URL", _DEFAULT_TEST_DB)
os.environ.setdefault("STORAGE_BACKEND", "memory")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("AUDIT_ENABLED", "false")
# ENVIRONMENT defaults to "production" (fail closed); tests opt into the local
# set explicitly, and auth rate limiting is off unless a test enables it.
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("AUTH_RATE_LIMIT_MAX", "0")

import socket  # noqa: E402
import uuid  # noqa: E402
from collections.abc import Callable, Iterator  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import (  # noqa: E402
    Engine,
    create_engine,
    text,
)
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

import backend.models  # noqa: E402,F401  (register models)
from backend.config import get_settings  # noqa: E402
from backend.core.security import create_access_token  # noqa: E402
from backend.db.base import Base  # noqa: E402
from backend.services.storage import InMemoryStorage  # noqa: E402

TEST_DATABASE_URL = os.environ["TEST_DATABASE_URL"]

_LOCAL_TZ = ZoneInfo(get_settings().default_timezone)


def skip_late_night(minutes_needed: int) -> None:
    """The single grep-able late-night guard for clock-sensitive tests.

    Planner v2 caps placement by the day's remaining minutes (D-027
    formula), so near local midnight an honest plan may be empty or only
    partially placed; tests that need real same-day placement call this
    instead of reimplementing the window check. One definition plus N call
    sites is the point: ``grep skip_late_night`` IS the audit — no second
    "midnight/skip pattern" sweep needed (the M3 first-day lesson).
    """

    now = datetime.now(_LOCAL_TZ)
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    if (midnight - now).total_seconds() // 60 < minutes_needed:
        pytest.skip(f"late-night window: less than {minutes_needed} minutes left today")


def tcp_available(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    try:
        test_engine = create_engine(
            TEST_DATABASE_URL, poolclass=NullPool, connect_args={"connect_timeout": 3}
        )
        with test_engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        pytest.skip("PostgreSQL is not available for integration tests")

    Base.metadata.drop_all(test_engine)
    # The memories.embedding column uses pgvector's VECTOR type, so create_all
    # needs the extension present in the test database (per-database object;
    # migrations create it in their own databases via op.execute).
    with test_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        c.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(test_engine)
    yield test_engine
    Base.metadata.drop_all(test_engine)
    test_engine.dispose()


@pytest.fixture
def db_session(engine: Engine) -> Iterator[Session]:
    connection = engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    session = factory()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def storage() -> InMemoryStorage:
    return InMemoryStorage()


@pytest.fixture
def app(db_session: Session, storage: InMemoryStorage):
    from backend.db.session import get_db
    from backend.main import create_app
    from backend.services.storage import get_storage

    application = create_app()

    def _override_db() -> Iterator[Session]:
        yield db_session

    application.dependency_overrides[get_db] = _override_db
    application.dependency_overrides[get_storage] = lambda: storage
    return application


@pytest.fixture
def client(app) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def register_user(client: TestClient):
    def _register(
        email: str | None = None,
        password: str = "password123",
        display_name: str = "Test User",
    ) -> dict[str, str]:
        payload = {
            "email": email or f"user-{uuid.uuid4().hex[:10]}@example.com",
            "password": password,
            "display_name": display_name,
        }
        response = client.post("/v1/auth/register", json=payload)
        assert response.status_code == 201, response.text
        # Merge the server response (normalized email) with the credentials.
        return {**payload, **response.json()}

    return _register


def login_headers(client: TestClient, email: str, password: str) -> dict[str, str]:
    response = client.post("/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def auth_factory(client: TestClient, register_user):
    def _make(email: str | None = None) -> dict[str, str]:
        payload = register_user(email=email)
        return login_headers(client, payload["email"], payload["password"])

    return _make


@pytest.fixture
def auth_headers(auth_factory) -> dict[str, str]:
    return auth_factory()


@pytest.fixture
def login_token_headers(client: TestClient, register_user) -> dict[str, str]:
    """Bearer headers obtained from the JSON ``POST /v1/auth/login`` endpoint."""

    payload = register_user()
    return login_headers(client, payload["email"], payload["password"])


@pytest.fixture
def oauth_token_headers(client: TestClient, register_user) -> dict[str, str]:
    """Bearer headers obtained from the OAuth2 form ``POST /v1/auth/token`` endpoint."""

    payload = register_user()
    response = client.post(
        "/v1/auth/token",
        data={"username": payload["email"], "password": payload["password"]},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def token_factory(register_user) -> Callable[..., tuple[dict[str, str], dict[str, str]]]:
    """Issue Bearer headers directly for a registered user with a custom expiry.

    Returns ``(headers, user)``; ``user`` carries the normalized email and id.
    """

    def _issue(
        *,
        email: str | None = None,
        expires_delta: timedelta | None = None,
    ) -> tuple[dict[str, str], dict[str, str]]:
        user = register_user(email=email)
        token = create_access_token(user["id"], expires_delta=expires_delta)
        return {"Authorization": f"Bearer {token}"}, user

    return _issue


@pytest.fixture
def expired_token_headers(token_factory) -> dict[str, str]:
    """Bearer headers whose JWT is already expired (D-018 401 semantics)."""

    headers, _ = token_factory(expires_delta=timedelta(seconds=-60))
    return headers


@pytest.fixture
def expired_access_token(token_factory) -> str:
    """An expired raw JWT for the same 401 checks."""

    headers, _ = token_factory(expires_delta=timedelta(seconds=-60))
    return headers["Authorization"].removeprefix("Bearer ")
