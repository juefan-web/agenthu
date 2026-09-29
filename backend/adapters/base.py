"""Adapter contracts for external data sources.

Adapters are the *only* place that understands a provider's API. They emit
``NormalizedEvent`` objects that map 1:1 onto the shared Event contract. Secrets
(cookies, tokens, passwords) are supplied per-user at runtime and must never be
logged, persisted in the repository or committed.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from backend.db.base import utcnow
from backend.schemas.event import EventCreate


@dataclass(frozen=True)
class NormalizedEvent:
    """A provider-agnostic fact produced by an adapter."""

    type: str
    source: str
    timestamp: datetime
    data: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    dedupe_key: str | None = None


@dataclass
class AdapterCredentials:
    """Runtime credentials for a single user.

    ``secret`` holds short-lived material (session cookie, token) and is never
    persisted by the adapter layer. Persisting credentials is a later decision
    that must include encryption, access control and a deletion path.
    """

    secret: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class SourceAdapter(ABC):
    """Base class for external source adapters."""

    name: str = "adapter"

    @abstractmethod
    def fetch(
        self, *, user_id: uuid.UUID, credentials: AdapterCredentials | None = None
    ) -> list[NormalizedEvent]:
        """Return normalized events since the adapter's last sync point."""

    def health(self) -> dict[str, Any]:
        return {"name": self.name, "status": "unknown"}


def normalize_to_event_create(normalized: NormalizedEvent) -> EventCreate:
    """Convert an adapter result into the shared Event create contract."""

    return EventCreate(
        type=normalized.type,
        source=normalized.source,
        timestamp=normalized.timestamp or utcnow(),
        data=normalized.data,
        context=normalized.context,
        provenance=normalized.provenance,
        dedupe_key=normalized.dedupe_key,
    )
