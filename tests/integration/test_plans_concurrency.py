"""Concurrency tests for ``/v1/plans/today`` idempotency (DECISIONS.md D-019).

``test_plans.py`` proves sequential idempotency, but it shares one session and
cannot catch the read-then-insert race. These tests use independent database
connections (the real production shape: one connection per request) and a
barrier so both callers start from "no plan" before either commits.
"""

from __future__ import annotations

import threading
import uuid

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from backend.models.enums import PlanStatus, TaskStatus
from backend.models.plan import Plan
from backend.models.task import Task
from backend.models.user import User
from backend.services.planner import resolve_today_plan

pytestmark = pytest.mark.integration


def _seed_user(engine) -> uuid.UUID:
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        user = User(
            email=f"race-{uuid.uuid4().hex[:10]}@example.com",
            display_name="Race User",
            hashed_password="not-a-real-hash",
        )
        session.add(user)
        session.flush()
        session.add(Task(user_id=user.id, title="HW", status=TaskStatus.TODO))
        session.commit()
        return user.id


def _open_plan_count(engine, user_id: uuid.UUID) -> int:
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        count = session.scalar(
            select(func.count())
            .select_from(Plan)
            .where(
                Plan.user_id == user_id,
                Plan.status.in_([PlanStatus.DRAFT, PlanStatus.PENDING_CONFIRMATION]),
            )
        )
    return int(count or 0)


def test_concurrent_today_requests_return_one_plan(engine) -> None:
    # Late-night window (same class as the test_plans guards): an empty
    # first draft is not reusable under D7, so the second resolve would
    # legitimately produce a different plan near local midnight.
    from datetime import datetime as _dt, timedelta
    from zoneinfo import ZoneInfo as _ZI

    from backend.config import get_settings as _gs
    _tz = _ZI(_gs().default_timezone)
    _now = _dt.now(_tz)
    _mid = (_now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    if (_mid - _now).total_seconds() // 60 < 130:
        import pytest as _pytest
        _pytest.skip("late-night window: empty-draft churn breaks reuse")
    user_id = _seed_user(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    barrier = threading.Barrier(2)
    results: list[object] = [None, None]

    def call(index: int) -> None:
        with factory() as session:
            try:
                barrier.wait(timeout=10)
                plan = resolve_today_plan(session, user_id)
                session.commit()
                results[index] = plan.id
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
    assert _open_plan_count(engine, user_id) == 1

    with factory() as session:
        session.execute(delete(User).where(User.id == user_id))
        session.commit()


def test_concurrent_today_requests_stay_isolated_per_user(engine) -> None:
    alice = _seed_user(engine)
    bob = _seed_user(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    barrier = threading.Barrier(2)
    results: dict[uuid.UUID, object] = {}

    def call(user_id: uuid.UUID) -> None:
        session: Session
        with factory() as session:
            try:
                barrier.wait(timeout=10)
                plan = resolve_today_plan(session, user_id)
                session.commit()
                results[user_id] = plan.id
            except Exception as exc:  # pragma: no cover - surfaced below
                session.rollback()
                results[user_id] = exc

    threads = [threading.Thread(target=call, args=(user_id,)) for user_id in (alice, bob)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert set(results) == {alice, bob}
    assert all(not isinstance(result, Exception) for result in results.values()), results
    assert results[alice] != results[bob]
    assert _open_plan_count(engine, alice) == 1
    assert _open_plan_count(engine, bob) == 1

    with factory() as session:
        session.execute(delete(User).where(User.id.in_([alice, bob])))
        session.commit()
