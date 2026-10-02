"""Memory retrieval floor (D-031 §5) + decision-use telemetry (§8a.2).

The retrieval path is the shared candidate source for decision contexts:
live rows only, REJECTED filtered, confidence floored at 0.3 (raisable,
never bypassable). The telemetry tests pin the planner wiring: a memory
row's ``use_count`` moves exactly when a generated plan's basis cites its
estimate — once per plan (batch dedup), never for candidate reads.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.enums import MemoryCorrectionStatus, MemoryKind, TaskStatus
from backend.models.memory import Memory
from backend.models.task import Task
from backend.models.user import User
from backend.services.memory_retrieval import (
    RETRIEVAL_CONFIDENCE_FLOOR,
    record_decision_use,
    retrieve_memories,
)

pytestmark = pytest.mark.integration

_MORNING_START = f"{datetime.now(UTC).astimezone().date()}T10:00:00+08:00"


def _memory(
    user_id: uuid.UUID,
    *,
    content: str,
    confidence: float,
    correction_status: MemoryCorrectionStatus = MemoryCorrectionStatus.UNREVIEWED,
    supersedes_id: uuid.UUID | None = None,
    subject_key: str | None = None,
    kind: MemoryKind | None = None,
    domain: str = "study",
    level: int = 2,
) -> Memory:
    return Memory(
        user_id=user_id,
        level=level,
        domain=domain,
        content=content,
        confidence=confidence,
        correction_status=correction_status,
        supersedes_id=supersedes_id,
        subject_key=subject_key,
        kind=kind,
    )


def _user(db_session: Session) -> User:
    user = db_session.scalar(select(User).order_by(User.created_at.desc()))
    assert user is not None
    return user


def test_retrieval_returns_only_live_non_rejected_rows(client, auth_headers, db_session) -> None:
    user = _user(db_session)
    passing = _memory(user.id, content="live unreviewed", confidence=0.5)
    confirmed = _memory(
        user.id,
        content="live confirmed",
        confidence=0.9,
        correction_status=MemoryCorrectionStatus.CONFIRMED,
    )
    low = _memory(user.id, content="below floor", confidence=RETRIEVAL_CONFIDENCE_FLOOR - 0.01)
    rejected = _memory(
        user.id,
        content="rejected stays hidden",
        confidence=1.0,
        correction_status=MemoryCorrectionStatus.REJECTED,
    )
    history = _memory(
        user.id,
        content="superseded history",
        confidence=1.0,
        supersedes_id=uuid.uuid4(),  # any non-null pointer marks it non-live
    )
    db_session.add_all([passing, confirmed, low, rejected, history])
    db_session.flush()

    # Set comparison: same-transaction rows can share updated_at, so the
    # id tiebreak is random by design (ordering itself is pinned below).
    contents = {m.content for m in retrieve_memories(db_session, user_id=user.id)}
    assert contents == {"live confirmed", "live unreviewed"}


def test_retrieval_floor_raisable_but_not_bypassable(client, auth_headers, db_session) -> None:
    user = _user(db_session)
    rows = {
        0.2: _memory(user.id, content="c02", confidence=0.2),
        0.3: _memory(user.id, content="c03", confidence=0.3),
        0.5: _memory(user.id, content="c05", confidence=0.5),
        0.8: _memory(user.id, content="c08", confidence=0.8),
    }
    db_session.add_all(rows.values())
    db_session.flush()

    def contents_for(min_confidence: float | None) -> set[str]:
        return {
            m.content
            for m in retrieve_memories(db_session, user_id=user.id, min_confidence=min_confidence)
        }

    # Default floor: 0.3 exactly passes, 0.2 does not.
    assert contents_for(None) == {"c03", "c05", "c08"}
    # A caller may raise the floor...
    assert contents_for(0.8) == {"c08"}
    # ...but never bypass it: asking for 0.1 still yields >= 0.3.
    assert contents_for(0.1) == {"c03", "c05", "c08"}
    # The module constant is the frozen D-031 §5 value.
    assert RETRIEVAL_CONFIDENCE_FLOOR == 0.3


def test_retrieval_filters_kind_domain_subject_and_orders(client, auth_headers, db_session) -> None:
    user = _user(db_session)
    base = datetime.now(UTC)
    # Explicit distinct updated_at values: ordering must be deterministic
    # regardless of uuid tiebreaks.
    older = _memory(
        user.id,
        content="older fact",
        confidence=0.6,
        subject_key="estimate:course:older",
        kind=MemoryKind.FACT,
    )
    newer = _memory(
        user.id,
        content="newer episode",
        confidence=0.6,
        kind=MemoryKind.EPISODE,
        domain="time",
        level=1,
    )
    other_key = _memory(
        user.id,
        content="other key",
        confidence=0.6,
        subject_key="estimate_ratio:user",
        kind=MemoryKind.FACT,
    )
    older.updated_at = base
    other_key.updated_at = base + timedelta(minutes=1)
    newer.updated_at = base + timedelta(minutes=2)
    db_session.add_all([older, newer, other_key])
    db_session.flush()

    assert [
        m.content for m in retrieve_memories(db_session, user_id=user.id, kinds=[MemoryKind.FACT])
    ] == ["other key", "older fact"]
    assert [
        m.content for m in retrieve_memories(db_session, user_id=user.id, domains=["time"])
    ] == ["newer episode"]
    assert [
        m.content
        for m in retrieve_memories(db_session, user_id=user.id, subject_key="estimate:course:older")
    ] == ["older fact"]
    assert [m.content for m in retrieve_memories(db_session, user_id=user.id, level=1)] == [
        "newer episode"
    ]
    # Newest first, truncated by limit.
    assert [m.content for m in retrieve_memories(db_session, user_id=user.id, limit=2)] == [
        "newer episode",
        "other key",
    ]


def test_retrieval_is_candidate_only_and_never_bumps_use_count(
    client, auth_headers, db_session
) -> None:
    """§8a.2: candidate retrieval must not count; only an explicit decision
    record (``record_decision_use``) does."""

    user = _user(db_session)
    row = _memory(user.id, content="candidate", confidence=0.5)
    db_session.add(row)
    db_session.flush()

    retrieve_memories(db_session, user_id=user.id)
    db_session.flush()
    assert row.use_count == 0
    assert row.last_used_at is None

    record_decision_use(db_session, [row.id, row.id])  # duplicate id dedups
    db_session.flush()
    db_session.refresh(row)
    assert row.use_count == 1
    assert row.last_used_at is not None


def test_generated_plan_records_estimate_decision_use(client, auth_headers, db_session) -> None:
    """The first frozen write point of ``use_count`` (§8a.2): the planner's
    L2 estimate rows entering a generated plan's basis. Once per row per
    plan — three tasks of one course read the row three times and still
    count one decision — and once more per regeneration (a new decision)."""

    user = _user(db_session)
    course = f"检索课-{uuid.uuid4().hex[:6]}"
    course_row = Memory(
        user_id=user.id,
        level=2,
        domain="study",
        content=f"{course} 估时",
        confidence=0.2,  # min(0.9, 2/10) — the sample-count gate, NOT the floor
        correction_status=MemoryCorrectionStatus.CONFIRMED,
        subject_key=f"estimate:course:{course}",
        kind=MemoryKind.FACT,
        source={"value": 75, "sample_count": 2},
    )
    db_session.add(course_row)
    tasks = [
        Task(
            user_id=user.id,
            title=f"{course}：作业{i}",
            source="onethu",
            status=TaskStatus.TODO,
            deadline=datetime.now(UTC) + timedelta(days=1),
            extra={"course_name": course},
        )
        for i in (1, 2, 3)
    ]
    db_session.add_all(tasks)
    db_session.flush()

    first = client.post(
        "/v1/plans/generate", json={"start_at": _MORNING_START}, headers=auth_headers
    )
    assert first.status_code == 201, first.text
    placed = [i for i in first.json()["items"] if i["basis"]["estimate_source"] == "learned:course"]
    assert len(placed) == 3, "all three course tasks should carry the learned estimate"

    db_session.refresh(course_row)
    assert course_row.use_count == 1
    assert course_row.last_used_at is not None

    second = client.post(
        "/v1/plans/generate", json={"start_at": _MORNING_START}, headers=auth_headers
    )
    assert second.status_code == 201, second.text
    db_session.refresh(course_row)
    assert course_row.use_count == 2


def test_rejected_or_unused_estimate_rows_never_enter_decisions(
    client, auth_headers, db_session
) -> None:
    user = _user(db_session)
    course_used = f"用上的课-{uuid.uuid4().hex[:6]}"
    course_rejected = f"被拒的课-{uuid.uuid4().hex[:6]}"
    used_row = Memory(
        user_id=user.id,
        level=2,
        domain="study",
        content=f"{course_used} 估时",
        confidence=0.2,
        correction_status=MemoryCorrectionStatus.CONFIRMED,
        subject_key=f"estimate:course:{course_used}",
        kind=MemoryKind.FACT,
        source={"value": 45, "sample_count": 2},
    )
    rejected_row = Memory(
        user_id=user.id,
        level=2,
        domain="study",
        content=f"{course_rejected} 估时",
        confidence=0.9,
        correction_status=MemoryCorrectionStatus.REJECTED,
        subject_key=f"estimate:course:{course_rejected}",
        kind=MemoryKind.FACT,
        source={"value": 999, "sample_count": 5},
    )
    db_session.add_all([used_row, rejected_row])
    db_session.flush()

    explicit = Task(
        user_id=user.id,
        title=f"{course_used}：手填估时",
        source="onethu",
        status=TaskStatus.TODO,
        estimated_duration_minutes=30,  # user estimate: the ladder never reads memory
        extra={"course_name": course_used},
    )
    rejected = Task(
        user_id=user.id,
        title=f"{course_rejected}：作业一",
        source="onethu",
        status=TaskStatus.TODO,
        deadline=datetime.now(UTC) + timedelta(days=1),
        extra={"course_name": course_rejected},
    )
    db_session.add_all([explicit, rejected])
    db_session.flush()

    response = client.post(
        "/v1/plans/generate", json={"start_at": _MORNING_START}, headers=auth_headers
    )
    assert response.status_code == 201, response.text
    basis = {i["title"]: i["basis"] for i in response.json()["items"]}
    assert basis[f"{course_rejected}：作业一"]["estimate_source"] == "default"

    db_session.refresh(used_row)
    db_session.refresh(rejected_row)
    # The used course's row was retrieved for ranking but its estimate never
    # landed in a basis (the user estimate won) — candidate reads don't count.
    assert used_row.use_count == 0
    assert rejected_row.use_count == 0
