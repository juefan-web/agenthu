"""Permission layer shared by the API and the future Agent runtime.

Levels (fixed by ``AGENTS.md``)::

    Level 0  read-only
    Level 1  suggest
    Level 2  confirm before executing
    Level 3  auto-execute after explicit user authorization

User-initiated CRUD is performed by the user themselves and is implicitly
authorized. This layer gates *Agent/tool* actions: an action may only run
automatically when an active ``PermissionGrant`` covers it.
"""

from __future__ import annotations

import fnmatch
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.errors import ValidationError
from backend.models.enums import AuditActor, AuditDecision
from backend.models.permission import PermissionGrant
from backend.services.audit import record_audit


class PermissionLevel:
    READ = 0
    SUGGEST = 1
    CONFIRM = 2
    AUTO = 3


LEVEL_DESCRIPTIONS: dict[str, str] = {
    "0": "Read-only: observe and answer without side effects.",
    "1": "Suggest: propose actions but do not change anything.",
    "2": "Confirm: ask the user before executing.",
    "3": "Auto-execute after explicit, standing user authorization.",
}

# Action -> (required level, description). Agent tools resolve their level here.
ACTION_POLICY: dict[str, tuple[int, str]] = {
    "state.read": (PermissionLevel.READ, "Read current state, tasks and memory."),
    "plan.suggest": (PermissionLevel.SUGGEST, "Propose a study/work plan."),
    "plan.confirm": (PermissionLevel.CONFIRM, "Confirm and activate a plan."),
    # D-034 correction: starting a focus session on the user's behalf is a
    # side effect and may not run at suggest level. User-initiated focus via
    # the existing API/UI is implicitly authorized and unaffected.
    "focus.start": (PermissionLevel.CONFIRM, "Start a focus session."),
    "task.create": (PermissionLevel.CONFIRM, "Create a task on the user's behalf."),
    "task.update": (PermissionLevel.CONFIRM, "Modify a task on the user's behalf."),
    "memory.write": (PermissionLevel.CONFIRM, "Write a memory entry."),
    "calendar.write": (PermissionLevel.CONFIRM, "Create or modify calendar entries."),
    "message.send": (PermissionLevel.CONFIRM, "Send a message on the user's behalf."),
    "campus.import": (PermissionLevel.CONFIRM, "Import data from a campus source."),
    "file.delete": (PermissionLevel.CONFIRM, "Delete a stored file."),
    "data.delete": (PermissionLevel.CONFIRM, "Delete user data."),
    "notify.push": (PermissionLevel.AUTO, "Send proactive push notifications."),
    # M4 tool-registry rows (D-034): the read face stays Level 0; the
    # grounded-answers tool stays behind the D-033 consent gate regardless
    # of its policy level.
    "memory.retrieve": (PermissionLevel.READ, "Retrieve memory entries for agent context."),
    "goal.read": (PermissionLevel.READ, "Read the user's active goals."),
    "replan.evaluate": (
        PermissionLevel.SUGGEST,
        "Evaluate replan triggers and suggestions.",
    ),
    "materials.answer": (
        PermissionLevel.READ,
        "Answer a question from the user's course materials (D-033 gated).",
    ),
}
DEFAULT_REQUIRED_LEVEL = PermissionLevel.CONFIRM


@dataclass(frozen=True)
class PermissionDecision:
    action: str
    required_level: int
    granted_level: int
    decision: AuditDecision
    reason: str

    @property
    def allowed(self) -> bool:
        return self.decision == AuditDecision.ALLOW

    @property
    def requires_confirmation(self) -> bool:
        return self.decision == AuditDecision.REQUIRE_CONFIRMATION


def required_level_for(action: str) -> int:
    entry = ACTION_POLICY.get(action)
    return entry[0] if entry else DEFAULT_REQUIRED_LEVEL


# fnmatch metacharacters — a grant action containing any of these is a
# pattern, and the match side still interprets grant.action as one.
PATTERN_METACHARACTERS = "*?["


def validate_grant_action(action: str) -> None:
    """Creation-face guard (external review #11): grant actions are concrete
    ACTION_POLICY keys, never patterns.

    The match side historically treats grant.action as an fnmatch pattern,
    so a storable ``plan.*`` / ``*`` row IS a wildcard; D-034 §2.5 already
    stops patterns from elevating levels, and this guard stops new pattern
    rows from being minted at all (rows predating the guard keep their
    legacy match semantics). Unknown actions are inert in evaluation — the
    policy fallback answers CONFIRM regardless — so granting one only
    litters the table with rows that would go live if the policy later
    grows a same-named action; they are refused here.
    """

    metacharacters = sorted({char for char in action if char in PATTERN_METACHARACTERS})
    if metacharacters:
        raise ValidationError(
            f"grant action {action!r} contains fnmatch metacharacters "
            f"({''.join(metacharacters)}); grants are concrete actions, not patterns"
        )
    if action not in ACTION_POLICY:
        raise ValidationError(
            f"unknown action {action!r}; grant actions must be declared in "
            "ACTION_POLICY (see GET /v1/permissions/policy)"
        )


