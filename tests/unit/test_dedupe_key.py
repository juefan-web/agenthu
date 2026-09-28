"""Dedupe key parity with the desktop client's ``eventDedupeKey`` (D-010).

The desktop contract escapes ``\\`` and ``:`` before joining the three parts, so
the Backend must use the same encoding. These tests pin the exact byte layout.
"""

from __future__ import annotations

from backend.services.events import compute_dedupe_key


def test_compute_dedupe_key_matches_client_format() -> None:
    assert (
        compute_dedupe_key("onethu", {"upstream_id": "hw-2", "semantic_version": "v1"})
        == "onethu:hw-2:v1"
    )


def test_compute_dedupe_key_escapes_colon_in_upstream_id() -> None:
    # The adapter emits upstream_id like "assignment:hw-1" and "course:<id>".
    key = compute_dedupe_key(
        "onethu", {"upstream_id": "assignment:hw-1", "semantic_version": "abc123"}
    )
    assert key == "onethu:assignment\\:hw-1:abc123"


def test_compute_dedupe_key_escapes_backslash_before_colon() -> None:
    key = compute_dedupe_key("a\\b", {"upstream_id": "u", "semantic_version": "v"})
    assert key == "a\\\\b:u:v"


def test_compute_dedupe_key_has_no_field_boundary_collision() -> None:
    escaped = compute_dedupe_key(
        "onethu", {"upstream_id": "assignment:hw-1", "semantic_version": "v1"}
    )
    shifted = compute_dedupe_key(
        "onethu:assignment", {"upstream_id": "hw-1", "semantic_version": "v1"}
    )
    assert escaped != shifted


def test_compute_dedupe_key_requires_upstream_and_semantic_version() -> None:
    assert compute_dedupe_key("onethu", {"upstream_id": "u"}) is None
    assert compute_dedupe_key("onethu", None) is None
