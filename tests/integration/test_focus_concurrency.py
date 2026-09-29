"""Concurrency tests for Focus session start (integration review blocking item 1).

``test_focus_sessions.py`` proves sequential idempotency of
``create_focus_session``, but it shares one session and cannot catch the
read-then-insert race. This test uses independent database connections (the
real production shape: one connection per request) and a barrier so both
callers start from "no active session" before either commits.
"""

from __future__ import annotations

import threading
import uuid

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import sessionmaker

from backend.models.enums import FocusSessionStatus, TaskStatus
from backend.models.focus_session import FocusSession
from backend.models.task import Task
from backend.models.user import User
from backend.services.focus import create_focus_session

pytestmark = pytest.mark.integration


def _seed_user_with_task(engine) -> tuple[uuid.UUID, uuid.UUID]:
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        user = User(
            email=f"focus-race-{uuid.uuid4().hex[:10]}@example.com",
            display_name="Focus Race User",
            hashed_password="not-a-real-hash",
        )
        session.add(user)
        session.flush()
        task = Task(user_id=user.id, title="HW", status=TaskStatus.TODO)
        session.add(task)
        session.commit()
        return user.id, task.id


def _running_session_count(engine, user_id: uuid.UUID, task_id: uuid.UUID) -> int:
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        count = session.scalar(
            select(func.count())
            .select_from(FocusSession)
            .where(
                FocusSession.user_id == user_id,
                FocusSession.task_id == task_id,
                FocusSession.status == FocusSessionStatus.RUNNING,
            )
        )
    return int(count or 0)


def test_concurrent_focus_starts_yield_one_session(engine) -> None:
    user_id, task_id = _seed_user_with_task(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    barrier = threading.Barrier(2)
    results: list[object] = [None, None]

    def call(index: int) -> None:
        with factory() as session:
            try:
                barrier.wait(timeout=10)
                task = session.get(Task, task_id)
                assert task is not None
                focus = create_focus_session(session, user_id=user_id, task=task)
                session.commit()
                results[index] = focus.id
            except Exception as exc:  # pragma: no cover - surfaced below
                session.rollback()
                results[index] = exc

    threads = [threading.Thread(target=call, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert all(not isinstance(result, Exception) for result in results), results
    assert results[0] == results[1], results
    assert _running_session_count(engine, user_id, task_id) == 1

    with factory() as session:
        session.execute(delete(User).where(User.id == user_id))
        session.commit()
