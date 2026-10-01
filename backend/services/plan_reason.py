"""Human-readable plan-item reasons rendered from the structured basis.

D-031 §1: the basis is the record, the reason is a view. Rendering lives here
so the planner never stores prose and the client contract's `reason` string is
always derivable from auditable data. Legacy items without a basis fall back
to the pre-v2 chain (notes -> replan_reason -> "planned").
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from backend.config import get_settings

_ESTIMATE_SOURCE_SUFFIX = {
    "user": "（你设置的估时）",
    "learned:course": "（按你近 {count} 次同课程作业实际用时）",
    "learned:ratio": "（按个人校准比推算）",
}


def _human_deadline(deadline: datetime, now: datetime) -> str | None:
    timezone = ZoneInfo(get_settings().default_timezone)
    local = deadline.astimezone(timezone)
    today = now.astimezone(timezone).date()
    if local.date() == today:
        prefix = "今天"
    elif local.date() == today + timedelta(days=1):
        prefix = "明天"
    else:
        prefix = f"{local.month}月{local.day}日"
    return f"{prefix} {local:%H:%M}"


def render_reason(
    basis: dict | None,
    *,
    planned_start: datetime | None,
    planned_end: datetime | None,
    now: datetime,
) -> str | None:
    """Chinese human sentence from a v2 basis; None when the basis carries no
    renderable v2 fields (caller falls back to the legacy chain)."""

    if not isinstance(basis, dict) or not basis.get("estimate_source"):
        return None
    timezone = ZoneInfo(get_settings().default_timezone)
    parts: list[str] = []

    deadline_raw = basis.get("deadline")
    if isinstance(deadline_raw, str):
        try:
            deadline = datetime.fromisoformat(deadline_raw)
        except ValueError:
            deadline = None
        if deadline is not None:
            deadline_text = _human_deadline(deadline, now)
            suffix = _ESTIMATE_SOURCE_SUFFIX.get(str(basis["estimate_source"]), "")
            if basis["estimate_source"] == "learned:course":
                suffix = suffix.format(count=basis.get("sample_count") or "")
            parts.append(f"{deadline_text}截止")
            estimate_minutes = basis.get("estimate_minutes")
            if isinstance(estimate_minutes, int):
                parts.append(f"预计 {estimate_minutes} 分钟{suffix}")

    slack = basis.get("slack_minutes")
    if planned_start is not None and planned_end is not None:
        window = (
            f"{planned_start.astimezone(timezone):%H:%M}–{planned_end.astimezone(timezone):%H:%M}"
        )
        if basis.get("slot_reason") == "今天最长空档":
            parts.append(f"{window} 是今天最长空档")
        elif isinstance(slack, int) and slack < 0:
            parts.append(f"{window} 补进度（已过截止）")
        else:
            parts.append(f"安排在 {window}")

    if not parts:
        return None
    return "；".join(parts) + "。"
