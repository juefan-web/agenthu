from __future__ import annotations

import pytest

from tests.fixtures.payloads import assignment_event, memory_payload

pytestmark = pytest.mark.integration


def test_memory_crud(client, auth_headers) -> None:
    event = client.post("/v1/events", json=assignment_event(), headers=auth_headers).json()
    created = client.post(
        "/v1/memory",
        json={**memory_payload(), "source_event_ids": [event["id"]]},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    memory = created.json()
    assert memory["level"] == 2
    assert memory["correction_status"] == "UNREVIEWED"
    assert event["id"] in memory["source_event_ids"]

    fetched = client.get(f"/v1/memory/{memory['id']}", headers=auth_headers)
    assert fetched.status_code == 200

    corrected = client.patch(
        f"/v1/memory/{memory['id']}",
        json={"content": "I tend to underestimate time", "correction_status": "CORRECTED"},
        headers=auth_headers,
    )
    assert corrected.json()["correction_status"] == "CORRECTED"

    assert client.delete(f"/v1/memory/{memory['id']}", headers=auth_headers).status_code == 204
    assert client.get(f"/v1/memory/{memory['id']}", headers=auth_headers).status_code == 404


def test_memory_list_filters(client, auth_headers) -> None:
    client.post("/v1/memory", json=memory_payload(), headers=auth_headers)
    client.post(
        "/v1/memory",
        json={**memory_payload(content="Runs on Tue/Thu"), "domain": "exercise", "level": 1},
        headers=auth_headers,
    )
    response = client.get("/v1/memory", params={"domain": "exercise"}, headers=auth_headers)
    assert response.json()["total"] == 1


def test_memory_isolation_between_users(client, auth_factory) -> None:
    alice = auth_factory()
    bob = auth_factory()
    memory = client.post("/v1/memory", json=memory_payload(), headers=alice).json()
    assert client.get(f"/v1/memory/{memory['id']}", headers=bob).status_code == 404


def test_memory_rejects_other_users_source_event(client, auth_factory) -> None:
    alice = auth_factory()
    bob = auth_factory()
    event = client.post("/v1/events", json=assignment_event(), headers=alice).json()

    response = client.post(
        "/v1/memory",
        json={**memory_payload(), "source_event_ids": [event["id"]]},
        headers=bob,
    )
    assert response.status_code == 404

    created = client.post("/v1/memory", json=memory_payload(), headers=bob).json()
    patched = client.patch(
        f"/v1/memory/{created['id']}",
        json={"source_event_ids": [event["id"]]},
        headers=bob,
    )
    assert patched.status_code == 404
