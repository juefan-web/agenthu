from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.core.sensitive import find_sensitive_paths, validate_json_payload
from backend.schemas.event import EventCreate


@pytest.mark.parametrize(
    "payload",
    [
        {"password": "hunter2"},
        {"nested": {"access_token": "abc"}},
        {"items": [{"cookie": "session=1"}]},
        {"AuthoriZation": "Bearer x"},
        {"otp": "123456"},
    ],
)
def test_sensitive_keys_are_found_recursively(payload: dict) -> None:
    assert find_sensitive_paths(payload, path="data")


def test_validate_json_payload_reports_paths_without_values() -> None:
    reason = validate_json_payload("data", {"password": "super-secret"})
    assert reason is not None
    assert "data.password" in reason
    assert "super-secret" not in reason


def test_event_create_rejects_sensitive_data() -> None:
    with pytest.raises(ValidationError):
        EventCreate(type="study.assignment.discovered", data={"password": "x"})


def test_event_create_rejects_oversized_payload() -> None:
    with pytest.raises(ValidationError):
        EventCreate(type="study.assignment.discovered", data={"blob": "x" * (300 * 1024)})


def test_event_create_accepts_occurred_at_alias() -> None:
    event = EventCreate.model_validate(
        {"type": "study.assignment.discovered", "occurred_at": "2026-09-26T10:00:00+08:00"}
    )
    assert event.timestamp.tzinfo is not None
