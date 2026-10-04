"""Disturbance-budget settlement for Level-3 notifications (D-034 §6/§8).

One function, one transaction: ``settle_and_deliver`` is the only writer of
the server-owned settlement fields (``sent_count``/``budget_date``/
``last_sent_at``). It settles AT THE MOMENT OF DELIVERY — creating a
pending notification action is free (user confirmation may still veto it);
only an actual push pays the budget.

Gate order (contract §6): category enabled -> quiet hours -> daily budget.
The budget day is the USER-LOCAL day derived from ``timezone``; a stale
``budget_date`` rolls over (``sent_count`` reset) inside the same locked
transaction, so a delivery at local midnight can never double-charge or
double-reset. Suppression is policy working as intended, not a failure:
callers report it as an honest outcome with the reason.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.base import utcnow
from backend.models.notification import NotificationPreference
from backend.services.audit import record_audit

SUPPRESSED_CATEGORY_DISABLED = "category_disabled"
SUPPRESSED_QUIET_HOURS = "quiet_hours"
SUPPRESSED_BUDGET_EXHAUSTED = "budget_exhausted"

_SUPPRESS_SUMMARIES = {
    SUPPRESSED_CATEGORY_DISABLED: "category is not enabled in preferences",
    SUPPRESSED_QUIET_HOURS: "quiet hours are active",
    SUPPRESSED_BUDGET_EXHAUSTED: "daily budget exhausted",
}


def _local_time(prefs: NotificationPreference, now: datetime) -> time:
    return now.astimezone(ZoneInfo(prefs.timezone)).timetz()


def _parse_hhmm(value: str) -> time:
    return datetime.strptime(value, "%H:%M").time()


def _in_quiet_hours(local: time, start: str, end: str) -> bool:
    """Window membership in local wall-clock terms. A window crossing
    midnight (22:00 -> 07:00) is legal; ``start == end`` is a zero-length
    window (never quiet) rather than an ambiguous 24h one."""

    begin = _parse_hhmm(start)
    finish = _parse_hhmm(end)
    if begin == finish:
        return False
    if begin < finish:
        return begin <= local < finish
    return local >= begin or local < finish  # crosses midnight


def settle_and_deliver(
    session: Session,
    *,
    user_id: uuid.UUID,
    category: str,
    pending_action_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Atomically gate + charge one notification delivery. Returns
    ``{"delivered": bool, "reason": str | None, "summary": str}``; the
    summary is the honest user-facing outcome either way."""

    now = now or utcnow()
    prefs = session.scalar(
        select(NotificationPreference)
        .where(NotificationPreference.user_id == user_id)
        .with_for_update()
    )
    if prefs is None or category not in prefs.enabled_categories:
        # No preferences row == factory state == nothing enabled (§8
        # defaults); do NOT materialize a row just to refuse a delivery.
        return _suppressed(
            session,
            user_id,
            category,
            SUPPRESSED_CATEGORY_DISABLED,
            pending_action_id,
        )

    local_today = now.astimezone(ZoneInfo(prefs.timezone)).date()
    if prefs.budget_date != local_today:
        prefs.budget_date = local_today
        prefs.sent_count = 0

    reason: str | None = None
    if (
        prefs.quiet_hours_start is not None
        and prefs.quiet_hours_end is not None
        and _in_quiet_hours(_local_time(prefs, now), prefs.quiet_hours_start, prefs.quiet_hours_end)
    ):
        reason = SUPPRESSED_QUIET_HOURS
    elif prefs.sent_count >= prefs.daily_budget:
        reason = SUPPRESSED_BUDGET_EXHAUSTED

    if reason is not None:
        return _suppressed(session, user_id, category, reason, pending_action_id)

    prefs.sent_count += 1
    prefs.last_sent_at = now
    record_audit(
        session,
        action="notification.delivered",
        actor="agent",
        user_id=user_id,
        resource_type="notification",
        resource_id=str(pending_action_id) if pending_action_id is not None else None,
        details={
            "category": category,
            "sent_count": prefs.sent_count,
            "daily_budget": prefs.daily_budget,
            "budget_date": local_today.isoformat(),
        },
    )
    return {
        "delivered": True,
        "reason": None,
        "summary": f"Notification delivered ({prefs.sent_count}/{prefs.daily_budget} today)",
    }


def _suppressed(
    session: Session,
    user_id: uuid.UUID,
    category: str,
    reason: str,
    pending_action_id: uuid.UUID | None,
) -> dict[str, Any]:
    record_audit(
        session,
        action="notification.suppressed",
        actor="agent",
        user_id=user_id,
        resource_type="notification",
        resource_id=str(pending_action_id) if pending_action_id is not None else None,
        details={"category": category, "reason": reason},
    )
    return {
        "delivered": False,
        "reason": reason,
        "summary": f"Notification suppressed: {_SUPPRESS_SUMMARIES[reason]}",
    }
