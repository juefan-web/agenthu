"""Assignment-event -> Task derivation tests (M1-1, DECISIONS.md D-028)."""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import sessionmaker

from backend.models.task import Task
from backend.models.user import User
from backend.schemas.event import EventCreate
from backend.services.events import create_event

pytestmark = pytest.mark.integration


def _assignment_event(
    *,
    assignment_id: str = "hw-1",
    event_type: str = "study.assignment.discovered",
    title: str = "作业一",
    deadline: str | None = None,
    submitted: bool = False,
    graded: bool = False,
    semantic_version: str = "1",
    source: str = "onethu",
) -> EventCreate:
    data: dict[str, object] = {
        "assignment_id": assignment_id,
        "course_id": "course-1",
        "title": title,
        "content": "完成课后习题 1-3",
        "publish_time": "2026-09-20T08:00:00+08:00",
        "deadline": deadline,
        "late_deadline": None,
        "submitted": submitted,
        "graded": graded,
        "url": "https://learn.tsinghua.edu.cn/a",
    }
    return EventCreate(
        type=event_type,
        source=source,
        data=data,
        context={"domain": "study", "course_id": "course-1"},
        provenance={
            "connector": "onethu",
            "connector_version": "test",
            "upstream_id": f"assignment:{assignment_id}",
            "semantic_version": semantic_version,
            "fetched_at": "2026-09-29T10:00:00+00:00",
        },
    )


def _derived_count(db_session, user_id) -> int:
    return int(
        db_session.scalar(
            select(func.count())
            .select_from(Task)
            .where(Task.user_id == user_id, Task.source_upstream_id.is_not(None))
        )
        or 0
    )


def _me_id(client, auth_headers) -> uuid.UUID:
    return uuid.UUID(client.get("/v1/auth/me", headers=auth_headers).json()["id"])


def test_discovered_creates_task_with_tzaware_deadline(db_session, client, auth_headers) -> None:
    from backend.schemas.client_contract import EventEnvelope, EventProvenance
    from backend.services.events import ingest_event_batch

    user_id = _me_id(client, auth_headers)
    deadline = (datetime.now(UTC) + timedelta(days=7)).isoformat()
    envelope = EventEnvelope(
        client_event_id=f"onethu:assignment:hw-1:1-{uuid.uuid4().hex[:6]}",
        type="study.assignment.discovered",
        occurred_at=datetime.now(UTC),
        source="onethu",
        data={
            "assignment_id": "hw-1",
            "course_id": "course-1",
            "title": "作业一",
            "content": "完成课后习题 1-3",
            "deadline": deadline,
            "late_deadline": None,
            "submitted": False,
            "graded": False,
        },
        context={"domain": "study"},
        provenance=EventProvenance(
            connector="onethu",
            connector_version="test",
            upstream_id="assignment:hw-1",
            semantic_version="1",
            fetched_at=datetime.now(UTC),
        ),
    )
    outcome = ingest_event_batch(db_session, user_id=user_id, envelopes=[envelope])
    assert outcome.rejected == [], outcome.rejected

    task = db_session.scalar(select(Task).where(Task.user_id == user_id))
    assert task is not None
    assert task.title == "作业一"
    assert task.source == "onethu"
    assert task.source_upstream_id == "assignment:hw-1"
    assert task.status.value == "TODO"
    assert task.deadline is not None
    assert task.deadline.isoformat() == datetime.fromisoformat(deadline).isoformat()
    assert task.description == "完成课后习题 1-3"


def test_updated_does_not_duplicate_and_refreshes(db_session, client, auth_headers) -> None:
    user_id = _me_id(client, auth_headers)
    first = _assignment_event(deadline="2026-10-10T23:59:59+08:00")
    create_event(db_session, user_id=user_id, payload=first, client_event_id="ce-1")

    second = _assignment_event(
        event_type="study.assignment.updated",
        title="作业一（改期）",
        deadline="2026-10-15T23:59:59+08:00",
        semantic_version="2",
    )
    create_event(db_session, user_id=user_id, payload=second, client_event_id="ce-2")

    assert _derived_count(db_session, user_id) == 1
    task = db_session.scalar(select(Task).where(Task.user_id == user_id))
    assert task is not None
    assert task.title == "作业一（改期）"
    assert task.deadline is not None
    assert task.deadline.hour == 15  # 23:59+08:00 == 15:59 UTC
    assert task.deadline.day == 15


def test_submitted_completes_stickily(db_session, client, auth_headers) -> None:
    user_id = _me_id(client, auth_headers)
    event = _assignment_event(
        event_type="study.assignment.updated",
        submitted=True,
        graded=True,
        semantic_version="3",
    )
    _event, was_created = create_event(
        db_session, user_id=user_id, payload=event, client_event_id="ce-3"
    )
    task = db_session.scalar(select(Task).where(Task.user_id == user_id))
    assert task is not None
    assert task.status.value == "COMPLETED"
    assert task.completed_at is not None

    # Sticky: a later collection that still says submitted must not regress.
    later = _assignment_event(
        event_type="study.assignment.updated",
        submitted=True,
        semantic_version="4",
    )
    create_event(db_session, user_id=user_id, payload=later, client_event_id="ce-4")
    db_session.refresh(task)
    assert task.status.value == "COMPLETED"
    assert task.completed_at is not None
    assert was_created


