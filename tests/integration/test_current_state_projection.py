"""CurrentState projection semantics tests (DECISIONS.md D-027).

Covers the frozen computation for ``available_minutes`` (override first,
otherwise day-remaining minus today's schedule overlap minus the current
task's remaining estimate) and the derived context label priority chain
(override > in-class > focusing > task > upcoming class > idle > None).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from backend.config import get_settings
from backend.models.enums import FocusSessionStatus
from backend.models.event import Event
from backend.models.focus_session import FocusSession
from backend.models.task import Task
from backend.models.user import User
from backend.services.current_state import recompute_current_state

pytestmark = pytest.mark.integration

_TZ = ZoneInfo(get_settings().default_timezone)


def _seed_user(db_session) -> User:
    user = User(
        email=f"proj-{uuid.uuid4().hex[:10]}@example.com",
        display_name="Projection User",
        hashed_password="not-a-real-hash",
    )
    db_session.add(user)
    db_session.flush()
    return user


def _today_local(now: datetime) -> date:
    return now.astimezone(_TZ).date()


def _schedule_event(
    db_session,
    user: User,
    *,
    upstream_id: str,
    course: str,
    day: date,
    start: str,
    end: str,
    location: str | None = "六教",
    timestamp: datetime | None = None,
    semantic_version: str = "1",
) -> Event:
    event = Event(
        user_id=user.id,
        type="time.schedule.entry",
        timestamp=timestamp or datetime.now(UTC),
        source="campus",
        data={
            "course_name": course,
            "date": day.isoformat(),
            "start_time": start,
            "end_time": end,
            "location": location,
        },
        context={"domain": "time"},
        provenance={
            "connector": "onethu",
            "upstream_id": upstream_id,
            "semantic_version": semantic_version,
        },
        dedupe_key=f"campus:{upstream_id}:{semantic_version}",
    )
    db_session.add(event)
    db_session.flush()
    return event


@pytest.fixture
def fixed_now(monkeypatch) -> datetime:
    """Pin the projection's clock to 13:00 local today for determinism.

    Class-coverage assertions must not depend on the wall-clock hour the suite
    happens to run at.
    """

    pinned = datetime.combine(_today_local(datetime.now(UTC)), time(13, 0), tzinfo=_TZ)
    now = pinned.astimezone(UTC)
    monkeypatch.setattr("backend.services.current_state.utcnow", lambda: now)
    return now


def test_no_data_derives_day_remaining_and_none_context(db_session, fixed_now) -> None:
    user = _seed_user(db_session)
    read = recompute_current_state(db_session, user.id)

    timezone = ZoneInfo(get_settings().default_timezone)
    day_end = datetime.combine(
        fixed_now.astimezone(timezone).date() + timedelta(days=1), time(0, 0), tzinfo=timezone
    ).astimezone(UTC)
    expected_remaining = int((day_end - fixed_now).total_seconds() // 60)
    assert read.available_minutes == expected_remaining
    assert read.context_label is None
    assert read.recent_state["available_minutes_breakdown"]["source"] == "derived"


def test_in_class_context_and_deduction(db_session, fixed_now) -> None:
    user = _seed_user(db_session)
    today = _today_local(fixed_now)
    # "Now" is pinned to 13:00 local; the class runs 12:00-15:00 so the
    # remaining overlap is exactly 120 minutes.
    _schedule_event(
        db_session,
        user,
        upstream_id="course-1",
        course="线性代数",
        day=today,
        start="12:00",
        end="15:00",
    )

    task = Task(
        user_id=user.id,
        title="作业",
        status="IN_PROGRESS",
        estimated_duration_minutes=60,
        actual_duration_minutes=20,
    )
    db_session.add(task)
    db_session.flush()

    read = recompute_current_state(db_session, user.id)
    breakdown = read.recent_state["available_minutes_breakdown"]
    assert read.context_label == "在课：线性代数@六教"
    assert breakdown["class_minutes"] == 120
    assert breakdown["current_task_remaining_minutes"] == 40
    assert read.available_minutes == max(
        0, breakdown["day_remaining_minutes"] - breakdown["class_minutes"] - 40
    )


def test_upcoming_class_label(db_session, fixed_now) -> None:
    user = _seed_user(db_session)
    today = _today_local(fixed_now)
    _schedule_event(
        db_session,
        user,
        upstream_id="course-2",
        course="大学物理",
        day=today,
        start="13:10",
        end="14:10",
        location=None,
    )

    read = recompute_current_state(db_session, user.id)
    assert read.context_label is not None
    assert read.context_label.startswith("即将上课：大学物理（")


def test_overrides_win(db_session) -> None:
    user = _seed_user(db_session)
    # Simulate the PATCH path: override label + override minutes.
    from backend.services.current_state import get_or_create_state

    row = get_or_create_state(db_session, user.id)
    row.current_context = {"label": "自定义上下文"}
    row.available_minutes = 42
    db_session.flush()

    read = recompute_current_state(db_session, user.id)
    assert read.context_label == "自定义上下文"
    assert read.available_minutes == 42
    assert read.recent_state["available_minutes_breakdown"]["source"] == "override"


def test_latest_revision_wins_per_upstream(db_session) -> None:
    user = _seed_user(db_session)
    today = _today_local(datetime.now(UTC))
    now = datetime.now(UTC)
    # Revision 1: morning class. Revision 2 (newer timestamp): moved to a
    # different day entirely — the old morning slot must stop counting.
    _schedule_event(
        db_session,
        user,
        upstream_id="course-3",
        course="数据结构",
        day=today,
        start="06:00",
        end="07:00",
        timestamp=now - timedelta(days=1),
    )
    _schedule_event(
        db_session,
        user,
        upstream_id="course-3",
        course="数据结构",
        day=today + timedelta(days=30),
        start="06:00",
        end="07:00",
        timestamp=now,
        semantic_version="2",
    )

    read = recompute_current_state(db_session, user.id)
    assert read.recent_state["available_minutes_breakdown"]["class_minutes"] == 0


def test_focus_session_beats_in_progress_task(db_session) -> None:
    user = _seed_user(db_session)
    task = Task(
        user_id=user.id,
        title="专注的任务",
        status="IN_PROGRESS",
    )
    db_session.add(task)
    db_session.flush()
    db_session.add(
        FocusSession(
            user_id=user.id,
            task_id=task.id,
            status=FocusSessionStatus.RUNNING,
            started_at=datetime.now(UTC),
        )
    )
    db_session.flush()

    read = recompute_current_state(db_session, user.id)
    assert read.context_label == "专注中：专注的任务"


def test_idle_when_pending_tasks_exist(db_session) -> None:
    user = _seed_user(db_session)
    db_session.add(Task(user_id=user.id, title="待办", status="TODO"))
    db_session.flush()

    read = recompute_current_state(db_session, user.id)
    assert read.context_label == "空闲"


def test_client_view_serves_effective_label(client, auth_headers, auth_factory) -> None:
    """The frozen client contract's `context` reflects the effective label."""

    # Override flows through the public PATCH endpoint.
    response = client.patch(
        "/v1/current-state",
        json={"current_context": {"label": "联调上下文"}},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["context"] == "联调上下文"

    # A different user without an override gets the derived label through the
    # same contract field (override has no clearing path in M1, so use a
    # separate identity rather than trying to unset it).
    fresh = auth_factory()
    task = client.post("/v1/tasks", json={"title": "派生上下文任务"}, headers=fresh)
    assert task.status_code == 201, task.text
    state = client.get("/v1/current-state", headers=fresh)
    assert state.status_code == 200
    assert state.json()["context"] == "空闲"
    assert isinstance(state.json()["available_minutes"], int)
