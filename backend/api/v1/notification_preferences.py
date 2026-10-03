"""Notification preference read/patch face (D-034, M4-A1).

GET lazily materializes the default row (contract §8 initial values:
budget 3/day, quiet hours unset, timezone Asia/Shanghai). PATCH carries
``expected_version`` — a mismatch is a 409 with the current row so two
clients never silently overwrite each other. The server-owned settlement
fields (``sent_count``/``budget_date``/``last_sent_at``) are never accepted
here; the A3 slice owns their atomic per-local-day settlement.
"""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from backend.api.deps import CurrentUser, DBSession
from backend.core.errors import ConflictError, ValidationError
from backend.models.notification import NotificationPreference
from backend.schemas.notification import (
    NotificationPreferencesPatch,
    NotificationPreferencesRead,
)

router = APIRouter(prefix="/notification-preferences", tags=["notifications"])


def _get_or_create(db, user_id) -> NotificationPreference:
    row = db.scalar(select(NotificationPreference).where(NotificationPreference.user_id == user_id))
    if row is None:
        row = NotificationPreference(user_id=user_id)
        db.add(row)
        db.flush()
    return row


@router.get("", response_model=NotificationPreferencesRead)
def get_preferences(user: CurrentUser, db: DBSession) -> NotificationPreferencesRead:
    return NotificationPreferencesRead.model_validate(_get_or_create(db, user.id))


@router.patch("", response_model=NotificationPreferencesRead)
def patch_preferences(
    payload: NotificationPreferencesPatch, user: CurrentUser, db: DBSession
) -> NotificationPreferencesRead:
    row = _get_or_create(db, user.id)
    if row.version != payload.expected_version:
        raise ConflictError(
            "Notification preferences were modified by another client; "
            "retry with the current version"
        )
    # model_fields_set distinguishes "absent" from "explicit null" so a
    # client can clear quiet hours by sending null. The merged values are
    # validated BEFORE any attribute is assigned: a rejected PATCH must not
    # leave a dirty row that a later request's autoflush would write.
    provided = payload.model_fields_set
    new_start = (
        payload.quiet_hours_start if "quiet_hours_start" in provided else row.quiet_hours_start
    )
    new_end = payload.quiet_hours_end if "quiet_hours_end" in provided else row.quiet_hours_end
    if (new_start is None) != (new_end is None):
        raise ValidationError("quiet hours must be set or cleared as a pair")
    row.quiet_hours_start = new_start
    row.quiet_hours_end = new_end
    if "timezone" in provided and payload.timezone is not None:
        row.timezone = payload.timezone
    if "enabled_categories" in provided and payload.enabled_categories is not None:
        row.enabled_categories = payload.enabled_categories
    if "daily_budget" in provided and payload.daily_budget is not None:
        row.daily_budget = payload.daily_budget
    row.version += 1
    db.flush()
    return NotificationPreferencesRead.model_validate(row)
