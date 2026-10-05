"""P0-3 slice 1: /v1/data previews, confirm transaction, operation reads.

Covers the frozen confirm semantics (A-draft §2/§4): digest-bound previews
that 409 instead of silently widening, idempotent replay keyed on
(owner, kind, client_request_id) with the preview digest in the comparison,
the users-row-lock serialization + IntegrityError convergence for concurrent
same-key confirms (B carry ① on #70), barrier raise with cleanup-item
registration, account deactivation with grant/consent revocation and the
one-time receipt capability, and source suppression keyed by upstream HMAC.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.models.chat import ChatMessage, ChatSession
from backend.models.consent import ModelContextConsent
from backend.models.data_lifecycle import (
    DataBarrier,
    DataCleanupItem,
    DataOperation,
    DataPreview,
    DataReceipt,
    DataSuppression,
)
from backend.models.enums import (
    CleanupItemAction,
    DataBarrierScope,
    DataOperationKind,
    DataOperationStatus,
)
from backend.models.file import FileObject
from backend.models.material import MaterialAnswer, MaterialChunk
from backend.models.memory import Memory
from backend.models.permission import PermissionGrant
from backend.models.task import Task, task_events
from backend.models.user import User
from backend.services import data_operations as ops
from backend.services.data_registry import graph_version
from tests.fixtures.payloads import assignment_event

pytestmark = pytest.mark.integration


def _me(client, headers) -> dict:
    return client.get("/v1/auth/me", headers=headers).json()


def _seed_event(client, headers) -> str:
    response = client.post("/v1/events", json=assignment_event(), headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _seed_task_with_edge(db_session: Session, user_id, event_id) -> uuid.UUID:
    task = Task(user_id=user_id, title="derived", source="event")
    db_session.add(task)
    db_session.flush()
    db_session.execute(insert(task_events).values(task_id=task.id, event_id=event_id))
    db_session.flush()
    return task.id


def _seed_citing_memory(db_session: Session, user_id, event_id) -> uuid.UUID:
    memory = Memory(
        user_id=user_id,
        level=1,
        domain="study",
        content="episode derived from the event",
        confidence=0.6,
        source_event_ids=[event_id],
    )
    db_session.add(memory)
    db_session.flush()
    return memory.id


def _preview(client, headers, target: dict) -> dict:
    response = client.post("/v1/data/previews", json=target, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _confirm(client, headers, preview: dict, *, key: str = "confirm-key-1") -> dict:
    response = client.post(
        "/v1/data/deletions",
        json={
            "preview_id": preview["id"],
            "preview_digest": preview["preview_digest"],
            "client_request_id": key,
            "confirmed": True,
        },
        headers=headers,
    )
    assert response.status_code == 202, response.text
    return response.json()


def _effects(preview: dict) -> dict[str, dict]:
    return {effect["resource_type"]: effect for effect in preview["effects"]}


class TestCapabilities:
    def test_shape_and_honesty(self, client, auth_headers):
        body = client.get("/v1/data/capabilities", headers=auth_headers).json()
        assert body["deletion_enabled"] is True
        assert body["supported_source_kinds"] == ["event", "file", "chat_session", "chat_message"]
        assert body["graph_version"] == graph_version()
        # The export pipeline is slice 2; capabilities must not advertise it.
        assert body["export_enabled"] is False


class TestPreviews:
    def test_account_preview_counts_seeded_families(self, client, auth_headers, db_session):
        me = _me(client, auth_headers)
        user_id = uuid.UUID(me["id"])
        event_id = _seed_event(client, auth_headers)
        _seed_task_with_edge(db_session, user_id, uuid.UUID(event_id))
        _seed_citing_memory(db_session, user_id, event_id)
        chat = ChatSession(user_id=user_id)
        db_session.add(chat)
        db_session.flush()
        db_session.add(
            ChatMessage(session_id=chat.id, user_id=user_id, role="user", content="hello")
        )
        db_session.flush()

        preview = _preview(client, auth_headers, {"kind": "account"})
        effects = _effects(preview)

        assert effects["events"]["delete_count"] == 1
        assert effects["tasks"]["delete_count"] == 1
        assert effects["task_events"]["delete_count"] == 1
        assert effects["memories"]["delete_count"] == 1
        assert effects["chat_sessions"]["delete_count"] == 1
        assert effects["chat_messages"]["delete_count"] == 1
        assert preview["data_generation"] == 1
        assert len(preview["preview_digest"]) == 64
        assert preview["expires_at"] > datetime.now(UTC).isoformat()
        assert preview["limitations"], "backup/provider/local limits must be listed"

    def test_source_event_preview_walks_derivation_edges(self, client, auth_headers, db_session):
        me = _me(client, auth_headers)
        user_id = uuid.UUID(me["id"])
        event_id = _seed_event(client, auth_headers)
        _seed_task_with_edge(db_session, user_id, uuid.UUID(event_id))
        _seed_citing_memory(db_session, user_id, event_id)
        # An unrelated second event stays out of the closure.
        _seed_event(client, auth_headers)

        preview = _preview(
            client,
            auth_headers,
            {"kind": "source", "source_kind": "event", "ids": [event_id]},
        )
        effects = _effects(preview)
        assert effects["events"]["delete_count"] == 1
        assert effects["tasks"]["delete_count"] == 1
        assert effects["task_events"]["delete_count"] == 1
        assert effects["memories"]["delete_count"] == 1
        assert effects["memories"]["reason_code"] == "derived_closure"

    def test_source_event_preview_isolates_owners(self, client, auth_factory, db_session):
        alice = auth_factory()
        bob = auth_factory()
        event_id = _seed_event(client, alice)
        _seed_citing_memory(db_session, uuid.UUID(_me(client, bob)["id"]), event_id)

        preview = _preview(
            client,
            alice,
            {"kind": "source", "source_kind": "event", "ids": [event_id]},
        )
        # Bob's memory cites the same event id string but is NOT Alice's row.
        assert _effects(preview).get("memories") is None

    def test_foreign_or_missing_target_id_is_404(self, client, auth_factory):
        alice = auth_factory()
        bob = auth_factory()
        bob_event = _seed_event(client, bob)
        response = client.post(
            "/v1/data/previews",
            json={"kind": "source", "source_kind": "event", "ids": [bob_event]},
            headers=alice,
        )
        assert response.status_code == 404

        response = client.post(
            "/v1/data/previews",
            json={"kind": "source", "source_kind": "event", "ids": [str(uuid.uuid4())]},
            headers=alice,
        )
        assert response.status_code == 404

    def test_memory_preview_walks_the_whole_chain(self, client, auth_headers, db_session):
        user_id = uuid.UUID(_me(client, auth_headers)["id"])
        oldest = Memory(user_id=user_id, level=2, domain="study", content="v1", confidence=0.5)
        db_session.add(oldest)
        db_session.flush()
        middle = Memory(
            user_id=user_id,
            level=2,
            domain="study",
            content="v2",
            confidence=0.5,
            supersedes_id=oldest.id,
        )
        db_session.add(middle)
        db_session.flush()
        live = Memory(
            user_id=user_id,
            level=2,
            domain="study",
            content="v3",
            confidence=0.5,
            supersedes_id=middle.id,
        )
        db_session.add(live)
        db_session.flush()

        preview = _preview(
            client, auth_headers, {"kind": "memory", "ids": [str(live.id)], "include_history": True}
        )
        effect = _effects(preview)["memories"]
        assert effect["delete_count"] == 3
        assert effect["reason_code"] == "supersedes_chain"

    def test_memory_target_requires_explicit_history(self, client, auth_headers):
        response = client.post(
            "/v1/data/previews",
            json={"kind": "memory", "ids": [str(uuid.uuid4())], "include_history": False},
            headers=auth_headers,
        )
        assert response.status_code == 422

    def test_file_preview_counts_chunks_and_citing_answers(self, client, auth_headers, db_session):
        user_id = uuid.UUID(_me(client, auth_headers)["id"])
        file_row = FileObject(
            user_id=user_id, storage_key=f"objects/{uuid.uuid4()}", filename="hw2.pdf"
        )
        db_session.add(file_row)
        db_session.flush()
        db_session.add(
            MaterialChunk(
                user_id=user_id,
                file_id=file_row.id,
                chunk_index=0,
                content="page 1",
                char_count=6,
                scanner_version="test",
            )
        )
        db_session.add(
            MaterialAnswer(
                user_id=user_id,
                course_name="Linear Algebra",
                question="Q",
                answer="A",
                grounded=True,
                citations=[{"file_id": str(file_row.id), "checksum": "x" * 64, "page": 1}],
                chunk_ids=[],
                memory_ids=[],
                model_version="test-model",
                prompt_version="v1",
            )
        )
        db_session.flush()

        preview = _preview(
            client,
            auth_headers,
            {"kind": "source", "source_kind": "file", "ids": [str(file_row.id)]},
        )
        effects = _effects(preview)
        assert effects["file_objects"]["delete_count"] == 1
        assert effects["material_chunks"]["delete_count"] == 1
        assert effects["material_answers"]["delete_count"] == 1


class TestConfirmDeletion:
    def test_source_confirm_accepts_and_registers_everything(
        self, client, auth_headers, db_session
    ):
        me = _me(client, auth_headers)
        user_id = uuid.UUID(me["id"])
        event_id = _seed_event(client, auth_headers)
        _seed_task_with_edge(db_session, user_id, uuid.UUID(event_id))

        preview = _preview(
            client, auth_headers, {"kind": "source", "source_kind": "event", "ids": [event_id]}
        )
        operation = _confirm(client, auth_headers, preview, key="source-confirm-1")

        assert operation["status"] == "QUEUED"
        assert operation["kind"] == "DELETION"
        assert operation["data_generation"] == 2
        assert operation["progress"]["outstanding_count"] > 0
        assert operation["receipt_capability"] is None

        handle = next(
            db_session.execute(select(User.owner_handle).where(User.id == user_id)).scalars()
        )
        barrier = db_session.scalar(
            select(DataBarrier).where(
                DataBarrier.owner_handle == handle,
                DataBarrier.state == "ACTIVE",
            )
        )
        assert barrier is not None
        assert barrier.scope == DataBarrierScope.SOURCE
        assert barrier.target == preview["target"]

        items = db_session.scalars(
            select(DataCleanupItem).where(
                DataCleanupItem.operation_id == uuid.UUID(operation["id"])
            )
        ).all()
        by_action = {(item.action, item.item_ref): item for item in items}
        events_delete = by_action[(CleanupItemAction.DELETE_RELATIONAL, "events")]
        assert events_delete.payload == {"ids": [event_id]}
        assert (CleanupItemAction.VERIFY_ABSENT, "events") in by_action

        suppression = db_session.scalar(select(DataSuppression))
        assert suppression is not None
        assert suppression.source_kind == "event"
        assert suppression.upstream_hmac != event_id  # HMAC, never the raw id

        get_response = client.get(f"/v1/data/operations/{operation['id']}", headers=auth_headers)
        assert get_response.status_code == 200
        assert get_response.headers["X-Data-Generation"] == "2"
        assert get_response.json()["receipt_capability"] is None

    def test_replay_returns_the_same_operation(self, client, auth_headers):
        event_id = _seed_event(client, auth_headers)
        preview = _preview(
            client, auth_headers, {"kind": "source", "source_kind": "event", "ids": [event_id]}
        )
        first = _confirm(client, auth_headers, preview, key="replay-key-1")
        second = _confirm(client, auth_headers, preview, key="replay-key-1")
        assert second["id"] == first["id"]
        assert second["version"] == first["version"]

    def test_same_key_different_preview_is_409(self, client, auth_headers):
        event_a = _seed_event(client, auth_headers)
        event_b = _seed_event(client, auth_headers)
        preview_a = _preview(
            client, auth_headers, {"kind": "source", "source_kind": "event", "ids": [event_a]}
        )
        preview_b = _preview(
            client, auth_headers, {"kind": "source", "source_kind": "event", "ids": [event_b]}
        )
        _confirm(client, auth_headers, preview_a, key="conflict-key-1")
        response = client.post(
            "/v1/data/deletions",
            json={
                "preview_id": preview_b["id"],
                "preview_digest": preview_b["preview_digest"],
                "client_request_id": "conflict-key-1",
                "confirmed": True,
            },
            headers=auth_headers,
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "idempotency_conflict"

    def test_scope_drift_between_preview_and_confirm_is_409(self, client, auth_headers, db_session):
        me = _me(client, auth_headers)
        event_id = _seed_event(client, auth_headers)
        preview = _preview(
            client, auth_headers, {"kind": "source", "source_kind": "event", "ids": [event_id]}
        )
        # Something ENTERING the closure (a new memory citing the target
        # event) changes the impact set — a bare unrelated event would not.
        _seed_citing_memory(db_session, uuid.UUID(me["id"]), event_id)
        response = client.post(
            "/v1/data/deletions",
            json={
                "preview_id": preview["id"],
                "preview_digest": preview["preview_digest"],
                "client_request_id": "stale-key-1",
                "confirmed": True,
            },
            headers=auth_headers,
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "preview_stale"

    def test_expired_or_wrong_digest_preview_is_409(self, client, auth_headers, db_session):
        event_id = _seed_event(client, auth_headers)
        preview = _preview(
            client, auth_headers, {"kind": "source", "source_kind": "event", "ids": [event_id]}
        )
        db_session.execute(
            update(DataPreview)
            .where(DataPreview.id == uuid.UUID(preview["id"]))
            .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        db_session.flush()
        response = client.post(
            "/v1/data/deletions",
            json={
                "preview_id": preview["id"],
                "preview_digest": preview["preview_digest"],
                "client_request_id": "expired-key-1",
                "confirmed": True,
            },
            headers=auth_headers,
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "preview_stale"

        fresh = _preview(
            client, auth_headers, {"kind": "source", "source_kind": "event", "ids": [event_id]}
        )
        response = client.post(
            "/v1/data/deletions",
            json={
                "preview_id": fresh["id"],
                "preview_digest": "0" * 64,
                "client_request_id": "digest-key-1",
                "confirmed": True,
            },
            headers=auth_headers,
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "preview_stale"

    def test_second_deletion_of_same_scope_is_in_progress(self, client, auth_headers):
        event_id = _seed_event(client, auth_headers)
        preview = _preview(
            client, auth_headers, {"kind": "source", "source_kind": "event", "ids": [event_id]}
        )
        _confirm(client, auth_headers, preview, key="first-key-1")
        # A FRESH preview of the same (not yet executed) scope passes the
        # staleness re-check and then hits the ACTIVE barrier.
        fresh = _preview(
            client, auth_headers, {"kind": "source", "source_kind": "event", "ids": [event_id]}
        )
        response = client.post(
            "/v1/data/deletions",
            json={
                "preview_id": fresh["id"],
                "preview_digest": fresh["preview_digest"],
                "client_request_id": "second-key-1",
                "confirmed": True,
            },
            headers=auth_headers,
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "deletion_in_progress"

    def test_operation_read_is_owner_scoped(self, client, auth_factory):
        alice = auth_factory()
        bob = auth_factory()
        event_id = _seed_event(client, alice)
        preview = _preview(
            client, alice, {"kind": "source", "source_kind": "event", "ids": [event_id]}
        )
        operation = _confirm(client, alice, preview, key="owner-key-1")
        response = client.get(f"/v1/data/operations/{operation['id']}", headers=bob)
        assert response.status_code == 404

    def test_integrity_error_converges_to_the_winner(
        self, client, auth_headers, db_session, monkeypatch
    ):
        """B carry ① on #70: a same-key confirm that slides past the
        pre-checks converges on the winner's operation instead of erroring."""

        event_id = _seed_event(client, auth_headers)
        preview = _preview(
            client, auth_headers, {"kind": "source", "source_kind": "event", "ids": [event_id]}
        )
        user = db_session.scalars(select(User)).one()
        from backend.services import data_lifecycle as dl

        handle = dl.owner_handle_of(db_session, user.id)
        winner = DataOperation(
            owner_handle=handle,
            kind=DataOperationKind.DELETION,
            client_request_id="race-key-1",
            target=preview["target"],
            preview_digest=preview["preview_digest"],
            status=DataOperationStatus.QUEUED,
            data_generation=2,
        )
        db_session.add(winner)
        db_session.flush()

        # Simulate the losing racer: both pre-check SELECTs see nothing (the
        # winner is invisible to them), then the INSERT hits the idempotency
        # unique constraint. The catch must converge on the now-visible
        # winner instead of erroring.
        real_find = ops._find_idempotent
        real_get_or_create = dl.get_or_create_operation
        seen = {"n": 0}

        def missing_first_two(*args, **kwargs):
            seen["n"] += 1
            if seen["n"] <= 2:
                return None
            return real_find(*args, **kwargs)

        def racing_get_or_create(session, owner_handle, request):
            raise IntegrityError("unique violation simulation", None, Exception())

        monkeypatch.setattr(ops, "_find_idempotent", missing_first_two)
        monkeypatch.setattr(ops.dl, "get_or_create_operation", racing_get_or_create)
        try:
            operation, capability = ops.confirm_deletion(
                db_session,
                user=user,
                preview_id=uuid.UUID(preview["id"]),
                preview_digest_value=preview["preview_digest"],
                client_request_id="race-key-1",
            )
        finally:
            monkeypatch.setattr(ops.dl, "get_or_create_operation", real_get_or_create)

        assert operation.id == winner.id
        assert capability is None


