"""Global "Agent model context" consent endpoints (D-034 §6.2, default OFF).

GET returns the current state plus the exact text the client must render;
PUT enforces the version-echo rule (an opt-in carrying a stale
``consent_text_version`` is rejected so text updates force re-confirmation).
Same pattern as the M3 per-course grounding consent (``/v1/grounding-consent``).
"""

from __future__ import annotations

from fastapi import APIRouter

from backend.api.deps import CurrentUser, DBSession
from backend.core.errors import ValidationError
from backend.models.consent import ModelContextConsent
from backend.schemas.consent import (
    MODEL_CONTEXT_CONSENT_TEXT,
    MODEL_CONTEXT_CONSENT_TEXT_VERSION,
    ModelContextConsentRead,
    ModelContextConsentUpdate,
)
from backend.services.model_consent import get_consent_row, set_consent

router = APIRouter(prefix="/model-context-consent", tags=["model-context-consent"])


def _read(row: ModelContextConsent | None) -> ModelContextConsentRead:
    return ModelContextConsentRead(
        enabled=row.enabled if row is not None else False,
        consent_text=MODEL_CONTEXT_CONSENT_TEXT,
        consent_text_version=MODEL_CONTEXT_CONSENT_TEXT_VERSION,
        consented_at=row.consented_at if row is not None else None,
    )


@router.get("", response_model=ModelContextConsentRead)
def get_model_context_consent(user: CurrentUser, db: DBSession) -> ModelContextConsentRead:
    """Current consent state plus the exact text the client must render."""

    return _read(get_consent_row(db, user.id))


@router.put("", response_model=ModelContextConsentRead)
def put_model_context_consent(
    payload: ModelContextConsentUpdate,
    user: CurrentUser,
    db: DBSession,
) -> ModelContextConsentRead:
    if payload.enabled and payload.consent_text_version != MODEL_CONTEXT_CONSENT_TEXT_VERSION:
        raise ValidationError(
            "Consent text has been updated; re-read the current text and "
            "confirm again (echo its consent_text_version)."
        )
    row = set_consent(
        db,
        user.id,
        enabled=payload.enabled,
        consent_text_version=payload.consent_text_version,
    )
    return _read(row)
