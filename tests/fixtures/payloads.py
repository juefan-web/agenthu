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
