"""P0-3 slice 2: recover, receipts and the pinned digest algorithm.

The recover digest is the SHA-256 of the canonical confirm body (D-036
§8-2); the exact canonicalization is pinned by a shared fixture the desktop
client mirrors. Recover is the only path a DEACTIVATED identity may call,
works once inside a 10-minute delivery window, answers every negative with
one uniform 404 and is throttled per identity AND per IP. Receipt reads
authenticate by capability (Authorization header, never the URL) and share
the uniform-404 hardening.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from backend.models.data_lifecycle import DataCleanupItem, DataOperation, DataReceipt
from backend.models.enums import CleanupItemState, DataOperationStatus
from backend.services.data_recovery import (
    deletion_request_digest,
    seal_capability,
    unseal_capability,
)

from .test_data_api import _me, _preview, _seed_event

pytestmark = pytest.mark.integration

_FIXTURE = Path(__file__).parents[1] / "fixtures" / "deletion-recover-digest.json"


@pytest.fixture(autouse=True)
def _fresh_recover_limiters():
    """The route limiters are module-level; keep tests independent by
    swapping in a pair bound to a fresh Redis namespace per test (the limits
    themselves stay covered by the dedicated 429 test)."""

    import uuid as _uuid

    from backend.api.v1 import data as data_api
    from backend.core.rate_limit import RateLimiter

    original = data_api._RECOVER_LIMITS
    namespace = f"test:{_uuid.uuid4().hex}"
    data_api._RECOVER_LIMITS = (
        RateLimiter(max_requests=3, window_seconds=600.0, namespace=namespace),
        RateLimiter(max_requests=10, window_seconds=600.0, namespace=namespace),
    )
    yield
    data_api._RECOVER_LIMITS = original


class TestDigestAlgorithm:
    def test_fixture_pins_the_canonical_digest(self):
        payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
        for sample in payload["samples"]:
            assert deletion_request_digest(sample["body"]) == sample["sha256"]

    def test_seal_unseal_roundtrip(self):
        token = "x" * 43
        operation_id = uuid.uuid4()
        nonce, ciphertext = seal_capability(
            token, receipt_owner="0" * 16, operation_id=operation_id
        )
        assert (
            unseal_capability(nonce, ciphertext, receipt_owner="0" * 16, operation_id=operation_id)
            == token
        )
        # The receipt owner and operation id are bound into the keystream:
        # unsealing under a different binding yields garbage, not the token.
        with pytest.raises((UnicodeDecodeError, ValueError)):
            unseal_capability(nonce, ciphertext, receipt_owner="1" * 16, operation_id=operation_id)


def _account_confirm(client, headers, *, key: str) -> dict:
    _me(client, headers)
    _seed_event(client, headers)
    preview = _preview(client, headers, {"kind": "account"})
    body = {
        "preview_id": preview["id"],
        "preview_digest": preview["preview_digest"],
        "client_request_id": key,
        "confirmed": True,
    }
    response = client.post("/v1/data/deletions", json=body, headers=headers)
    assert response.status_code == 202, response.text
    operation = response.json()
    return {"operation": operation, "body": body, "digest": deletion_request_digest(body)}


def _recover(client, headers, *, key: str, digest: str):
    return client.post(
        "/v1/data/deletions/recover",
        json={"client_request_id": key, "request_digest": digest},
        headers=headers,
    )


class TestRecover:
    def test_recovers_the_capability_once_for_a_deactivated_identity(
        self, client, auth_headers, db_session
    ):
        confirmed = _account_confirm(client, auth_headers, key="recover-key-0001")
        operation = confirmed["operation"]
        # Business auth is closed after deactivation...
        assert client.get("/v1/auth/me", headers=auth_headers).status_code == 401

        response = _recover(
            client,
            auth_headers,
            key="recover-key-0001",
            digest=confirmed["digest"],
        )
        assert response.status_code == 200, response.text
        recovered = response.json()
        assert recovered["id"] == operation["id"]
        assert recovered["receipt_capability"] == operation["receipt_capability"]
        assert recovered["receipt_id"] == operation["receipt_id"]

        # Single use: the delivery cache is consumed on the first success.
        response = _recover(
            client, auth_headers, key="recover-key-0001", digest=confirmed["digest"]
        )
        assert response.status_code == 404
        receipt = db_session.scalar(select(DataReceipt))
        assert receipt is not None and receipt.delivery_ciphertext is None

    def test_outside_the_delivery_window_is_a_uniform_404(self, client, auth_headers, db_session):
        confirmed = _account_confirm(client, auth_headers, key="recover-key-0002")
        receipt = db_session.scalar(select(DataReceipt))
        receipt.delivery_expires_at = datetime.now(UTC) - timedelta(minutes=1)
        db_session.flush()
        response = _recover(
            client, auth_headers, key="recover-key-0002", digest=confirmed["digest"]
        )
        assert response.status_code == 404
        assert "code" in response.json()["error"]

    def test_wrong_digest_unknown_key_and_source_scope_are_indistinguishable(
        self, client, auth_headers, auth_factory
    ):
        confirmed = _account_confirm(client, auth_headers, key="recover-key-0003")
        statuses = set()
        response = _recover(client, auth_headers, key="recover-key-0003", digest="0" * 64)
        statuses.add(response.status_code)
        response = _recover(client, auth_headers, key="no-such-key-99", digest=confirmed["digest"])
        statuses.add(response.status_code)

        # Source deletions never issue capabilities: their recover is the
        # same 404 (a fresh user — the account confirm above deactivated).
        other = auth_factory()
        event_id = _seed_event(client, other)
        preview = _preview(
            client,
            other,
            {"kind": "source", "source_kind": "event", "ids": [event_id]},
        )
        body = {
            "preview_id": preview["id"],
            "preview_digest": preview["preview_digest"],
            "client_request_id": "source-recover-1",
            "confirmed": True,
        }
        response = client.post("/v1/data/deletions", json=body, headers=other)
        assert response.status_code == 202, response.text
        response = _recover(
            client,
            other,
            key="source-recover-1",
            digest=deletion_request_digest(body),
        )
        statuses.add(response.status_code)
        assert statuses == {404}, "every negative outcome is the same 404"

    def test_rate_limit_is_429_with_retry_after(self, client, auth_headers):
        _account_confirm(client, auth_headers, key="recover-key-0004")
        for _ in range(3):
            response = _recover(client, auth_headers, key="recover-key-0004", digest="0" * 64)
            assert response.status_code == 404
        response = _recover(client, auth_headers, key="recover-key-0004", digest="0" * 64)
        assert response.status_code == 429
        assert response.json()["error"]["code"] == "rate_limited"
        assert int(response.headers["Retry-After"]) >= 1


class TestReceipts:
    def test_capability_reads_the_receipt(self, client, auth_headers):
        confirmed = _account_confirm(client, auth_headers, key="receipt-key-001")
        operation = confirmed["operation"]
        response = client.get(
            f"/v1/data/receipts/{operation['receipt_id']}",
            headers={"Authorization": f"Bearer {operation['receipt_capability']}"},
        )
        assert response.status_code == 200, response.text
        receipt = response.json()
        assert receipt["operation_id"] == operation["id"]
        assert receipt["completion_scope"] == "controlled_live"
        assert receipt["completed_at"] is None  # executor has not run yet
        assert receipt["outstanding_count"] > 0
        assert receipt["local_cleanup_required"] is True
        assert receipt["audit_receipt_version"]
        assert isinstance(receipt["effects"], list) and receipt["effects"]

    def test_invalid_missing_and_expired_capabilities_are_one_404(
        self, client, auth_headers, db_session
    ):
        confirmed = _account_confirm(client, auth_headers, key="receipt-key-002")
        operation = confirmed["operation"]
        receipt_id = operation["receipt_id"]

        wrong = client.get(
            f"/v1/data/receipts/{receipt_id}", headers={"Authorization": "Bearer nope"}
        )
        none_ = client.get(f"/v1/data/receipts/{receipt_id}")
        unknown = client.get(
            f"/v1/data/receipts/{uuid.uuid4()}",
            headers={"Authorization": f"Bearer {operation['receipt_capability']}"},
        )
        assert {wrong.status_code, none_.status_code, unknown.status_code} == {404}

        receipt = db_session.scalar(select(DataReceipt))
        receipt.expires_at = datetime.now(UTC) - timedelta(days=1)
        db_session.flush()
        expired = client.get(
            f"/v1/data/receipts/{receipt_id}",
            headers={"Authorization": f"Bearer {operation['receipt_capability']}"},
        )
        assert expired.status_code == 404


def _force_failed(db_session, operation_id: uuid.UUID) -> DataOperation:
    """Park a confirmed account deletion the way an exhausted ladder would:
    operation FAILED with error state, one item FAILED mid-ladder."""

    operation = db_session.scalar(select(DataOperation).where(DataOperation.id == operation_id))
    operation.status = DataOperationStatus.FAILED
    operation.error_code = "ladder_exhausted"
    operation.error_message = "chaos injection"
    operation.error_retryable = True
    item = db_session.scalars(
        select(DataCleanupItem)
        .where(DataCleanupItem.operation_id == operation_id)
        .order_by(DataCleanupItem.id)
    ).first()
    item.state = CleanupItemState.FAILED
    item.attempts = 5
    item.last_error = "S3 403"
    db_session.flush()
    return operation


class TestAccountRequeue:
    """Capability-driven requeue for FAILED account deletions (external
    review #7): the receipt narrow path is the only key after the
    confirm-time deactivation, and it drives the same ladder reset as the
    source/memory manual retry."""

    def test_requeue_revives_a_failed_account_deletion(self, client, auth_headers, db_session):
        confirmed = _account_confirm(client, auth_headers, key="requeue-key-01")
        operation = confirmed["operation"]
        row = _force_failed(db_session, uuid.UUID(operation["id"]))
        failed_ids = {
            item.id
            for item in db_session.scalars(
                select(DataCleanupItem).where(DataCleanupItem.operation_id == row.id)
            ).all()
            if item.state == CleanupItemState.FAILED
        }
        assert failed_ids  # the forced-failure precondition held

        # Precondition: business auth is closed, the authed retry route is
        # unreachable for this owner — the capability is the only way in.
        assert client.get("/v1/auth/me", headers=auth_headers).status_code == 401

        requeued = client.post(
            f"/v1/data/receipts/{operation['receipt_id']}/requeue",
            json={"expected_version": operation["version"]},
            headers={"Authorization": f"Bearer {operation['receipt_capability']}"},
        )
        assert requeued.status_code == 200, requeued.text
        body = requeued.json()
        assert body["id"] == operation["id"]
        assert body["status"] == "QUEUED"
        assert body["version"] == operation["version"] + 1

        db_session.refresh(row)
        assert row.status == DataOperationStatus.QUEUED
        assert row.error_code is None and row.error_message is None
        items = db_session.scalars(
            select(DataCleanupItem).where(DataCleanupItem.operation_id == row.id)
        ).all()
        assert all(item.state == CleanupItemState.PENDING for item in items)
        assert all(item.attempts == 0 and item.last_error is None for item in items)

    def test_wrong_or_missing_capability_is_the_uniform_404(self, client, auth_headers):
        confirmed = _account_confirm(client, auth_headers, key="requeue-key-02")
        operation = confirmed["operation"]
        url = f"/v1/data/receipts/{operation['receipt_id']}/requeue"

        wrong = client.post(
            url, json={"expected_version": 1}, headers={"Authorization": "Bearer nope"}
        )
        missing = client.post(url, json={"expected_version": 1})
        unknown = client.post(
            f"/v1/data/receipts/{uuid.uuid4()}/requeue",
            json={"expected_version": 1},
            headers={"Authorization": f"Bearer {operation['receipt_capability']}"},
        )
        assert {wrong.status_code, missing.status_code, unknown.status_code} == {404}

    def test_completed_termination_never_requeues(self, client, auth_headers, db_session):
        confirmed = _account_confirm(client, auth_headers, key="requeue-key-03")
        operation = confirmed["operation"]
        row = db_session.scalar(
            select(DataOperation).where(DataOperation.id == uuid.UUID(operation["id"]))
        )
        row.status = DataOperationStatus.COMPLETED
        db_session.flush()

        response = client.post(
            f"/v1/data/receipts/{operation['receipt_id']}/requeue",
            json={"expected_version": operation["version"]},
            headers={"Authorization": f"Bearer {operation['receipt_capability']}"},
        )
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "not_retryable"

    def test_version_conflict_on_a_stale_holder(self, client, auth_headers, db_session):
        confirmed = _account_confirm(client, auth_headers, key="requeue-key-04")
        operation = confirmed["operation"]
        _force_failed(db_session, uuid.UUID(operation["id"]))

        response = client.post(
            f"/v1/data/receipts/{operation['receipt_id']}/requeue",
            json={"expected_version": operation["version"] + 3},
            headers={"Authorization": f"Bearer {operation['receipt_capability']}"},
        )
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "version_conflict"

    def test_receipt_exposes_operation_status_and_version(self, client, auth_headers, db_session):
        confirmed = _account_confirm(client, auth_headers, key="requeue-key-05")
        operation = confirmed["operation"]
        row = _force_failed(db_session, uuid.UUID(operation["id"]))

        response = client.get(
            f"/v1/data/receipts/{operation['receipt_id']}",
            headers={"Authorization": f"Bearer {operation['receipt_capability']}"},
        )
        assert response.status_code == 200, response.text
        receipt = response.json()
        assert receipt["operation_status"] == "FAILED"
        assert receipt["operation_version"] == row.version
