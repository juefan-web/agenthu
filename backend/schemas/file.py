from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from backend.schemas.common import ORMModel


class FileRead(ORMModel):
    id: uuid.UUID
    user_id: uuid.UUID
    storage_key: str
    storage_backend: str
    filename: str
    content_type: str
    size_bytes: int
    checksum_sha256: str | None
    status: str
    course_name: str | None
    file_metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class SignedUrl(BaseModel):
    url: str
    expires_in: int
