from __future__ import annotations

from typing import Any

import pytest

from tests.fixtures.payloads import assignment_event, course_event

pytestmark = pytest.mark.integration


def _envelope(
    client_event_id: str,
    *,
    upstream_id: str,
    semantic_version: str = "v1",
    data: dict[str, Any] | None = None,
    source: str = "onethu",
) -> dict[str, Any]:
    return {
        "client_event_id": client_event_id,
        "type": "study.assignment.discovered",
        "occurred_at": "2026-09-26T10:00:00+08:00",
        "source": source,
        "data": data or {"title": "HW1"},
        "context": {},
        "provenance": {
            "connector": source,
            "connector_version": "2e3455f",
            "upstream_id": upstream_id,
            "semantic_version": semantic_version,
            "fetched_at": "2026-09-26T10:00:01+08:00",
        },
    }


def test_create_event_returns_client_fields(client, auth_headers) -> None:
    response = client.post("/v1/events", json=course_event(), headers=auth_headers)
    assert response.status_code == 201
    body = response.json()
    assert body["type"] == "course.created"
    assert body["source"] == "manual"
    assert body["occurred_at"] == body["timestamp"]
    assert "client_event_id" in body


def test_single_event_dedupe_by_explicit_key(client, auth_headers) -> None:
    payload = assignment_event(dedupe_key="assignment:hw2")
    first = client.post("/v1/events", json=payload, headers=auth_headers)
    second = client.post("/v1/events", json=payload, headers=auth_headers)
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.headers["X-Deduplicated"] == "true"
    assert first.json()["id"] == second.json()["id"]


def test_single_event_dedupe_computed_from_provenance(client, auth_headers) -> None:
    envelope = _envelope("client-a", upstream_id="hw-2")
    payload = {
        "type": envelope["type"],
        "occurred_at": envelope["occurred_at"],
        "source": envelope["source"],
        "data": envelope["data"],
        "context": envelope["context"],
        "provenance": envelope["provenance"],
    }
    first = client.post("/v1/events", json=payload, headers=auth_headers)
    second = client.post("/v1/events", json=payload, headers=auth_headers)
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["dedupe_key"] == "onethu:hw-2:v1"


def test_event_listing_and_filters(client, auth_headers) -> None:
    client.post("/v1/events", json=course_event(), headers=auth_headers)
    client.post("/v1/events", json=assignment_event(), headers=auth_headers)

    all_events = client.get("/v1/events", headers=auth_headers)
    assert all_events.status_code == 200
    assert all_events.json()["total"] == 2

    filtered = client.get("/v1/events", params={"type": "assignment.created"}, headers=auth_headers)
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["type"] == "assignment.created"


def test_event_isolation_between_users(client, auth_factory) -> None:
    alice = auth_factory()
    bob = auth_factory()

    created = client.post("/v1/events", json=course_event(), headers=alice)
    event_id = created.json()["id"]

    assert client.get(f"/v1/events/{event_id}", headers=bob).status_code == 404
    assert client.get("/v1/events", headers=bob).json()["total"] == 0


def test_delete_event(client, auth_headers) -> None:
    created = client.post("/v1/events", json=course_event(), headers=auth_headers)
    event_id = created.json()["id"]
    assert client.delete(f"/v1/events/{event_id}", headers=auth_headers).status_code == 204
    assert client.get(f"/v1/events/{event_id}", headers=auth_headers).status_code == 404


def test_batch_ingest_accepts_and_reports_client_event_ids(client, auth_headers) -> None:
    payload = {
        "events": [
            _envelope("client-1", upstream_id="hw-1"),
            _envelope("client-2", upstream_id="hw-2"),
        ],
        "client_cursor": "cursor-1",
    }
    response = client.post("/v1/events/batch", json=payload, headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert sorted(body["accepted_event_ids"]) == ["client-1", "client-2"]
    assert body["duplicate_event_ids"] == []
    assert body["rejected"] == []
    assert body["next_cursor"] == "cursor-1"

    # Re-sending the same batch is idempotent and reports duplicates by client id.
    again = client.post("/v1/events/batch", json=payload, headers=auth_headers).json()
    assert again["accepted_event_ids"] == []
    assert sorted(again["duplicate_event_ids"]) == ["client-1", "client-2"]


def test_batch_ingest_rejects_sensitive_fields(client, auth_headers) -> None:
    payload = {
        "events": [
            _envelope("ok", upstream_id="hw-ok"),
            _envelope("bad", upstream_id="hw-bad", data={"password": "secret"}),
        ],
        "client_cursor": None,
    }
    body = client.post("/v1/events/batch", json=payload, headers=auth_headers).json()
    assert body["accepted_event_ids"] == ["ok"]
    assert len(body["rejected"]) == 1
    assert body["rejected"][0]["client_event_id"] == "bad"
    assert "data.password" in body["rejected"][0]["reason"]
    assert "secret" not in body["rejected"][0]["reason"]
