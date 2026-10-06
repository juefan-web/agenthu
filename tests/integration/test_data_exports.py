"""P0-3 slice 2: the export pipeline and its /v1/data routes.

One graph, one snapshot (A-draft §3): collect reads every family in one
transaction, the ZIP is immutable staging with a checksum manifest, READY
requires verification to reproduce every manifest checksum, download is
owner-auth + no-store, 24h staging expires with the object deleted, and a
concurrent deletion voids the package instead of letting it report READY.
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from backend.models.chat import ChatMessage, ChatSession
from backend.models.data_lifecycle import DataOperation
from backend.models.enums import DataOperationStatus
from backend.models.file import FileObject
from backend.models.memory import Memory
from backend.services.data_exports import (
    expire_ready_exports,
    run_export,
    staging_key,
)
from backend.services.storage import get_storage

from .test_data_api import _confirm, _me, _preview, _seed_citing_memory, _seed_event

pytestmark = pytest.mark.integration

_BLOB = b"course notes blob, exported verbatim"


def _seed_rich_world(client, auth_headers, db_session: Session) -> dict:
    me = _me(client, auth_headers)
    user_id = uuid.UUID(me["id"])
    event_id = _seed_event(client, auth_headers)
    memory_id = _seed_citing_memory(db_session, user_id, event_id)
    memory = db_session.get(Memory, memory_id)
    memory.embedding = [0.1] * 1536  # type: ignore[index]
    chat = ChatSession(user_id=user_id, title="chat")
    db_session.add(chat)
    db_session.flush()
    db_session.add(ChatMessage(session_id=chat.id, user_id=user_id, role="user", content="hi"))
    file_id = uuid.uuid4()
    storage_key = f"objects/{file_id}"
    get_storage().put(storage_key, _BLOB, "application/octet-stream")
    db_session.add(
        FileObject(id=file_id, user_id=user_id, storage_key=storage_key, filename="notes.txt")
    )
    db_session.flush()
    return {"user_id": user_id, "event_id": event_id, "memory_id": memory_id, "file_id": file_id}


def _export(client, headers, *, key: str = "export-key-1", include_files: bool | None = None):
    body: dict[str, object] = {"client_request_id": key}
    if include_files is not None:
        body["include_files"] = include_files
    response = client.post("/v1/data/exports", json=body, headers=headers)
    assert response.status_code == 202, response.text
    return response.json()


def _run(db_session: Session, operation_id) -> DataOperation:
    operation = db_session.get(DataOperation, operation_id)
    assert operation is not None
    run_export(db_session, operation, storage=get_storage())
    db_session.flush()
    return operation


def _unzip(package: bytes) -> tuple[dict, dict[str, bytes]]:
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(members["manifest.json"])
    return manifest, members


class TestExportPipeline:
    def test_package_ready_download_and_manifest(self, client, auth_headers, db_session):
        world = _seed_rich_world(client, auth_headers, db_session)
        operation = _export(client, auth_headers)
        assert operation["status"] == "QUEUED"
        assert operation["kind"] == "EXPORT"
        assert operation["target"] is None
        operation_id = uuid.UUID(operation["id"])
        db_session.expire_all()

        result = _run(db_session, operation_id)
        assert result.status == DataOperationStatus.READY
        assert result.expires_at is not None
        assert result.expires_at > datetime.now(UTC)

        response = client.get(
            f"/v1/data/operations/{operation['id']}/download", headers=auth_headers
        )
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        manifest, members = _unzip(response.content)

        assert manifest["schema_version"] and manifest["graph_version"]
        assert manifest["generation"] == 1
        assert manifest["family_counts"]["events"] == 1
        assert manifest["family_counts"]["chat_messages"] == 1
        assert manifest["include_files"] is True

        events = [json.loads(line) for line in members["events.jsonl"].decode().splitlines()]
        assert events[0]["id"] == world["event_id"]
        memories = [json.loads(line) for line in members["memories.jsonl"].decode().splitlines()]
        assert memories[0]["id"] == str(world["memory_id"])
        # Embeddings never leave the backend (A-draft §3).
        assert "embedding" not in memories[0]
        assert "credentials" in " ".join(manifest["excluded_categories"]).lower() or any(
            "credential" in category for category in manifest["excluded_categories"]
        )
        users_rows = [json.loads(line) for line in members["users.jsonl"].decode().splitlines()]
        assert "hashed_password" not in users_rows[0]
        # Files ride along with include_files=true.
        file_entries = [name for name in members if name.startswith("files/")]
        assert len(file_entries) == 1
        assert members[file_entries[0]] == _BLOB
        # Every manifest entry checksum reproduces (minus manifest.json itself).
        import hashlib

        for entry in manifest["entries"]:
            data = members[entry["path"]]
            assert hashlib.sha256(data).hexdigest() == entry["sha256"]
            assert len(data) == entry["size_bytes"]

    def test_include_files_false_lists_omissions(self, client, auth_headers, db_session):
        _seed_rich_world(client, auth_headers, db_session)
        operation = _export(client, auth_headers, include_files=False)
        operation_id = uuid.UUID(operation["id"])
        db_session.expire_all()
        result = _run(db_session, operation_id)
        assert result.status == DataOperationStatus.READY

        response = client.get(
            f"/v1/data/operations/{operation['id']}/download", headers=auth_headers
        )
        assert response.status_code == 200
        manifest, members = _unzip(response.content)
        assert manifest["include_files"] is False
        assert manifest["omitted_files"] and manifest["omitted_files"][0]["filename"]
        assert not [name for name in members if name.startswith("files/")]

    def test_export_idempotency_covers_include_files(self, client, auth_headers):
        first = _export(client, auth_headers, key="idem-export-1", include_files=True)
        second = _export(client, auth_headers, key="idem-export-1", include_files=True)
        assert second["id"] == first["id"]
        response = client.post(
            "/v1/data/exports",
            json={"client_request_id": "idem-export-1", "include_files": False},
            headers=auth_headers,
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "idempotency_conflict"

    def test_download_requires_ready(self, client, auth_headers):
        operation = _export(client, auth_headers, key="not-ready-1")
        response = client.get(
            f"/v1/data/operations/{operation['id']}/download", headers=auth_headers
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "export_not_ready"

    def test_download_is_owner_scoped(self, client, auth_factory):
        alice = auth_factory()
        bob = auth_factory()
        operation = _export(client, alice, key="owner-export-1")
        response = client.get(f"/v1/data/operations/{operation['id']}/download", headers=bob)
        assert response.status_code == 404

    def test_concurrent_deletion_voids_the_package(self, client, auth_headers, db_session):
        world = _seed_rich_world(client, auth_headers, db_session)
        operation = _export(client, auth_headers, key="void-export-1")
        operation_id = uuid.UUID(operation["id"])
        db_session.expire_all()
        result = _run(db_session, operation_id)
        assert result.status == DataOperationStatus.READY

        # A source deletion bumps the generation: the READY package is void.
        preview = _preview(
            client,
            auth_headers,
            {"kind": "source", "source_kind": "event", "ids": [world["event_id"]]},
        )
        _confirm(client, auth_headers, preview, key="void-delete-1")

        response = client.get(
            f"/v1/data/operations/{operation['id']}/download", headers=auth_headers
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "invalidated_by_deletion"
        db_session.expire_all()
        assert db_session.get(DataOperation, operation_id).status == DataOperationStatus.FAILED

    def test_staging_expiry_flips_expired_and_deletes_object(
        self, client, auth_headers, db_session
    ):
        _seed_rich_world(client, auth_headers, db_session)
        operation = _export(client, auth_headers, key="expire-export-1")
        operation_id = uuid.UUID(operation["id"])
        db_session.expire_all()
        result = _run(db_session, operation_id)
        assert result.status == DataOperationStatus.READY
        package_key = staging_key(result.owner_handle, operation_id)
        assert get_storage().stat(package_key) == get_storage().STAT_EXISTS

        result.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db_session.flush()
        expired = expire_ready_exports(db_session, storage=get_storage())
        assert expired == 1
        db_session.expire_all()
        assert db_session.get(DataOperation, operation_id).status == DataOperationStatus.EXPIRED
        assert get_storage().stat(package_key) == get_storage().STAT_ABSENT

        response = client.get(
            f"/v1/data/operations/{operation['id']}/download", headers=auth_headers
        )
        assert response.status_code == 410
        assert response.json()["error"]["code"] == "export_expired"

    def test_audit_export_is_content_free(self, client, auth_headers, db_session):
        from backend.models.audit import AuditLog

        me = _me(client, auth_headers)
        db_session.add(
            AuditLog(
                user_id=uuid.UUID(me["id"]),
                actor="user",
                action="x.y",
                ip_address="8.8.8.8",
                user_agent="ua",
                details={"secret": "payload"},
            )
        )
        db_session.flush()
        operation = _export(client, auth_headers, key="audit-export-1")
        db_session.expire_all()
        _run(db_session, uuid.UUID(operation["id"]))
        response = client.get(
            f"/v1/data/operations/{operation['id']}/download", headers=auth_headers
        )
        _, members = _unzip(response.content)
        rows = [json.loads(line) for line in members["audit_logs.jsonl"].decode().splitlines()]
        assert rows, "audit receipt copies are exported"
        assert set(rows[0]) <= {"id", "actor", "action", "decision", "created_at"}, (
            "the audit copy is the content-free receipt view only"
        )