def _active_grants(session: Session, user_id: uuid.UUID) -> list[PermissionGrant]:
    now = datetime.now(UTC)
    stmt = select(PermissionGrant).where(
        PermissionGrant.user_id == user_id,
        PermissionGrant.revoked_at.is_(None),
    )
    grants = list(session.scalars(stmt))
    active: list[PermissionGrant] = []
    for grant in grants:
        if grant.expires_at is not None and grant.expires_at <= now:
            continue
        active.append(grant)
    return active


def _matching_grants(grants: list[PermissionGrant], action: str) -> list[PermissionGrant]:
    """Grants whose action key covers ``action`` (exact or fnmatch pattern).

    The pattern match only decides WHICH grants are candidates — since D-034
    §2.5 it can no longer elevate an action's level: a Level 3 grant never
    auto-executes a tool the registry declares Level 2.
    """

    return [
        grant for grant in grants if grant.action == action or fnmatch.fnmatch(action, grant.action)
    ]


def _default_scope_ok(scope: dict | None) -> bool:
    """Minimum bar for an auto-executable grant: a non-empty scope object.

    Empty scope is not a wildcard (contract §5.3); tool-specific validators
    (see the registry) additionally reject unknown fields and ``*``.
    """

    return isinstance(scope, dict) and len(scope) > 0


def _value_scope_ok(
    scope_matcher: Callable[[dict | None, Any], bool] | None,
    scope: dict | None,
    args: Any | None,
) -> bool:
    """Value-level §5.3 gate. No matcher supplied (args-less policy checks)
    keeps the shape-only policy answer; a matcher without concrete args can
    never value-match, so the action falls to confirmation — fail-closed."""

    if scope_matcher is None:
        return True
    if args is None:
        return False
    return scope_matcher(scope, args)


def evaluate_permission(
    session: Session,
    *,
    user_id: uuid.UUID | None,
    action: str,
    required_level: int | None = None,
    actor: str = AuditActor.AGENT.value,
    audit: bool = True,
    scope_validator: Callable[[dict | None], bool] | None = None,
    scope_matcher: Callable[[dict | None, Any], bool] | None = None,
    args: Any | None = None,
) -> PermissionDecision:
    """Tightened D-034 §2.5/§5.3 semantics.

    - Level 0/1: allowed outright (read/suggest cannot mutate).
    - Level 2: ALWAYS ``REQUIRE_CONFIRMATION`` — per-action user confirmation,
      every time. A Level 3 grant does not elevate a Level 2 tool (the
      M0-era ``granted >= required`` shortcut is retired).
    - Level 3: ``ALLOW`` only with an active, unrevoked, unexpired matching
      grant whose level is exactly 3, whose scope passes shape validation
      (``scope_validator``, else the non-empty default) AND — when the
      caller supplies the tool's ``scope_matcher`` — whose scope covers
      THIS call's ``args`` values (coordinator ruling 2026-10-04: a
      "deadline"-scoped grant must not auto-run a "replan" push). Without
      concrete ``args`` a value-scoped action never auto-allows here; the
      args-less ``/permissions/check`` face therefore stays policy-level
      (shape) while the runner and dispatch paths are value-level.
      Otherwise require confirmation.
    """

    required = required_level if required_level is not None else required_level_for(action)

    if required <= PermissionLevel.SUGGEST:
        decision = PermissionDecision(
            action=action,
            required_level=required,
            granted_level=PermissionLevel.READ,
            decision=AuditDecision.ALLOW,
            reason="read/suggest actions need no confirmation",
        )
    elif user_id is None:
        decision = PermissionDecision(
            action=action,
            required_level=required,
            granted_level=PermissionLevel.READ,
            decision=AuditDecision.DENY,
            reason="no user context",
        )
    else:
        matching = _matching_grants(_active_grants(session, user_id), action)
        granted = max((grant.level for grant in matching), default=PermissionLevel.READ)
        if required == PermissionLevel.AUTO:
            scope_ok = scope_validator or _default_scope_ok
            auto_grants = [
                grant
                for grant in matching
                if grant.level == PermissionLevel.AUTO
                and scope_ok(grant.scope)
                and _value_scope_ok(scope_matcher, grant.scope, args)
            ]
            if auto_grants:
                decision = PermissionDecision(
                    action=action,
                    required_level=required,
                    granted_level=PermissionLevel.AUTO,
                    decision=AuditDecision.ALLOW,
                    reason="active level-3 grant with scope covering this call",
                )
            else:
                decision = PermissionDecision(
                    action=action,
                    required_level=required,
                    granted_level=granted,
                    decision=AuditDecision.REQUIRE_CONFIRMATION,
                    reason="no level-3 grant whose scope covers this call; confirm",
                )
        else:
            decision = PermissionDecision(
                action=action,
                required_level=required,
                granted_level=granted,
                decision=AuditDecision.REQUIRE_CONFIRMATION,
                reason="level-2 actions always require per-action confirmation (D-034)",
            )

    if audit:
        record_audit(
            session,
            action="permission.check",
            actor=actor,
            user_id=user_id,
            resource_type="permission",
            permission_level=decision.required_level,
            decision=decision.decision.value,
            details={
                "checked_action": action,
                "required_level": decision.required_level,
                "granted_level": decision.granted_level,
                "reason": decision.reason,
            },
        )
    return decision
