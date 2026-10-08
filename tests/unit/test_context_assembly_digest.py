"""State-digest unit regression (audit 四-1, slice beta).

``_render_state`` reads ``digest["state_version"]`` unconditionally; the
digest used to rely on every caller patching the key in out-of-band, so a
new caller that forgot the patch would KeyError at render time.
"""

from __future__ import annotations

from types import SimpleNamespace

from backend.services.context_assembly import _render_state, _state_digest


def _state(version: int = 7) -> SimpleNamespace:
    return SimpleNamespace(
        version=version,
        current_context={"label": "library"},
        available_minutes=90,
        current_task_id=None,
        current_plan_id=None,
        pending_task_ids=["t-1"],
    )


def test_state_digest_carries_state_version_itself() -> None:
    digest = _state_digest(_state(version=12))
    assert digest["state_version"] == 12


def test_render_state_works_straight_off_the_digest() -> None:
    state = _state(version=3)
    rendered = _render_state(_state_digest(state))
    assert "- version: 3" in rendered
    assert "- context: library" in rendered
    assert "- pending_tasks: 1" in rendered
