"""Recover and receipt-read paths for account-deletion capabilities (slice 2).

Frozen semantics (A-draft §4 / D-036 §8-2):

- the recover digest is the SHA-256 of the canonical confirm request body
  (keys sorted, no whitespace, UTF-8); the body carries preview_digest, so
  the digest transitively binds content. The exact canonicalization is
  pinned by a shared fixture (tests/fixtures/deletion-recover-digest.json)
  that the desktop client mirrors — both ends must keep producing these
  exact digests;
- the first 202 hands out the capability exactly once; a lost response can
  re-fetch it through POST /deletions/recover for 10 minutes using the
  ORIGINAL JWT identity (deactivated accounts included — this is the only
  path that works after deactivation), the original client_request_id and
  the digest. Outside the window a capability can never be re-issued;
- anti-enumeration: recover and GET /receipts/{id} answer "no such request /
  wrong digest / expired cache / wrong capability" with one uniform 404 —
  the caller cannot distinguish them, and the capability value never
  reaches any log;
- the 10-minute delivery cache stores the capability encrypted with an
  HMAC-SHA256 keystream derived from the server secret (key = secret, info
  = receipt owner + operation id + random per-receipt nonce, counter-mode
  expansion — no extra crypto dependency, one short block, nonce used
  once). It is single-use: the first successful recover clears it.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.db.base import utcnow
from backend.models.data_lifecycle import DataOperation, DataReceipt
from backend.models.enums import DataOperationKind

#: Keystream domain separator; changing it invalidates every sealed cache.
_DELIVERY_INFO = b"data:receipt-delivery-v1"


def _canonical_json(body: dict) -> str:
    """The pinned canonical form: sorted keys, no whitespace, real UTF-8."""

    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def deletion_request_digest(body: dict) -> str:
    """SHA-256 of the canonical confirm body (the recover second factor)."""

    return hashlib.sha256(_canonical_json(body).encode("utf-8")).hexdigest()


def _keystream(nonce: bytes, receipt_owner: str, operation_id: uuid.UUID, length: int) -> bytes:
    secret = get_settings().secret_key.encode("utf-8")
    stream = bytearray()
    counter = 0
    while len(stream) < length:
        block = hmac.new(
            secret,
            _DELIVERY_INFO
            + receipt_owner.encode("utf-8")
            + operation_id.bytes
            + nonce
            + counter.to_bytes(1, "big"),
            hashlib.sha256,
        ).digest()
        stream.extend(block)
        counter += 1
    return bytes(stream[:length])


def seal_capability(token: str, *, receipt_owner: str, operation_id: uuid.UUID) -> tuple[str, str]:
    """Encrypt the capability for the 10-minute delivery cache."""

    nonce = secrets.token_bytes(16)
    plaintext = token.encode("utf-8")
    keystream = _keystream(nonce, receipt_owner, operation_id, len(plaintext))
    ciphertext = bytes(a ^ b for a, b in zip(plaintext, keystream, strict=True))
    return nonce.hex(), ciphertext.hex()


def unseal_capability(
    nonce_hex: str, ciphertext_hex: str, *, receipt_owner: str, operation_id: uuid.UUID
) -> str:
    nonce = bytes.fromhex(nonce_hex)
    ciphertext = bytes.fromhex(ciphertext_hex)
    keystream = _keystream(nonce, receipt_owner, operation_id, len(ciphertext))
    plaintext = bytes(a ^ b for a, b in zip(ciphertext, keystream, strict=True))
    return plaintext.decode("utf-8")


def recover_deletion(
    session: Session,
    *,
    owner_handle: str,
    client_request_id: str,
    request_digest: str,
) -> tuple[DataOperation, str] | None:
    """Re-deliver a lost capability within the 10-minute window.

    Returns (operation, capability) on the one allowed re-delivery, or None
    for every other outcome (no such request / digest mismatch / no receipt
    / cache expired or already used / not an account deletion) — the route
    maps None to the uniform 404, so callers learn nothing about which
    condition held.
    """

    operation = session.scalar(
        select(DataOperation).where(
            DataOperation.owner_handle == owner_handle,
            DataOperation.kind == DataOperationKind.DELETION,
            DataOperation.client_request_id == client_request_id,
        )
    )
    if operation is None or operation.request_digest != request_digest:
        return None
    if (operation.target or {}).get("kind") != "account":
        # Only account deletions issue capabilities worth recovering.
        return None
    receipt = session.scalar(select(DataReceipt).where(DataReceipt.operation_id == operation.id))
    if receipt is None or receipt.delivery_ciphertext is None:
        return None
    now: datetime = utcnow()
    if receipt.delivery_expires_at is None or receipt.delivery_expires_at <= now:
        # Expired cache is dead: clear it and answer the uniform 404. After
        # the window a capability can never be re-issued (A-draft §4).
        receipt.delivery_nonce = None
        receipt.delivery_ciphertext = None
        receipt.delivery_expires_at = None
        session.flush()
        return None
    if not receipt.delivery_nonce:
        return None
    capability = unseal_capability(
        receipt.delivery_nonce,
        receipt.delivery_ciphertext,
        receipt_owner=owner_handle,
        operation_id=operation.id,
    )
    # Single use: consumed on the successful re-delivery.
    receipt.delivery_nonce = None
    receipt.delivery_ciphertext = None
    receipt.delivery_expires_at = None
    session.flush()
    # Defense in depth: the re-delivered token must match the stored digest.
    if hmac.compare_digest(
        hashlib.sha256(capability.encode("utf-8")).hexdigest(), receipt.capability_digest
    ):
        return operation, capability
    return None


def receipt_view(session: Session, *, receipt_id: uuid.UUID, capability: str) -> DataReceipt | None:
    """Resolve a receipt by id + capability (Authorization header value).

    Invalid, unknown or expired capabilities are indistinguishable: None →
    the route answers a uniform 404 (anti-enumeration, A-draft §4)."""

    receipt = session.get(DataReceipt, receipt_id)
    if receipt is None:
        return None
    digest = hashlib.sha256(capability.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(digest, receipt.capability_digest):
        return None
    if receipt.expires_at <= utcnow():
        return None
    return receipt
