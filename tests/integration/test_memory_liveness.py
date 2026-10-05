"""Memory live-row predicate (D-036 §1, M5 P0-1 slice 1).

The single liveness definition is
``backend.services.memory_lifecycle.live_memory_conditions``: no superseded
pointer AND the validity window covers now. These tests pin the three
behaviors the r1 gap allowed: retired-but-unpointed rows (the FK SET NULL
resurrection shape) must not reach any reader, must not squat a subject_key
against new writes, and client-supplied valid_from/valid_to must be
silently ignored (validity is server-managed, D-036 §6).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.enums import MemoryCorrectionStatus, MemoryKind
from backend.models.memory import Memory
from backend.models.user import User
from backend.services.estimates import live_key_row
from backend.services.event_handlers import _recent_episode_ids
from backend.services.memory_lifecycle import live_memory_conditions, upsert_keyed_memory
from backend.services.memory_retrieval import retrieve_memories

pytestmark = pytest.mark.integration


def _memory(
    user_id: uuid.UUID,
    *,
    subject_key: str | None = None,
    kind: MemoryKind | None = None,
    correction_status: MemoryCorrectionStatus = MemoryCorrectionStatus.UNREVIEWED,
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
    supersedes_id: uuid.UUID | None = None,
    confidence: float = 0.5,
) -> Memory:
    return Memory(
        user_id=user_id,
        level=2,
        domain="study",
        content=f"row-{uuid.uuid4().hex[:8]}",
        confidence=confidence,
        correction_status=correction_status,
        supersedes_id=supersedes_id,
        subject_key=subject_key,
        kind=kind,
        valid_from=valid_from,
        valid_to=valid_to,
    )


def _user(db_session: Session) -> User:
    user = db_session.scalar(select(User).order_by(User.created_at.desc()))
    assert user is not None
    return user


def test_live_predicate_boundaries(client, auth_headers, db_session) -> None:
    """valid_from <= now < valid_to; NULL bounds are unbounded (D-036 §1)."""

    fixed = datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC)
    hour = timedelta(hours=1)
    shapes = {
        "open": (None, None),
        "from_eq_now": (fixed, None),  # lower bound inclusive
        "from_past": (fixed - hour, None),
        "to_future": (None, fixed + hour),
        "to_eq_now": (None, fixed),  # upper bound exclusive
        "from_future": (fixed + hour, None),
        "to_past": (None, fixed - hour),
    }
    user = _user(db_session)
    rows: dict[str, Memory] = {}
    for name, (valid_from, valid_to) in shapes.items():
        row = _memory(user.id, valid_from=valid_from, valid_to=valid_to)
        rows[name] = row
        db_session.add(row)
    db_session.flush()

    live_ids = {
        row.id
        for row in db_session.scalars(select(Memory).where(*live_memory_conditions(now=fixed)))
    }
    for name, expected_live in [
        ("open", True),
        ("from_eq_now", True),
        ("from_past", True),
        ("to_future", True),
        ("to_eq_now", False),
        ("from_future", False),
        ("to_past", False),
    ]:
        assert (rows[name].id in live_ids) is expected_live, name


def test_readers_exclude_retired_unpointed_rows(client, auth_headers, db_session) -> None:
    """The FK SET NULL resurrection shape stays out of every reader."""

    user = _user(db_session)
    subject = "estimate:course:liveness"
    hour = timedelta(hours=1)

    resurrected = _memory(
        user.id,
        subject_key=subject,
        kind=MemoryKind.EPISODE,
        valid_to=datetime.now(UTC) - hour,  # retired, pointer cleared by SET NULL
    )
    future = _memory(
        user.id,
        kind=MemoryKind.EPISODE,
        valid_from=datetime.now(UTC) + hour,
    )
    windowed = _memory(
        user.id,
        kind=MemoryKind.EPISODE,
        valid_from=datetime.now(UTC) - hour,
        valid_to=datetime.now(UTC) + hour,
    )
    db_session.add_all([resurrected, future, windowed])
    db_session.flush()

    contents = {m.content for m in retrieve_memories(db_session, user_id=user.id)}
    assert contents == {windowed.content}

    assert live_key_row(db_session, user_id=user.id, subject_key=subject) is None
    episode_ids = _recent_episode_ids(db_session, user_id=user.id, course_name=None)
    assert str(windowed.id) in episode_ids
    assert str(resurrected.id) not in episode_ids
    assert str(future.id) not in episode_ids


def test_retired_squatter_does_not_block_new_subject_key(client, auth_headers, db_session) -> None:
    """A retired unpointed row must not squat (user, subject_key):
    the predicate pre-check passes AND the narrowed unique index lets the
    insert through (the r1 failure mode was a 409 from the squatting row)."""

    user = _user(db_session)
    subject = "estimate:course:squat"
    squatter = _memory(
        user.id,
        subject_key=subject,
        valid_to=datetime.now(UTC) - timedelta(hours=1),
    )
    db_session.add(squatter)
    db_session.commit()

    resp = client.post(
        "/v1/memory",
        headers=auth_headers,
        json={
            "content": "fresh live row on a squatted key",
            "subject_key": subject,
            "level": 2,
        },
    )
    assert resp.status_code == 201, resp.text
    fresh_id = resp.json()["id"]

    live_rows = retrieve_memories(db_session, user_id=user.id, subject_key=subject)
    assert [str(row.id) for row in live_rows] == [fresh_id]


def test_create_and_patch_ignore_client_validity(client, auth_headers, db_session) -> None:
    """valid_from/valid_to left the writable surface (D-036 §6): sending
    them is silently ignored, so a client cannot retire its own live row
    under the readers' feet."""

    created = client.post(
        "/v1/memory",
        headers=auth_headers,
        json={
            "content": "validity is server-managed",
            "valid_to": "2020-01-01T00:00:00Z",  # would be long-retired
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["valid_to"] is None
    memory_id = created.json()["id"]

    patched = client.patch(
        f"/v1/memory/{memory_id}",
        headers=auth_headers,
        json={
            "content": "still server-managed after patch",
            "valid_to": "2020-01-01T00:00:00Z",
            "valid_from": "2030-01-01T00:00:00Z",
        },
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["valid_to"] is None
    assert body["valid_from"] is None
    assert body["content"] == "still server-managed after patch"

    row = db_session.get(Memory, uuid.UUID(memory_id))
    assert row is not None and row.valid_to is None and row.valid_from is None
    # The ignored fields did not retire the row: it still reaches readers.
    retrieved = retrieve_memories(db_session, user_id=row.user_id, limit=200)
    assert row.id in {m.id for m in retrieved}


def test_keyed_upsert_ignores_retired_squatter(db_session, client, auth_headers) -> None:
    """The L2 writer resolves the live row with the same predicate: a
    retired squatter means 'no live row', so the upsert inserts fresh
    instead of superseding a dead row."""

    user = _user(db_session)
    subject = "estimate:course:upsert-squat"
    squatter = _memory(
        user.id,
        subject_key=subject,
        correction_status=MemoryCorrectionStatus.REJECTED,
        valid_to=datetime.now(UTC) - timedelta(hours=1),
    )
    db_session.add(squatter)
    db_session.commit()

    result = upsert_keyed_memory(
        db_session,
        user_id=user.id,
        subject_key=subject,
        level=2,
        kind="fact",
        domain="study",
        content="fresh derivation",
        source={"value": 45, "sample_count": 3},
        confidence=0.6,
        evidence=[],
    )
    assert result is not None
    assert result.supersedes_id is None  # fresh row, not a supersede of the dead one
    assert result.subject_key == subject
