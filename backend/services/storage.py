"""Object storage abstraction.

Raw bytes (PDF/PPT/audio/transcripts) live in S3-compatible object storage, not
in PostgreSQL. ``LocalMinIO`` is the M0 implementation; a hosted S3 backend can
reuse the same interface. An in-memory backend keeps the test suite hermetic.
"""

from __future__ import annotations

import io
import logging
from abc import ABC, abstractmethod
from functools import lru_cache

import boto3
from botocore.client import BaseClient, Config
from botocore.exceptions import BotoCoreError, ClientError

from backend.config import get_settings
from backend.core.errors import StorageError

logger = logging.getLogger(__name__)


class ObjectStorage(ABC):
    backend_name: str = "abstract"

    STAT_EXISTS = "exists"
    STAT_ABSENT = "absent"
    STAT_FORBIDDEN = "forbidden"
    STAT_UNAVAILABLE = "unavailable"

    @abstractmethod
    def put(self, key: str, data: bytes, content_type: str) -> None: ...

    @abstractmethod
    def get(self, key: str) -> bytes: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def signed_url(self, key: str, expires_in: int | None = None) -> str: ...

    def stat(self, key: str) -> str:
        """Erasure-evidence trichotomy (A-draft §2.5), unlike ``exists``.

        Returns one of STAT_EXISTS / STAT_ABSENT / STAT_FORBIDDEN /
        STAT_UNAVAILABLE. Only STAT_ABSENT is erasure evidence: a 403 or a
        network failure must never be read as "the object is gone".
        """

        return self.STAT_EXISTS if self.exists(key) else self.STAT_ABSENT

    def ensure_ready(self) -> None:
        """Best-effort readiness check. Default no-op."""

        return None


class InMemoryStorage(ObjectStorage):
    """Hermetic storage for tests and offline development."""

    backend_name = "memory"

    def __init__(self) -> None:
        self._objects: dict[str, tuple[bytes, str]] = {}

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self._objects[key] = (data, content_type)

    def get(self, key: str) -> bytes:
        if key not in self._objects:
            raise StorageError(f"Object not found: {key}")
        return self._objects[key][0]

    def exists(self, key: str) -> bool:
        return key in self._objects

    def delete(self, key: str) -> None:
        self._objects.pop(key, None)

    def signed_url(self, key: str, expires_in: int | None = None) -> str:
        return f"memory://{key}"


class S3Storage(ObjectStorage):
    """S3-compatible storage (MinIO locally, hosted S3 in production)."""

    backend_name = "minio"

    def __init__(
        self,
        *,
        endpoint_url: str | None,
        access_key: str,
        secret_key: str,
        bucket: str,
        region: str,
        use_ssl: bool,
        signed_url_expire_seconds: int,
    ) -> None:
        self._bucket = bucket
        self._default_expiry = signed_url_expire_seconds
        self._client: BaseClient = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            use_ssl=use_ssl,
            # Path-style addressing works with MinIO, S3Mock and hosted S3.
            config=Config(s3={"addressing_style": "path"}),
        )

    def ensure_bucket(self) -> None:
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except ClientError:
            try:
                self._client.create_bucket(Bucket=self._bucket)
            except (ClientError, BotoCoreError) as exc:
                raise StorageError(f"Unable to create bucket '{self._bucket}'") from exc

    def ensure_ready(self) -> None:
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except (ClientError, BotoCoreError) as exc:
            raise StorageError(f"Object storage bucket '{self._bucket}' is not available") from exc

    def put(self, key: str, data: bytes, content_type: str) -> None:
        try:
            self._client.put_object(
                Bucket=self._bucket, Key=key, Body=io.BytesIO(data), ContentType=content_type
            )
        except (ClientError, BotoCoreError) as exc:
            raise StorageError(f"Failed to store object: {key}") from exc

    def get(self, key: str) -> bytes:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            return response["Body"].read()
        except (ClientError, BotoCoreError) as exc:
            raise StorageError(f"Failed to read object: {key}") from exc

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except (ClientError, BotoCoreError):
            return False

    def stat(self, key: str) -> str:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return self.STAT_EXISTS
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            status = str(exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", ""))
            if code in ("404", "NoSuchKey", "NotFound") or status == "404":
                return self.STAT_ABSENT
            if code in ("403", "AccessDenied", "Forbidden") or status == "403":
                return self.STAT_FORBIDDEN
            return self.STAT_UNAVAILABLE
        except BotoCoreError:
            return self.STAT_UNAVAILABLE

    def delete(self, key: str) -> None:
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
        except (ClientError, BotoCoreError) as exc:
            raise StorageError(f"Failed to delete object: {key}") from exc

    def signed_url(self, key: str, expires_in: int | None = None) -> str:
        try:
            return self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=expires_in or self._default_expiry,
            )
        except (ClientError, BotoCoreError) as exc:
            raise StorageError(f"Failed to sign URL for object: {key}") from exc


def build_storage() -> ObjectStorage:
    settings = get_settings()
    if settings.storage_backend == "memory":
        return InMemoryStorage()
    storage = S3Storage(
        endpoint_url=settings.s3_endpoint_url,
        access_key=settings.s3_access_key,
        secret_key=settings.s3_secret_key,
        bucket=settings.s3_bucket,
        region=settings.s3_region,
        use_ssl=settings.s3_use_ssl,
        signed_url_expire_seconds=settings.signed_url_expire_seconds,
    )
    try:
        storage.ensure_bucket()
    except StorageError:
        logger.warning("Object storage bucket is not ready; uploads will fail until it is")
    return storage


@lru_cache
def get_storage() -> ObjectStorage:
    return build_storage()


def reset_storage() -> None:
    get_storage.cache_clear()
