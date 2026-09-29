from __future__ import annotations

import pytest

from backend.core.errors import StorageError
from backend.services.storage import InMemoryStorage


def test_memory_storage_roundtrip() -> None:
    storage = InMemoryStorage()
    storage.put("user/file.txt", b"hello", "text/plain")
    assert storage.exists("user/file.txt")
    assert storage.get("user/file.txt") == b"hello"
    assert storage.signed_url("user/file.txt") == "memory://user/file.txt"


def test_memory_storage_delete() -> None:
    storage = InMemoryStorage()
    storage.put("k", b"v", "text/plain")
    storage.delete("k")
    assert not storage.exists("k")
    with pytest.raises(StorageError):
        storage.get("k")
