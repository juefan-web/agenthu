"""Global "Agent model context" consent (D-034 §6.2, default OFF).

One row per user. This is the single gate for sending CurrentState, Memory
and chat content to any model provider: without an active row the runner
forces ``capability: "none"`` (deterministic-only) and every provider call
that would carry user context is skipped — asserted by call count in the
regression suite. The shape deliberately mirrors ``grounding_consents``
(consent-text version echo, consented/revoked timestamps) so a text update
forces re-confirmation instead of silently inheriting old consent.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ModelContextConsent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "model_context_consents"
    __table_args__ = (UniqueConstraint("user_id", name="uq_model_context_consents_user"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Version of the consent text the user last acted on; opting in must echo
    # the CURRENT version (stale echoes are rejected — see the API layer).
    consent_text_version: Mapped[str] = mapped_column(String(32), nullable=False)
    consented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
