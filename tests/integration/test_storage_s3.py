from __future__ import annotations

import os
import uuid
from urllib.parse import urlparse

import pytest

from backend.services.storage import S3Storage
from tests.conftest import tcp_available

pytestmark = [pytest.mark.integration, pytest.mark.storage]


@pytest.fixture
def s3_storage() -> S3Storage:
    endpoint = os.environ.get("S3_ENDPOINT_URL")
    if not endpoint:
        pytest.skip("S3_ENDPOINT_URL is not set")

    parsed = urlparse(endpoint)
    host = parsed.hostname or "localhost"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if not tcp_available(host, port):
        pytest.skip(f"S3-compatible storage is not reachable at {endpoint}")

    storage = S3Storage(
        endpoint_url=endpoint,
        access_key=os.environ.get("S3_ACCESS_KEY", "agenthu"),
        secret_key=os.environ.get("S3_SECRET_KEY", "agenthu123"),
        bucket=os.environ.get("S3_BUCKET", "agenthu"),
        region=os.environ.get("S3_REGION", "us-east-1"),
        use_ssl=parsed.scheme == "https",
        signed_url_expire_seconds=60,
    )
    storage.ensure_bucket()
    return storage


def test_s3_storage_roundtrip(s3_storage: S3Storage) -> None:
    key = f"tests/{uuid.uuid4().hex}.txt"
    s3_storage.put(key, b"hello-s3", "text/plain")
    try:
        assert s3_storage.exists(key)
        assert s3_storage.get(key) == b"hello-s3"
        assert s3_storage.signed_url(key).startswith("http")
    finally:
        s3_storage.delete(key)
    assert not s3_storage.exists(key)
