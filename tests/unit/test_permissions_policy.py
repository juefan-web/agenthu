from __future__ import annotations

import pytest

from backend.core.errors import ValidationError
from backend.services.permissions import (
    ACTION_POLICY,
    DEFAULT_REQUIRED_LEVEL,
    LEVEL_DESCRIPTIONS,
    PermissionLevel,
    required_level_for,
    validate_grant_action,
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


def test_every_policy_action_is_grantable() -> None:
    # External review #11: the creation face must accept exactly the
    # ACTION_POLICY keys — no key may be accidentally rejected by the guard.
    for action in ACTION_POLICY:
        validate_grant_action(action)


@pytest.mark.parametrize("action", ["plan.*", "task.?", "data.[x]", "*"])
def test_grant_action_rejects_fnmatch_patterns(action: str) -> None:
    with pytest.raises(ValidationError, match="metacharacters"):
        validate_grant_action(action)


def test_grant_action_rejects_unknown_actions() -> None:
    with pytest.raises(ValidationError, match="unknown action"):
        validate_grant_action("does.not.exist")
