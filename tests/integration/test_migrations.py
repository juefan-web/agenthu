"""Migration integrity: the migration must build the schema from zero.

This runs against a throwaway database so it cannot disturb the shared test
schema. It validates upgrade-from-zero, downgrade-to-base, and that the
migration head matches the SQLAlchemy models (no drift).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from backend.config import clear_settings_cache
from backend.models.enums import TaskStatus
from backend.models.event import Event
from backend.models.memory import Memory
from backend.models.task import Task
from backend.models.user import User
from backend.services.event_handlers import process_event

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


def test_focus_learning_handler_on_migrated_schema(temp_database: str) -> None:
    """The learning writer must work on the MIGRATION-built schema.

    Regression for the E4 first-run failure: create_all-built test databases
    rendered the memory_kind CHECK from the model (uppercase member names),
    while migration e52a9d3b1c48 writes the lowercase values — so the
    learning writer passed every test and failed every real deployment. The
    model now binds values; this test runs focus.completed against a schema
    built purely by the migrations.
    """

    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = temp_database
    clear_settings_cache()
    try:
        config = Config(str(_REPO_ROOT / "alembic.ini"))
        config.set_main_option("sqlalchemy.url", temp_database)
        command.upgrade(config, "head")

        engine = create_engine(temp_database, poolclass=NullPool)
        Session = sessionmaker(bind=engine)
        with Session() as session:
            user = User(
                email="mig-handler@example.com",
                display_name="Mig",
                hashed_password="not-a-real-hash",  # handler path never logs in
                is_active=True,
            )
            session.add(user)
            session.flush()
            course = f"迁移课-{uuid.uuid4().hex[:6]}"
            task = Task(
                user_id=user.id,
                title=f"{course}：作业一",
                source="onethu",
                status=TaskStatus.TODO,
                deadline=datetime.now(UTC) + timedelta(days=1),
                extra={"course_name": course},
            )
            session.add(task)
            session.flush()
            event = Event(
                user_id=user.id,
                type="focus.completed",
                timestamp=datetime.now(UTC),
                source="backend",
                data={
                    "task_id": str(task.id),
                    "actual_minutes": 55,
                    "completed": True,
                    "notes": "迁移库冒烟",
                },
                context={},
                provenance={"fixture": "test_migrations.learning"},
                dedupe_key=f"mig:{uuid.uuid4().hex}",
            )
            session.add(event)
            session.flush()

            process_event(session, event)
            session.flush()

            session.refresh(task)
            # The completion survives even though it shares the event with
            # the learning writer (independent savepoints).
            assert task.status == TaskStatus.COMPLETED
            assert task.actual_duration_minutes == 55
            memories = list(session.scalars(select(Memory).where(Memory.user_id == user.id)))
            kinds = {(m.kind.value if m.kind else None) for m in memories}
            assert "episode" in kinds
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(Memory)
                    .where(Memory.subject_key == f"estimate:course:{course}")
                )
                == 1
            )
        engine.dispose()
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        clear_settings_cache()
