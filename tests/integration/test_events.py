from __future__ import annotations

import pytest

from tests.fixtures.payloads import assignment_event, course_event

pytestmark = pytest.mark.integration


def test_create_event_returns_201(client, auth_headers) -> None:
    response = client.post("/api/v1/events", json=course_event(), headers=auth_headers)
    assert response.status_code == 201
    body = response.json()
    assert body["type"] == "course.created"
    assert body["source"] == "manual"
    assert body["provenance"]["fixture"] == "payloads.course_event"
    assert response.headers["X-Deduplicated"] == "false"


def test_event_deduplication_by_dedupe_key(client, auth_headers) -> None:
    payload = assignment_event(dedupe_key="assignment:hw2")
    first = client.post("/api/v1/events", json=payload, headers=auth_headers)
    second = client.post("/api/v1/events", json=payload, headers=auth_headers)
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.headers["X-Deduplicated"] == "true"
    assert first.json()["id"] == second.json()["id"]


def test_event_listing_and_filters(client, auth_headers) -> None:
    client.post("/api/v1/events", json=course_event(), headers=auth_headers)
    client.post("/api/v1/events", json=assignment_event(), headers=auth_headers)

    all_events = client.get("/api/v1/events", headers=auth_headers)
    assert all_events.status_code == 200
    assert all_events.json()["total"] == 2

    filtered = client.get(
        "/api/v1/events", params={"type": "assignment.created"}, headers=auth_headers
    )
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["type"] == "assignment.created"


def test_event_isolation_between_users(client, auth_factory) -> None:
    alice = auth_factory()
    bob = auth_factory()

    created = client.post("/api/v1/events", json=course_event(), headers=alice)
    event_id = created.json()["id"]

    assert client.get(f"/api/v1/events/{event_id}", headers=bob).status_code == 404
    assert client.get("/api/v1/events", headers=bob).json()["total"] == 0


def test_delete_event(client, auth_headers) -> None:
    created = client.post("/api/v1/events", json=course_event(), headers=auth_headers)
    event_id = created.json()["id"]
    assert client.delete(f"/api/v1/events/{event_id}", headers=auth_headers).status_code == 204
    assert client.get(f"/api/v1/events/{event_id}", headers=auth_headers).status_code == 404
