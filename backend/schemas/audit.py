from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from backend.schemas.common import ORMModel


class AuditLogRead(ORMModel):
    id: uuid.UUID
    user_id: uuid.UUID | None
    actor: str
    action: str
    resource_type: str | None
    resource_id: str | None
    method: str | None
    path: str | None
    status_code: int | None
    duration_ms: int | None
    permission_level: int | None
    decision: str | None
    details: dict[str, Any]
    ip_address: str | None
    user_agent: str | None
    created_at: datetime
