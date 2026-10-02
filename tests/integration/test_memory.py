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

    # Correction goes through the semantic endpoint (D-032 ruling): direct
    # correction_status fills are ignored on PATCH.
    ignored = client.patch(
        f"/v1/memory/{memory['id']}",
        json={"correction_status": "CORRECTED"},
        headers=auth_headers,
    )
    assert ignored.status_code == 200
    assert ignored.json()["correction_status"] == "UNREVIEWED"

    corrected = client.post(
        f"/v1/memory/{memory['id']}/correct",
        json={"content": "I tend to underestimate time", "confidence": 0.9},
        headers=auth_headers,
    )
    assert corrected.status_code == 201, corrected.text
    body = corrected.json()
    assert body["correction_status"] == "CONFIRMED"
    assert body["source"]["user_corrected"] is True

    old = client.get(f"/v1/memory/{memory['id']}", headers=auth_headers).json()
    assert old["correction_status"] == "CORRECTED"
    assert old["supersedes_id"] == body["id"]

    assert client.delete(f"/v1/memory/{body['id']}", headers=auth_headers).status_code == 204
    assert client.get(f"/v1/memory/{body['id']}", headers=auth_headers).status_code == 404


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
    assert memory["embedding"] is None
    # Compare validity bounds as absolute instants: the echoed offset follows
    # the flushed (not re-read) ORM value, which is the input offset here —
    # the same serialization behavior round-5 pinned down for task due_at.
    assert datetime.fromisoformat(memory["valid_from"]) == datetime.fromisoformat(
        "2026-10-01T08:00:00+08:00"
    )
    assert datetime.fromisoformat(memory["valid_to"]) == datetime.fromisoformat(
        "2027-01-31T23:59:00+08:00"
    )


def test_memory_embedding_round_trip_and_not_client_writable(
    client, auth_headers, db_session
) -> None:
    """M3 pgvector slice: a 1536-dim vector persists and surfaces read-only.

    ``embedding`` is not a MemoryCreate field (server writers own it — they
    arrive with the M3 retrieval slice), so a client-supplied value is ignored
    like any unknown key. Equality needs an epsilon: pgvector's wire text is
    the shortest decimal that round-trips the column's float4 elements, so a
    float64-exact input can come back with up to ~1e-7 of representation
    error even though the stored float4 is exact.
    """
    created = client.post(
        "/v1/memory",
        json={**memory_payload(), "embedding": [0.1, 0.2]},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["embedding"] is None

    memory_id = uuid.UUID(created.json()["id"])
    embedding = [i / 1024 for i in range(1536)]
    stored = db_session.get(Memory, memory_id)
    assert stored is not None
    stored.embedding = embedding
    db_session.flush()
    db_session.refresh(stored)
    assert stored.embedding == pytest.approx(embedding, abs=1e-6)

    fetched = client.get(f"/v1/memory/{memory_id}", headers=auth_headers)
    assert fetched.status_code == 200
    assert fetched.json()["embedding"] == pytest.approx(embedding, abs=1e-6)


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


def test_memory_confirm_and_reject_semantics(client, auth_headers) -> None:
    key = "estimate:course:linear-algebra"
    created = client.post(
        "/v1/memory",
        json={**memory_payload(), "kind": "fact", "subject_key": key},
        headers=auth_headers,
    ).json()

    confirmed = client.post(f"/v1/memory/{created['id']}/confirm", headers=auth_headers)
    assert confirmed.status_code == 200
    assert confirmed.json()["correction_status"] == "CONFIRMED"
    # Idempotent: confirming again is a no-op.
    assert (
        client.post(f"/v1/memory/{created['id']}/confirm", headers=auth_headers).status_code == 200
    )

    rejected = client.post(f"/v1/memory/{created['id']}/reject", headers=auth_headers)
    assert rejected.status_code == 200
    assert rejected.json()["correction_status"] == "REJECTED"
    # The REJECTED row stays live and keeps occupying its subject_key (the
    # re-derivation block): a fresh live row for the same key still conflicts.
    conflict = client.post(
        "/v1/memory",
        json={**memory_payload(), "subject_key": key},
        headers=auth_headers,
    )
    assert conflict.status_code == 409
    listed = client.get(
        "/v1/memory", params={"correction_status": "REJECTED"}, headers=auth_headers
    )
    assert listed.json()["total"] == 1

    # Confirm is the documented un-reject path.
    unrejected = client.post(f"/v1/memory/{created['id']}/confirm", headers=auth_headers)
    assert unrejected.json()["correction_status"] == "CONFIRMED"


def test_memory_correct_walks_the_superseded_by_chain(client, auth_headers) -> None:
    key = "estimate_ratio:user"
    created = client.post(
        "/v1/memory",
        json={
            **memory_payload(),
            "kind": "fact",
            "subject_key": key,
            "confidence": 0.4,
            "valid_from": "2026-10-01T08:00:00+08:00",
        },
        headers=auth_headers,
    ).json()

    first = client.post(
        f"/v1/memory/{created['id']}/correct",
        json={"content": "corrected ratio: 1.2x"},
        headers=auth_headers,
    )
    assert first.status_code == 201, first.text
    v2 = first.json()
    # New version is the live, user-confirmed row; keyed identity carries over.
    assert v2["id"] != created["id"]
    assert v2["supersedes_id"] is None
    assert v2["correction_status"] == "CONFIRMED"
    assert v2["content"] == "corrected ratio: 1.2x"
    assert v2["subject_key"] == key
    assert v2["kind"] == "fact"
    assert v2["confidence"] == 0.4  # carried over when not overridden

    # Old row: retired in place — CORRECTED, superseded-by pointer at the new
    # row (the confirmed direction), validity closed, content untouched.
    v1 = client.get(f"/v1/memory/{created['id']}", headers=auth_headers).json()
    assert v1["correction_status"] == "CORRECTED"
    assert v1["supersedes_id"] == v2["id"]
    assert v1["valid_to"] is not None
    assert v1["content"] == memory_payload()["content"]

    # Operating on history is an error; correcting the live row chains again.
    stale = client.post(
        f"/v1/memory/{created['id']}/correct", json={"content": "stale"}, headers=auth_headers
    )
    assert stale.status_code == 409
    second = client.post(
        f"/v1/memory/{v2['id']}/correct",
        json={"content": "corrected ratio: 1.3x", "confidence": 0.9},
        headers=auth_headers,
    )
    v3 = second.json()
    assert v3["confidence"] == 0.9
    v2_after = client.get(f"/v1/memory/{v2['id']}", headers=auth_headers).json()
    assert v2_after["supersedes_id"] == v3["id"]
    assert v2_after["correction_status"] == "CORRECTED"