class TestAccountDeletion:
    def test_confirm_deactivates_revokes_and_issues_capability_once(
        self, client, auth_headers, db_session
    ):
        me = _me(client, auth_headers)
        user_id = uuid.UUID(me["id"])
        grant = PermissionGrant(user_id=user_id, action="agent.act", level=2)
        consent = ModelContextConsent(user_id=user_id, enabled=True, consent_text_version="v1")
        db_session.add_all([grant, consent])
        db_session.flush()

        preview = _preview(client, auth_headers, {"kind": "account"})
        response = client.post(
            "/v1/data/deletions",
            json={
                "preview_id": preview["id"],
                "preview_digest": preview["preview_digest"],
                "client_request_id": "account-key-1",
                "confirmed": True,
            },
            headers=auth_headers,
        )
        assert response.status_code == 202, response.text
        operation = response.json()

        db_session.expire_all()
        assert db_session.get(User, user_id).is_active is False
        assert grant.revoked_at is not None
        assert consent.revoked_at is not None

        receipt = db_session.scalar(select(DataReceipt))
        assert receipt is not None
        assert receipt.owner_handle == next(
            db_session.execute(select(User.owner_handle).where(User.id == user_id)).scalars()
        )
        assert (
            receipt.capability_digest
            == hashlib.sha256(operation["receipt_capability"].encode()).hexdigest()
        )
        assert len(operation["receipt_capability"]) >= 40

        # Deactivated account: business auth is closed from here on.
        assert client.get("/v1/auth/me", headers=auth_headers).status_code == 401

    def test_account_cleanup_items_cover_redis_and_audit(self, client, auth_headers, db_session):
        preview = _preview(client, auth_headers, {"kind": "account"})
        operation = _confirm(client, auth_headers, preview, key="account-items-1")
        items = db_session.scalars(
            select(DataCleanupItem).where(
                DataCleanupItem.operation_id == uuid.UUID(operation["id"])
            )
        ).all()
        refs = {(item.action, item.item_ref) for item in items}
        assert (CleanupItemAction.CLEAR_REDIS, "agenthu:trigger:dirty") in refs
        assert (CleanupItemAction.CLEAR_REDIS, "agenthu:storage:orphans") in refs