def test_naive_deadline_rejected_at_both_boundaries(client, auth_headers) -> None:
    naive = "2026-10-10T23:59:59"  # no offset
    # Batch path: envelope lands in `rejected`, nothing ingested.
    batch = client.post(
        "/v1/events/batch",
        json={
            "events": [
                {
                    "client_event_id": f"onethu:naive:{uuid.uuid4().hex[:6]}",
                    "type": "study.assignment.discovered",
                    "occurred_at": "2026-09-29T10:00:00+00:00",
                    "source": "onethu",
                    "data": {
                        "assignment_id": "hw-naive",
                        "title": "naive 作业",
                        "deadline": naive,
                    },
                    "context": {"domain": "study"},
                    "provenance": {
                        "connector": "onethu",
                        "connector_version": "test",
                        "upstream_id": "assignment:hw-naive",
                        "semantic_version": "1",
                        "fetched_at": "2026-09-29T10:00:00+00:00",
                    },
                }
            ]
        },
        headers=auth_headers,
    )
    assert batch.status_code == 200
    body = batch.json()
    assert body["accepted_event_ids"] == []
    assert len(body["rejected"]) == 1
    assert "timezone-aware" in body["rejected"][0]["reason"]

    # Single-event path: 422 with the same reason.
    single = client.post(
        "/v1/events",
        json={
            "type": "study.assignment.discovered",
            "source": "onethu",
            "data": {"assignment_id": "hw-naive-2", "title": "naive", "deadline": naive},
            "provenance": {
                "connector": "onethu",
                "connector_version": "test",
                "upstream_id": "assignment:hw-naive-2",
                "semantic_version": "1",
                "fetched_at": "2026-09-29T10:00:00+00:00",
            },
        },
        headers=auth_headers,
    )
    assert single.status_code == 422
    assert "timezone-aware" in single.json()["error"]["message"]

    # Task API rejects naive deadlines too (D-028 §3b).
    task_response = client.post(
        "/v1/tasks",
        json={"title": "手工任务", "deadline": naive},
        headers=auth_headers,
    )
    assert task_response.status_code == 422


def test_concurrent_same_key_events_create_one_task(engine) -> None:
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        user = User(
            email=f"derive-{uuid.uuid4().hex[:10]}@example.com",
            display_name="Derive Race",
            hashed_password="not-a-real-hash",
        )
        session.add(user)
        session.commit()
        user_id = user.id

    barrier = threading.Barrier(2)
    results: list[object] = [None, None]

    def call(index: int) -> None:
        event = _assignment_event(semantic_version=str(index + 1))
        with factory() as session:
            try:
                barrier.wait(timeout=10)
                create_event(
                    session, user_id=user_id, payload=event, client_event_id=f"race-{index}"
                )
                session.commit()
                results[index] = "ok"
            except Exception as exc:  # surfaced below
                session.rollback()
                results[index] = exc

    threads = [threading.Thread(target=call, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert all(not isinstance(result, Exception) for result in results), results
    with factory() as session:
        count = session.scalar(
            select(func.count())
            .select_from(Task)
            .where(
                Task.user_id == user_id,
                Task.source == "onethu",
                Task.source_upstream_id == "assignment:hw-1",
            )
        )
        assert count == 1
        session.execute(delete(User).where(User.id == user_id))
        session.commit()


def test_real_payload_replay_fixture(db_session, client, auth_headers) -> None:
    """Replay a captured vendor payload shape end-to-end (D-028 acceptance).

    Mirrors the desktop adapter's mapAssignmentEvent output after B's tz fix:
    tz-aware +08:00 ISO deadlines plus `*_raw` provenance fields.
    """

    from datetime import datetime as _dt

    from backend.schemas.client_contract import EventEnvelope, EventProvenance
    from backend.services.events import ingest_event_batch

    user_id = _me_id(client, auth_headers)
    envelopes = [
        EventEnvelope(
            client_event_id=f"onethu:assignment:replay-{i}:{v}",
            type="study.assignment.discovered" if v == "1" else "study.assignment.updated",
            occurred_at=_dt.fromisoformat("2026-09-29T02:00:00+00:00"),
            source="onethu",
            data={
                "assignment_id": f"replay-{i}",
                "course_id": "2025-2026-1-xxx",
                "title": f"数据结构作业{i}",
                "content": "见附件",
                "publish_time": "2026-09-20T08:00:00+08:00",
                "deadline": "2026-10-10T23:59:59+08:00",
                "deadline_raw": "2026-10-10 23:59",
                "late_deadline": "2026-10-13T23:59:59+08:00",
                "late_deadline_raw": "2026-10-13 23:59",
                "submitted": False,
                "graded": False,
                "url": "https://learn.tsinghua.edu.cn/f/i",
            },
            context={"domain": "study", "course_id": "2025-2026-1-xxx"},
            provenance=EventProvenance(
                connector="onethu",
                connector_version="2026.09",
                upstream_id=f"assignment:replay-{i}",
                semantic_version=v,
                fetched_at=_dt.fromisoformat("2026-09-29T02:00:00+00:00"),
            ),
        )
        for i, v in ((1, "1"), (1, "2"), (2, "1"))
    ]

    outcome = ingest_event_batch(db_session, user_id=user_id, envelopes=envelopes)
    assert outcome.rejected == [], outcome.rejected
    assert outcome.duplicates == []

    tasks = db_session.scalars(select(Task).where(Task.user_id == user_id)).all()
    assert len(tasks) == 2
    first = next(t for t in tasks if t.source_upstream_id == "assignment:replay-1")
    assert first.title == "数据结构作业1"
    assert first.deadline is not None
    assert first.deadline.utcoffset() == timedelta(0)
    assert first.deadline.hour == 15  # +08:00 normalized to UTC storage
    assert first.extra["deadline_raw"] == "2026-10-10 23:59"
    assert first.extra["last_derived_event_id"]
