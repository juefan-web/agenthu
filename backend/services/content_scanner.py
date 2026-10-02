"""Ingestion-time content scanner (D-033 §5, first defence layer).

Pure function over text — no DB, no I/O — so the adversarial fixtures in the
test suite cover it exhaustively. Policy (frozen in scanner_rules.py):

- hard-block pattern present (raw or after invisible-char normalization)
  → ``blocked``; the caller must NOT persist the chunk.
- invisible/bidi characters present but no hard-block after normalization
  → ``flagged``; persist the *normalized* text with flags recorded.
- otherwise → ``clean``.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from backend.core.scanner_rules import (
    BIDI_CONTROLS,
    FLAG_BIDI_CONTROLS,
    FLAG_INVISIBLE_CHARS,
    HARD_BLOCK_PATTERNS,
    INVISIBLE_ZERO_WIDTH,
    SCANNER_VERSION,
)


@dataclass(frozen=True)
class ScanOutcome:
    status: str  # "clean" | "flagged" | "blocked"
    flags: list[str]
    content: str  # normalized text to persist (== raw when nothing to strip)
    scanner_version: str


def normalize_text(raw: str) -> str:
    """Strip zero-width characters and apply NFC.

    Bidi controls are NOT stripped — they reorder display, so removal can
    silently change meaning; they only flag. NFC folds the PDF-ligature /
    compatibility-form family into canonical forms so pattern matching and
    later citation verification see one representation.
    """

    stripped = raw.translate({ord(c): None for c in INVISIBLE_ZERO_WIDTH})
    return unicodedata.normalize("NFC", stripped)


def _hard_block_hits(text: str) -> list[str]:
    return [name for name, pattern in HARD_BLOCK_PATTERNS if pattern.search(text)]


def scan_text(raw: str) -> ScanOutcome:
    """Scan one chunk of extracted text. See module docstring for policy."""

    flags: list[str] = []
    if any(c in raw for c in INVISIBLE_ZERO_WIDTH):
        flags.append(FLAG_INVISIBLE_CHARS)
    if any(c in raw for c in BIDI_CONTROLS):
        flags.append(FLAG_BIDI_CONTROLS)

    # Instruction shapes are checked on the raw text first (visible payloads
    # need no obfuscation to be dangerous) and again after normalization
    # (zero-width stuffing is the classic evasion).
    hits = _hard_block_hits(raw)
    normalized = normalize_text(raw) if flags else raw
    if not hits:
        hits = _hard_block_hits(normalized)

    if hits:
        return ScanOutcome(
            status="blocked",
            flags=[*flags, *hits],
            content=normalized,
            scanner_version=SCANNER_VERSION,
        )
    return ScanOutcome(
        status="flagged" if flags else "clean",
        flags=flags,
        content=normalized,
        scanner_version=SCANNER_VERSION,
    )
