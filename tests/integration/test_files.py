from __future__ import annotations

import hashlib

import pytest

pytestmark = pytest.mark.integration

_CONTENT = b"%PDF-1.4 synthetic test document"


def test_file_upload_download_and_delete(client, auth_headers) -> None:
    upload = client.post(
        "/api/v1/files",
        files={"file": ("notes.pdf", _CONTENT, "application/pdf")},
        headers=auth_headers,
    )
    assert upload.status_code == 201, upload.text
    body = upload.json()
    assert body["filename"] == "notes.pdf"
    assert body["size_bytes"] == len(_CONTENT)
    assert body["checksum_sha256"] == hashlib.sha256(_CONTENT).hexdigest()
    assert body["storage_backend"] == "memory"

    listing = client.get("/api/v1/files", headers=auth_headers)
    assert listing.json()["total"] == 1

    download = client.get(f"/api/v1/files/{body['id']}/download", headers=auth_headers)
    assert download.status_code == 200
    assert download.content == _CONTENT

    signed = client.get(f"/api/v1/files/{body['id']}/signed-url", headers=auth_headers)
    assert signed.status_code == 200
    assert signed.json()["url"].startswith("memory://")

    assert client.delete(f"/api/v1/files/{body['id']}", headers=auth_headers).status_code == 204
    assert client.get(f"/api/v1/files/{body['id']}", headers=auth_headers).status_code == 404


def test_empty_upload_is_rejected(client, auth_headers) -> None:
    response = client.post(
        "/api/v1/files",
        files={"file": ("empty.txt", b"", "text/plain")},
        headers=auth_headers,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_file_isolation_between_users(client, auth_factory) -> None:
    alice = auth_factory()
    bob = auth_factory()
    upload = client.post(
        "/api/v1/files",
        files={"file": ("secret.txt", b"hello", "text/plain")},
        headers=alice,
    ).json()
    assert client.get(f"/api/v1/files/{upload['id']}", headers=bob).status_code == 404
    assert client.get(f"/api/v1/files/{upload['id']}/download", headers=bob).status_code == 404
