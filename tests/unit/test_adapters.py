from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.adapters.base import (
    AdapterCredentials,
    NormalizedEvent,
    normalize_to_event_create,
)
from backend.adapters.onethu import OneTHUAdapter
from backend.core.errors import ServiceUnavailableError


def test_normalized_event_maps_to_event_contract() -> None:
    normalized = NormalizedEvent(
        type="assignment.created",
        source="onethu",
        timestamp=datetime(2026, 9, 26, 8, 0, tzinfo=UTC),
        data={"title": "HW2"},
        provenance={"external_id": "abc"},
        dedupe_key="onethu:assignment:abc",
    )
    payload = normalize_to_event_create(normalized)
    assert payload.type == "assignment.created"
    assert payload.source == "onethu"
    assert payload.dedupe_key == "onethu:assignment:abc"
    assert payload.data["title"] == "HW2"


def test_onethu_adapter_is_an_explicit_stub() -> None:
    adapter = OneTHUAdapter()
    with pytest.raises(ServiceUnavailableError):
        adapter.fetch(user_id=__import__("uuid").uuid4(), credentials=AdapterCredentials())
    assert adapter.health()["status"] == "not_implemented"
