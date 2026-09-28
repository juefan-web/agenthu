"""Concurrency tests for CurrentState first-request creation (merge-1 D5).

``get_or_create_state`` used to be a lock-free select-then-insert: concurrent
first requests both observed "no state", the loser hit
``uq_current_states_user`` and the API returned a 500 (reproduced 2/5 with 5
concurrent requests in the merge-1 manual test). These tests use independent
database connections and a barrier so all callers start from "no state".
"""

from __future__ import annotations

import threading
import uuid

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from backend.models.current_state import CurrentState
from backend.models.user import User
from backend.services.current_state import recompute_current_state

pytestmark = pytest.mark.integration


def _seed_user(engine) -> uuid.UUID:
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        user = User(
            email=f"state-race-{uuid.uuid4().hex[:10]}@example.com",
            display_name="State Race User",
            hashed_password="not-a-real-hash",
        )
        session.add(user)
        session.commit()
        return user.id


def _state_count(engine, user_id: uuid.UUID) -> int:
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        count = session.scalar(
            select(func.count()).select_from(CurrentState).where(CurrentState.user_id == user_id)
        )
    return int(count or 0)


def test_concurrent_first_recompute_creates_exactly_one_state(engine) -> None:
    user_id = _seed_user(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    workers = 5
    barrier = threading.Barrier(workers)
    results: list[object] = [None] * workers

    def call(index: int) -> None:
        session: Session
        with factory() as session:
            try:
                barrier.wait(timeout=10)
                state = recompute_current_state(session, user_id)
                session.commit()
                results[index] = state.version
            except Exception as exc:  # surfaced below
                session.rollback()
                results[index] = exc

    threads = [threading.Thread(target=call, args=(index,)) for index in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert all(not isinstance(result, Exception) for result in results), results
    # The race must leave exactly one row for the user, not a 500.
    assert _state_count(engine, user_id) == 1

    with factory() as session:
        session.execute(delete(User).where(User.id == user_id))
        session.commit()


def test_sequential_first_recompute_still_creates_state(engine) -> None:
    user_id = _seed_user(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        state = recompute_current_state(session, user_id)
        session.commit()
        assert state.version >= 1
    assert _state_count(engine, user_id) == 1

    with factory() as session:
        session.execute(delete(User).where(User.id == user_id))
        session.commit()
