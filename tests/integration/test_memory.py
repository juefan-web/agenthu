from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from backend.models.memory import Memory
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


def test_memory_extension_fields_round_trip(client, auth_headers) -> None:
    event = client.post("/v1/events", json=assignment_event(), headers=auth_headers).json()
    document_evidence = {
        "type": "document",
        "file_id": "1e6b4c2a-9d3f-4a52-8c11-2b7d90f6a3aa",
        "checksum_sha256": "a" * 64,
        "page": 3,
        "span_start": 0,
        "span_end": 120,
    }
    created = client.post(
        "/v1/memory",
        json={
            **memory_payload(),
            "kind": "fact",
            "subject_key": "estimate:course:linear-algebra",
            "evidence": [{"type": "event", "id": event["id"]}, document_evidence],
            "valid_from": "2026-10-01T08:00:00+08:00",
            "valid_to": "2027-01-31T23:59:00+08:00",
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    memory = created.json()
    assert memory["kind"] == "fact"
    assert memory["subject_key"] == "estimate:course:linear-algebra"
    assert {"type": "event", "id": event["id"]} in memory["evidence"]
    assert document_evidence in memory["evidence"]
    # Server-managed columns exist on read and start neutral.
    assert memory["supersedes_id"] is None
    assert memory["use_count"] == 0
    assert memory["last_used_at"] is None
    # Compare validity bounds as absolute instants: the echoed offset follows
    # the flushed (not re-read) ORM value, which is the input offset here —
    # the same serialization behavior round-5 pinned down for task due_at.
    assert datetime.fromisoformat(memory["valid_from"]) == datetime.fromisoformat(
        "2026-10-01T08:00:00+08:00"
    )
    assert datetime.fromisoformat(memory["valid_to"]) == datetime.fromisoformat(
        "2027-01-31T23:59:00+08:00"
    )


def test_memory_live_subject_key_is_unique_per_user(client, auth_factory) -> None:
    alice = auth_factory()
    key = {"subject_key": "estimate_ratio:user"}
    first = client.post("/v1/memory", json={**memory_payload(), **key}, headers=alice)
    assert first.status_code == 201
    # A second live row for the same key is rejected (live-row invariant).
    second = client.post(
        "/v1/memory",
        json={**memory_payload(content="another ratio"), **key},
        headers=alice,
    )
    assert second.status_code == 409
    # The invariant is per user: the same key is fine for someone else.
    bob = auth_factory()
    other = client.post("/v1/memory", json={**memory_payload(), **key}, headers=bob)
    assert other.status_code == 201


def test_memory_chained_row_does_not_block_the_live_key(client, auth_headers, db_session) -> None:
    live = client.post(
        "/v1/memory",
        json={**memory_payload(), "subject_key": "estimate:course:linear-algebra"},
        headers=auth_headers,
    ).json()
    me = client.get("/v1/auth/me", headers=auth_headers).json()
    # A version-chain row sharing the key must coexist with the live row: the
    # partial unique index only constrains rows with supersedes_id IS NULL.
    db_session.add(
        Memory(
            user_id=uuid.UUID(me["id"]),
            content="superseded estimate",
            level=2,
            domain="time",
            confidence=0.7,
            subject_key="estimate:course:linear-algebra",
            supersedes_id=uuid.UUID(live["id"]),
        )
    )
    db_session.flush()

    conflict = client.post(
        "/v1/memory",
        json={**memory_payload(), "subject_key": "estimate:course:linear-algebra"},
        headers=auth_headers,
    )
    assert conflict.status_code == 409


def test_memory_evidence_rejects_other_users_event(client, auth_factory) -> None:
    alice = auth_factory()
    bob = auth_factory()
    event = client.post("/v1/events", json=assignment_event(), headers=alice).json()

    response = client.post(
        "/v1/memory",
        json={
            **memory_payload(),
            "evidence": [{"type": "event", "id": event["id"]}],
        },
        headers=bob,
    )
    assert response.status_code == 404

    created = client.post("/v1/memory", json=memory_payload(), headers=bob).json()
    patched = client.patch(
        f"/v1/memory/{created['id']}",
        json={"evidence": [{"type": "event", "id": event["id"]}]},
        headers=bob,
    )
    assert patched.status_code == 404
