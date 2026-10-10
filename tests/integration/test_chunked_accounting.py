"""Nearest-slot plan-item accounting for chunked tasks (external review #8).

A long task is split into several plan items (planner §3.1 blocks of at most
90 minutes). One focus session must land on exactly ONE item — the chunk
whose slot is nearest the session moment — instead of completing every chunk
and stacking the whole session's minutes on each, which N-counted a single
session in ``plan_item_ratios`` (the estimate-learning sampler reads
actual/planned per item).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest

from backend.models.enums import PlanItemStatus, PlanStatus
from backend.models.plan import Plan, PlanItem
from backend.services.estimates import plan_item_ratios
from tests.fixtures.payloads import task_payload

pytestmark = pytest.mark.integration


def _confirmed_plan_with_chunks(
    db_session, user_id: uuid.UUID, task_id: uuid.UUID, slots: list[timedelta | None]
) -> list[PlanItem]:
    """A CONFIRMED plan with one chunk per slot offset from now (None = slot-less)."""

    now = datetime.now(UTC)
    items = [
        PlanItem(
            task_id=task_id,
            title=f"chunk {index}",
            order_index=index,
            planned_start=None if offset is None else now + offset,
            planned_end=None if offset is None else now + offset + timedelta(minutes=90),
            planned_minutes=90,
        )
        for index, offset in enumerate(slots)
    ]
    db_session.add(
        Plan(
            user_id=user_id,
            title="拆块计划",
            status=PlanStatus.CONFIRMED,
            basis={},
            permission_level=2,
            generated_by="manual",
            confirmed_at=now,
            items=items,
        )
    )
    db_session.flush()
    return items


def _chunks(db_session, chunks: list[PlanItem]) -> Iterator[PlanItem]:
    for chunk in chunks:
        yield db_session.get(PlanItem, chunk.id)


def _run_focus(client, auth_headers, task_id: str, minutes: int) -> None:
    started = client.post("/v1/focus-sessions", json={"task_id": task_id}, headers=auth_headers)
    assert started.status_code == 201, started.text
    completed = client.patch(
        f"/v1/focus-sessions/{started.json()['id']}",
        json={"status": "completed", "actual_minutes": minutes},
        headers=auth_headers,
    )
    assert completed.status_code == 200, completed.text


def test_one_session_lands_on_the_nearest_chunk_only(client, auth_headers, db_session) -> None:
    me = client.get("/v1/auth/me", headers=auth_headers).json()
    task = client.post(
        "/v1/tasks",
        json=task_payload(title="线性代数大作业", estimated_minutes=200),
        headers=auth_headers,
    ).json()
    chunks = _confirmed_plan_with_chunks(
        db_session,
        uuid.UUID(me["id"]),
        uuid.UUID(task["id"]),
        slots=[timedelta(hours=-2), timedelta(minutes=-5), timedelta(hours=3)],
    )

    _run_focus(client, auth_headers, task["id"], minutes=50)

    past, near, future = _chunks(db_session, chunks)
    assert near.status == PlanItemStatus.COMPLETED
    assert near.actual_minutes == 50
    # The un-worked chunks keep their honest state: no retroactive
    # completion, no copied duration — the old loop did both.
    assert past.status == PlanItemStatus.PENDING and past.actual_minutes is None
    assert future.status == PlanItemStatus.PENDING and future.actual_minutes is None
    # Task-side accounting is unchanged: one session, one accumulation.
    assert (
        client.get(f"/v1/tasks/{task['id']}", headers=auth_headers).json()[
            "actual_duration_minutes"
        ]
        == 50
    )


def test_consecutive_sessions_walk_pending_chunks(client, auth_headers, db_session) -> None:
    me = client.get("/v1/auth/me", headers=auth_headers).json()
    task = client.post(
        "/v1/tasks",
        json=task_payload(title="大物实验报告", estimated_minutes=180),
        headers=auth_headers,
    ).json()
    chunks = _confirmed_plan_with_chunks(
        db_session,
        uuid.UUID(me["id"]),
        uuid.UUID(task["id"]),
        slots=[timedelta(minutes=-10), timedelta(hours=2)],
    )

    _run_focus(client, auth_headers, task["id"], minutes=40)
    _run_focus(client, auth_headers, task["id"], minutes=35)

    first, second = _chunks(db_session, chunks)
    # Session 2 (completed=False for an already-done task) attributes to the
    # nearest PENDING chunk instead of stacking a second session on the first.
    assert first.status == PlanItemStatus.COMPLETED and first.actual_minutes == 40
    assert second.status == PlanItemStatus.COMPLETED and second.actual_minutes == 35
    assert (
        client.get(f"/v1/tasks/{task['id']}", headers=auth_headers).json()[
            "actual_duration_minutes"
        ]
        == 75
    )


def test_sessions_accumulate_when_all_chunks_are_done(client, auth_headers, db_session) -> None:
    me = client.get("/v1/auth/me", headers=auth_headers).json()
    task = client.post(
        "/v1/tasks",
        json=task_payload(title="单块任务", estimated_minutes=90),
        headers=auth_headers,
    ).json()
    chunks = _confirmed_plan_with_chunks(
        db_session,
        uuid.UUID(me["id"]),
        uuid.UUID(task["id"]),
        slots=[timedelta(minutes=-5)],
    )

    _run_focus(client, auth_headers, task["id"], minutes=30)
    _run_focus(client, auth_headers, task["id"], minutes=20)

    (only,) = _chunks(db_session, chunks)
    # Accumulation semantics are preserved for the single-chunk case: the
    # item mirrors the task's total, and the ratio sampler sees ONE honest
    # sample instead of two stacked ones.
    assert only.status == PlanItemStatus.COMPLETED and only.actual_minutes == 50
    assert plan_item_ratios(db_session, user_id=uuid.UUID(me["id"])) == [50 / 90]


def test_slotless_chunks_attribute_deterministically(client, auth_headers, db_session) -> None:
    me = client.get("/v1/auth/me", headers=auth_headers).json()
    task = client.post(
        "/v1/tasks",
        json=task_payload(title="无槽位手排", estimated_minutes=120),
        headers=auth_headers,
    ).json()
    chunks = _confirmed_plan_with_chunks(
        db_session,
        uuid.UUID(me["id"]),
        uuid.UUID(task["id"]),
        slots=[None, None],
    )

    _run_focus(client, auth_headers, task["id"], minutes=25)

    first, second = _chunks(db_session, chunks)
    # Slot-less items (manual plans) fall back to creation order — still
    # exactly one chunk per session, never both.
    assert first.status == PlanItemStatus.COMPLETED and first.actual_minutes == 25
    assert second.status == PlanItemStatus.PENDING and second.actual_minutes is None
