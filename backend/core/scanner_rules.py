"""Versioned content-scanner rules for material chunks (D-033 §5).

Chunk text extracted from course files is untrusted input: a malicious slide
is a prompt-injection carrier. These rules implement the first defence layer
(ingestion-time scanning). Rule changes MUST bump ``SCANNER_VERSION`` — rows
in ``material_chunks`` record the version that scanned them, so "which rules
scanned this batch" stays answerable.

Two severities, per the frozen policy:

- ``HARD_BLOCK_PATTERNS`` — instruction-shaped content (ignore-previous-
  instructions variants, credential exfiltration phrasing). A chunk matching
  these after normalization is NOT stored (``blocked``).
- invisible-Unicode detection — zero-width / bidi-override characters. These
  only ``flag`` the chunk; the normalized text is re-scanned and stored unless
  the normalization reveals a hard-block pattern. PDF text layers legitimately
  contain such artifacts, so false positives are this layer's main risk and
  hard-rejecting here would block legal course material.

False-positive discipline: hard-block patterns must read as imperatives
directed at a model, not as topical discussion; generic role-play vocabulary
("act as", "pretend") is deliberately NOT blocked on its own.
"""

from __future__ import annotations

import re

SCANNER_VERSION = "2026-10-02.1"

# (rule_name, compiled pattern) — matched case-insensitively.
_HARD_BLOCK: list[tuple[str, re.Pattern[str]]] = [
    (
        "ignore_previous_instructions",
        re.compile(
            r"ignore\s+(?:all\s+)?(?:any\s+)?(?:previous|prior|above|earlier)"
            r"[\s\S]{0,24}?(?:instruction|prompt|rule|direction|guideline)s?\b",
            re.IGNORECASE,
        ),
    ),
    (
        "disregard_above",
        re.compile(
            r"disregard\s+(?:all\s+|any\s+|the\s+)?(?:above|previous|prior|preceding|earlier)"
            r"[\s\S]{0,24}?(?:instruction|prompt|rule|direction|context|message)s?\b",
            re.IGNORECASE,
        ),
    ),
    (
        "forget_instructions",
        re.compile(
            r"forget\s+(?:all\s+|everything\s+|anything\s+)?(?:above|previous|prior|earlier)?"
            r"[\s\S]{0,24}?(?:instruction|prompt|rule|direction)s?\b",
            re.IGNORECASE,
        ),
    ),
    (
        "system_prompt_override",
        re.compile(
            r"\b(?:you\s+are\s+now|switch\s+(?:in)?to|enter(?:ing)?|activate)\b"
            r"[\s\S]{0,32}?\b(?:developer\s+mode|system\s+mode|dan\s+mode"
            r"|unrestricted\s+mode|jailbreak(?:ed|\s+mode)?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "credential_exfiltration",
        re.compile(
            r"\b(?:reveal|show|share|send|print|output|repeat|leak)\b"
            r"[\s\S]{0,32}?\b(?:your\s+)?(?:system\s+prompt|initial\s+instructions"
            r"|api[\s-]?key|secret[\s-]?key|credentials|private\s+key)\b",
            re.IGNORECASE,
        ),
    ),
    (
        # 中文指令形态（课件以中文为主）。限定「忽略/无视 +（之前的）指令」
        # 形态；裸「忽略」讨论（如「忽略噪声」）不命中。
        "cn_ignore_previous",
        re.compile(
            r"(?:忽略|无视|不理会)(?:掉|所有|以上|上面|之前|以前|上述)?"
            r"[\s\S]{0,12}?(?:指令|指示|提示词?|规则|设定|命令)",
            re.IGNORECASE,
        ),
    ),
    (
        "cn_credential_exfiltration",
        re.compile(
            r"(?:发送|输出|透露|泄露|告诉我|打印)"
            r"[\s\S]{0,16}?(?:系统提示词?|初始指令|密钥|秘钥|凭据|口令|密码|API\s*密钥)",
            re.IGNORECASE,
        ),
    ),
    (
        "cn_developer_mode",
        re.compile(r"(?:开发者模式|越狱模式|无限制模式|你现在是系统模式)"),
    ),
]

# Compiled once at import; rule tuples are (name, pattern).
HARD_BLOCK_PATTERNS: list[tuple[str, re.Pattern[str]]] = _HARD_BLOCK

# Invisible / bidi-override Unicode. Zero-width chars are stripped during
# normalization; bidi controls are flags only (they change display order and
# survive no clean removal — the chunk stays flagged either way).
INVISIBLE_ZERO_WIDTH = "\u200b\u200c\u200d\u2060\ufeff"
BIDI_CONTROLS = "\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"

FLAG_INVISIBLE_CHARS = "invisible_characters"
FLAG_BIDI_CONTROLS = "bidi_controls"
