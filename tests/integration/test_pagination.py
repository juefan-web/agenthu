"""Keyset pagination contract (D-029).

tasks and events list endpoints: opaque cursors over the actual sort key
(tasks: deadline nulls-last, created_at desc, id desc; events: timestamp
desc, id desc), ``next_cursor``/``X-Next-Cursor`` absent on the last page,
``total`` skipped on cursor pages, and cursor+offset rejected with 422.
Seeds use fixed timestamps (including ties) so the page walk is exact.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.orm import Session

from backend.models.enums import TaskStatus
from backend.models.task import Task

pytestmark = pytest.mark.integration

_CLIENT_ORIGIN = "http://localhost:5173"


def _task_rows(db_session: Session, user_id: uuid.UUID) -> list[Task]:
    """7 tasks: three at D1 (distinct created_at), two at D2 sharing one
    created_at (exercises the id tiebreak), two with no deadline (nulls
    last). Insert order is deliberately unrelated to the final order."""

    base = datetime(2026, 10, 1, 8, 0, 0, tzinfo=UTC)
    d1 = base + timedelta(days=3)
    d2 = base + timedelta(days=4)
    specs = [
        ("t1", d1, base + timedelta(minutes=1)),
        ("t2", d1, base + timedelta(minutes=3)),
        ("t3", d1, base + timedelta(minutes=2)),
        ("t4", d2, base + timedelta(minutes=5)),
        ("t5", d2, base + timedelta(minutes=5)),  # same (deadline, created_at)
        ("t6", None, base + timedelta(minutes=6)),
        ("t7", None, base + timedelta(minutes=7)),
    ]
    rows = [
        Task(
            user_id=user_id,
            title=name,
            source="manual",
            status=TaskStatus.TODO,
            deadline=deadline,
            created_at=created_at,
        )
        for name, deadline, created_at in specs
    ]
    db_session.add_all(rows)
    db_session.flush()
    return rows


def _expected_task_order(rows: list[Task]) -> list[str]:
    """deadline ASC (nulls last), then created_at DESC, id DESC."""

    def sort_key(task: Task) -> tuple[int, Any, float, int]:
        return (
            1 if task.deadline is None else 0,
            task.deadline or datetime.min.replace(tzinfo=UTC),
            -task.created_at.timestamp(),
            -task.id.int,
        )

    return [task.title for task in sorted(rows, key=sort_key)]


def test_tasks_keyset_walk_is_exact(client, auth_headers, db_session) -> None:
    user_id = uuid.UUID(client.get("/v1/auth/me", headers=auth_headers).json()["id"])
    rows = _task_rows(db_session, user_id)
    expected = _expected_task_order(rows)

    seen: list[str] = []
    cursors = 0
    response = client.get("/v1/tasks?limit=3", headers=auth_headers)
    while True:
        assert response.status_code == 200, response.text
        seen.extend(item["title"] for item in response.json())
        header = response.headers.get("X-Next-Cursor")
        if header is None:
            break
        cursors += 1
        response = client.get(f"/v1/tasks?limit=3&cursor={header}", headers=auth_headers)

    assert seen == expected, "keyset walk must reproduce the full order exactly"
    assert cursors == 2, "7 rows / limit 3 -> exactly two next-page cursors"
    # Cursor pages on tasks are bare arrays — no body shape change.
    assert isinstance(response.json(), list)


def test_tasks_last_page_has_no_cursor_header(client, auth_headers, db_session) -> None:
    user_id = uuid.UUID(client.get("/v1/auth/me", headers=auth_headers).json()["id"])
    _task_rows(db_session, user_id)
    response = client.get("/v1/tasks?limit=200", headers=auth_headers)
    assert response.status_code == 200
    assert "X-Next-Cursor" not in response.headers


def test_tasks_cursor_and_offset_are_rejected(client, auth_headers, db_session) -> None:
    user_id = uuid.UUID(client.get("/v1/auth/me", headers=auth_headers).json()["id"])
    _task_rows(db_session, user_id)
    first = client.get("/v1/tasks?limit=3", headers=auth_headers)
    cursor = first.headers["X-Next-Cursor"]
    rejected = client.get(f"/v1/tasks?limit=3&cursor={cursor}&offset=0", headers=auth_headers)
    assert rejected.status_code == 422


def test_tasks_invalid_cursor_is_rejected(client, auth_headers) -> None:
    response = client.get("/v1/tasks?limit=3&cursor=not-a-cursor", headers=auth_headers)
    assert response.status_code == 422


def test_tasks_offset_path_still_works_without_header(client, auth_headers, db_session) -> None:
    """The deprecated offset path keeps today's behavior (and mints no
    cursor header, since an offset page has no keyset anchor)."""

    user_id = uuid.UUID(client.get("/v1/auth/me", headers=auth_headers).json()["id"])
    rows = _task_rows(db_session, user_id)
    expected = _expected_task_order(rows)

    response = client.get("/v1/tasks?limit=2&offset=2", headers=auth_headers)
    assert response.status_code == 200
    assert "X-Next-Cursor" not in response.headers
    assert [item["title"] for item in response.json()] == expected[2:4]


def test_tasks_cors_exposes_cursor_header(client, auth_headers, db_session) -> None:
    user_id = uuid.UUID(client.get("/v1/auth/me", headers=auth_headers).json()["id"])
    _task_rows(db_session, user_id)
    response = client.get("/v1/tasks?limit=3", headers={"Origin": _CLIENT_ORIGIN})
    exposed = response.headers.get("Access-Control-Expose-Headers", "")
    assert "X-Next-Cursor" in exposed


def test_events_keyset_walk_is_exact_and_skips_total(client, auth_headers, db_session) -> None:
    from backend.models.event import Event

    user_id = uuid.UUID(client.get("/v1/auth/me", headers=auth_headers).json()["id"])
    stamp = datetime(2026, 10, 2, 12, 0, 0, tzinfo=UTC)  # one shared timestamp: id tiebreak
    rows = [
        Event(
            user_id=user_id,
            type="course.created",
            timestamp=stamp,
            source="manual",
            data={"course": f"C{i}"},
            context={},
            provenance={"fixture": "pagination"},
            created_at=stamp,
        )
        for i in range(5)
    ]
    db_session.add_all(rows)
    db_session.flush()
    expected_ids = [str(e.id) for e in sorted(rows, key=lambda e: e.id, reverse=True)]

    seen: list[str] = []
    first = client.get("/v1/events?limit=2", headers=auth_headers)
    assert first.status_code == 200
    # First page keeps today's semantics: total present, cursor minted.
    assert first.json()["total"] == 5
    assert first.json()["next_cursor"] is not None

    response = first
    while True:
        seen.extend(item["id"] for item in response.json()["items"])
        cursor = response.json()["next_cursor"]
        if cursor is None:
            break
        response = client.get(f"/v1/events?limit=2&cursor={cursor}", headers=auth_headers)
        assert response.status_code == 200
        # Cursor pages skip the COUNT (D-029).
        assert response.json()["total"] is None

    assert seen == expected_ids, "timestamp tie must be broken by id, no drops or dupes"


def test_events_cursor_and_offset_are_rejected(client, auth_headers) -> None:
    rejected = client.get("/v1/events?limit=2&cursor=abc&offset=0", headers=auth_headers)
    assert rejected.status_code == 422


def test_events_offset_path_keeps_total_and_no_cursor(client, auth_headers, db_session) -> None:
    from backend.models.event import Event

    user_id = uuid.UUID(client.get("/v1/auth/me", headers=auth_headers).json()["id"])
    stamp = datetime(2026, 10, 2, 12, 0, 0, tzinfo=UTC)
    db_session.add_all(
        [
            Event(
                user_id=user_id,
                type="course.created",
                timestamp=stamp,
                source="manual",
                data={"course": f"C{i}"},
                context={},
                provenance={"fixture": "pagination"},
                created_at=stamp,
            )
            for i in range(4)
        ]
    )
    db_session.flush()

    response = client.get("/v1/events?limit=2&offset=1", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 4
    assert body["next_cursor"] is None
    assert len(body["items"]) == 2
