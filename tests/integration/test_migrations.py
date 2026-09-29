"""Migration integrity: the migration must build the schema from zero.

This runs against a throwaway database so it cannot disturb the shared test
schema. It validates upgrade-from-zero, downgrade-to-base, and that the
migration head matches the SQLAlchemy models (no drift).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from backend.config import clear_settings_cache

pytestmark = pytest.mark.integration

_REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def temp_database() -> Iterator[str]:
    base_url = os.environ["TEST_DATABASE_URL"]
    server_url, _, _ = base_url.rpartition("/")
    admin_url = f"{server_url}/postgres"
    database_name = f"agenthu_mig_{uuid.uuid4().hex[:8]}"

    admin = create_engine(
        admin_url,
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
        connect_args={"connect_timeout": 3},
    )
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    except Exception:
        admin.dispose()
        pytest.skip("Cannot create a temporary database for migration tests")
    admin.dispose()

    temp_url = f"{server_url}/{database_name}"
    try:
        yield temp_url
    finally:
        cleanup = create_engine(
            admin_url,
            isolation_level="AUTOCOMMIT",
            poolclass=NullPool,
            connect_args={"connect_timeout": 3},
        )
        with cleanup.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)'))
        cleanup.dispose()


def test_migration_upgrade_downgrade_and_no_drift(temp_database: str) -> None:
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = temp_database
    clear_settings_cache()
    try:
        config = Config(str(_REPO_ROOT / "alembic.ini"))
        config.set_main_option("sqlalchemy.url", temp_database)

        command.upgrade(config, "head")
        command.check(config)  # no drift between models and migration head

        command.downgrade(config, "base")
        command.upgrade(config, "head")
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        clear_settings_cache()
