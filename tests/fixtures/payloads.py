"""Payload builders for API contract tests.

Data here is synthetic and contains no real user information.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any


def iso(dt: datetime) -> str:
    return dt.isoformat()


def course_event(
    *, course: str = "Linear Algebra", dedupe_key: str | None = None
) -> dict[str, Any]:
    return {
        "type": "course.created",
        "source": "manual",
        "data": {"course": course, "semester": "2026-Fall"},
        "context": {"origin": "test-fixture"},
        "provenance": {"fixture": "payloads.course_event"},
        "dedupe_key": dedupe_key,
    }


def assignment_event(
    *,
    title: str = "Linear Algebra HW2",
    deadline: datetime | None = None,
    estimated_minutes: int = 120,
    dedupe_key: str | None = None,
) -> dict[str, Any]:
    deadline = deadline or (datetime.now(UTC) + timedelta(days=1))
    return {
        "type": "assignment.created",
        "source": "manual",
        "timestamp": iso(datetime.now(UTC)),
        "data": {
            "title": title,
            "course": "Linear Algebra",
            "deadline": iso(deadline),
            "estimated_minutes": estimated_minutes,
        },
        "context": {"origin": "test-fixture"},
        "provenance": {"fixture": "payloads.assignment_event"},
        "dedupe_key": dedupe_key or f"assignment:{uuid.uuid4().hex}",
    }


def task_payload(
    *,
    title: str = "Linear Algebra HW2",
    deadline: datetime | None = None,
    estimated_minutes: int = 120,
    goal_id: str | None = None,
    related_event_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "title": title,
        "description": "Complete exercises 1-10",
        "source": "manual",
        "deadline": iso(deadline or (datetime.now(UTC) + timedelta(days=1))),
        "estimated_duration_minutes": estimated_minutes,
        "goal_id": goal_id,
        "related_event_ids": related_event_ids or [],
    }


# Fixed timestamps keep the batch fixtures byte-for-byte repeatable.
_ASSIGNMENT_OCCURRED_AT = "2026-09-26T10:00:00+08:00"
_ASSIGNMENT_FETCHED_AT = "2026-09-26T10:00:01+08:00"


def assignment_envelope(
    *,
    client_event_id: str,
    upstream_id: str,
    title: str = "Linear Algebra HW2",
    estimated_minutes: int = 120,
    semantic_version: str = "v1",
    source: str = "onethu",
) -> dict[str, Any]:
    """Deterministic ``EventEnvelope`` for ``POST /v1/events/batch``.

    The dedupe key derives from ``source:upstream_id:semantic_version`` (D-010),
    so replaying the same envelope is idempotent and reported as a duplicate.
    """

    return {
        "client_event_id": client_event_id,
        "type": "study.assignment.discovered",
        "occurred_at": _ASSIGNMENT_OCCURRED_AT,
        "source": source,
        "data": {"title": title, "estimated_minutes": estimated_minutes},
        "context": {"origin": "test-fixture"},
        "provenance": {
            "connector": source,
            "connector_version": "2026-09-26",
            "upstream_id": upstream_id,
            "semantic_version": semantic_version,
            "fetched_at": _ASSIGNMENT_FETCHED_AT,
        },
    }


def goal_payload(*, title: str = "Do well in Linear Algebra") -> dict[str, Any]:
    return {
        "title": title,
        "description": "Reach a solid understanding before the final",
        "category": "study",
        "priority": 1,
    }


def memory_payload(*, content: str = "I usually underestimate assignment time") -> dict[str, Any]:
    return {
        "content": content,
        "level": 2,
        "domain": "time",
        "confidence": 0.7,
    }
