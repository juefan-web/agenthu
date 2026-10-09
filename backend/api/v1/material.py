"""Per-course grounding consent (D-033 decision 4: default OFF).

The switch gates every provider call that carries course-material text.
Opting in requires echoing the CURRENT consent text version, so a text
update forces re-confirmation instead of silently inheriting old consent.
Opting in enqueues an embedding backfill for the course's existing clean
chunks; opting out stops new calls but keeps already-computed embeddings
(local data — deletion is a separate, Level-2 action).
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import select

from backend.api.deps import CurrentUser, DBSession
from backend.core.errors import ValidationError
from backend.db.base import utcnow
from backend.models.material import GroundingConsent
from backend.schemas.material import (
    CONSENT_TEXT,
    CONSENT_TEXT_VERSION,
    GroundingConsentRead,
    GroundingConsentUpdate,
)
from backend.worker.queue import enqueue, get_arq_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/grounding-consent", tags=["grounding-consent"])


def _read(course_name: str, row: GroundingConsent | None) -> GroundingConsentRead:
    return GroundingConsentRead(
        course_name=course_name,
        enabled=row.enabled if row is not None else False,
        consent_text=CONSENT_TEXT,
        consent_text_version=CONSENT_TEXT_VERSION,
        consented_at=row.consented_at if row is not None else None,
    )


def _get_row(db: DBSession, user_id, course_name: str) -> GroundingConsent | None:
    return db.scalar(
        select(GroundingConsent).where(
            GroundingConsent.user_id == user_id,
            GroundingConsent.course_name == course_name,
        )
    )


CourseNameQuery = Annotated[str, Query(min_length=1, max_length=300)]


@router.get("", response_model=GroundingConsentRead)
def get_consent(
    course_name: CourseNameQuery,
    user: CurrentUser,
    db: DBSession,
) -> GroundingConsentRead:
    """Current consent state plus the exact text the client must render."""

    return _read(course_name, _get_row(db, user.id, course_name))


@router.put("", response_model=GroundingConsentRead)
async def set_consent(
    payload: GroundingConsentUpdate,
    user: CurrentUser,
    db: DBSession,
) -> GroundingConsentRead:
    if payload.enabled and payload.consent_text_version != CONSENT_TEXT_VERSION:
        raise ValidationError(
            "Consent text has been updated; re-read the current text and "
            "confirm again (echo its consent_text_version)."
        )

    row = _get_row(db, user.id, payload.course_name)
    if row is None:
        row = GroundingConsent(
            user_id=user.id,
            course_name=payload.course_name,
            consent_text_version=payload.consent_text_version,
        )
        db.add(row)
    row.enabled = payload.enabled
    row.consent_text_version = payload.consent_text_version
    if payload.enabled:
        row.consented_at = utcnow()
        row.revoked_at = None
    else:
        row.revoked_at = utcnow()
    db.flush()

    if payload.enabled:
        try:
            pool = await get_arq_pool()
            await enqueue(pool, "embed_course_backfill", str(user.id), payload.course_name)
        except Exception:
            # The switch is on; the backfill can be retried (a future upload
            # or re-save re-enqueues) — log and let the state stand.
            logger.warning(
                "Embedding backfill enqueue failed",
                extra={"course_name": payload.course_name},
            )
    return _read(payload.course_name, row)
