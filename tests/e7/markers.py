"""Synthetic marker scheme for the E7 seed world.

Every seeded content row carries per-user tokens (``E7MARK-U-001`` /
``E7MARK-V-001``). U and V get same-*shaped* content (same filenames, same
title pattern) with different tokens, so leak scans can distinguish owners:
after any operation, a U token must not appear outside U's allowed survivor
surfaces. Tokens are synthetic fixture strings, never real secrets
(m5-e7-acceptance §1: "用synthetic unique marker查内容泄漏，不用真实secret").
"""

from __future__ import annotations

MARKER_PREFIXES = {"U": "E7MARK-U-", "V": "E7MARK-V-"}


def marker(user: str, n: int) -> str:
    """Deterministic token; ``n`` is allocated by seed_spec in build order."""

    return f"{MARKER_PREFIXES[user]}{n:03d}"


def marker_prefix(user: str) -> str:
    return MARKER_PREFIXES[user]
