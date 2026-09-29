"""OneTHU adapter skeleton.

The adapter contract is implemented, but data acquisition is intentionally not
wired up in M0. When the provider's technical and authorization boundaries are
confirmed, ``fetch`` should translate provider DTOs into ``NormalizedEvent``
instances and nothing more. The rest of the Backend must never see provider
types.
"""

from __future__ import annotations

import uuid

from backend.adapters.base import AdapterCredentials, NormalizedEvent, SourceAdapter
from backend.core.errors import ServiceUnavailableError


class OneTHUAdapter(SourceAdapter):
    name = "onethu"

    def fetch(
        self, *, user_id: uuid.UUID, credentials: AdapterCredentials | None = None
    ) -> list[NormalizedEvent]:
        raise ServiceUnavailableError(
            "OneTHU adapter is not implemented in M0; see adapters/onethu/RESEARCH.md"
        )

    def health(self) -> dict[str, object]:
        return {"name": self.name, "status": "not_implemented", "milestone": "M1+"}
