from __future__ import annotations

from backend.services.permissions import (
    ACTION_POLICY,
    DEFAULT_REQUIRED_LEVEL,
    LEVEL_DESCRIPTIONS,
    PermissionLevel,
    required_level_for,
)


def test_level_descriptions_cover_all_levels() -> None:
    assert set(LEVEL_DESCRIPTIONS) == {"0", "1", "2", "3"}


def test_known_actions_resolve_to_declared_level() -> None:
    for action, (level, _description) in ACTION_POLICY.items():
        assert required_level_for(action) == level


def test_unknown_action_defaults_to_confirm() -> None:
    assert required_level_for("does.not.exist") == DEFAULT_REQUIRED_LEVEL
    assert DEFAULT_REQUIRED_LEVEL == PermissionLevel.CONFIRM


def test_irreversible_actions_require_confirmation_or_more() -> None:
    for action in ("data.delete", "message.send", "calendar.write"):
        assert required_level_for(action) >= PermissionLevel.CONFIRM
