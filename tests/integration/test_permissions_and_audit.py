from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_permission_policy_exposes_levels(client, auth_headers) -> None:
    response = client.get("/v1/permissions/policy", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert set(body["levels"]) == {"0", "1", "2", "3"}
    actions = {entry["action"]: entry["level"] for entry in body["actions"]}
    assert actions["plan.confirm"] == 2
    assert actions["state.read"] == 0


def test_confirm_always_requires_confirmation_even_with_grant(client, auth_headers) -> None:
    """D-034 §2.5 tightening: a Level 3 grant never elevates a Level 2
    action — ``plan.confirm`` asks for confirmation on every execution, with
    or without a covering grant. The M0-era ``granted >= required`` shortcut
    is retired."""

    check = client.post(
        "/v1/permissions/check",
        json={"action": "plan.confirm"},
        headers=auth_headers,
    ).json()
    assert check["allowed"] is False
    assert check["requires_confirmation"] is True
    assert check["required_level"] == 2

    grant = client.post(
        "/v1/permissions/grants",
        json={"action": "plan.confirm", "level": 3, "note": "auto-confirm study plans"},
        headers=auth_headers,
    )
    assert grant.status_code == 201

    after_grant = client.post(
        "/v1/permissions/check",
        json={"action": "plan.confirm"},
        headers=auth_headers,
    ).json()
    assert after_grant["allowed"] is False
    assert after_grant["requires_confirmation"] is True
    assert after_grant["granted_level"] == 3

    assert (
        client.delete(
            f"/v1/permissions/grants/{grant.json()['id']}", headers=auth_headers
        ).status_code
        == 204
    )
    after_revoke = client.post(
        "/v1/permissions/check",
        json={"action": "plan.confirm"},
        headers=auth_headers,
    ).json()
    assert after_revoke["allowed"] is False


def test_read_only_action_needs_no_confirmation(client, auth_headers) -> None:
    check = client.post(
        "/v1/permissions/check",
        json={"action": "state.read"},
        headers=auth_headers,
    ).json()
    assert check["allowed"] is True
    assert check["requires_confirmation"] is False


def test_permission_decisions_are_audited(client, auth_headers) -> None:
    client.post("/v1/permissions/check", json={"action": "plan.confirm"}, headers=auth_headers)
    audit = client.get("/v1/audit", params={"action": "permission.check"}, headers=auth_headers)
    assert audit.status_code == 200
    assert audit.json()["total"] >= 1
    entry = audit.json()["items"][0]
    assert entry["decision"] in {"allow", "require_confirmation", "deny"}
    assert entry["details"]["checked_action"] == "plan.confirm"


def test_grant_creation_rejects_patterns_and_unknown_actions(client, auth_headers) -> None:
    """External review #11: grant actions are concrete ACTION_POLICY keys.
    The match side interprets grant.action as an fnmatch pattern, so a
    storable wildcard row would be a live wildcard; the creation face refuses
    new pattern rows (rows predating the guard keep legacy semantics — pinned
    in test_m4_runtime.py::test_l3_grant_never_elevates_l2_even_wildcard)."""

    for action in ("plan.*", "task.?", "data.[x]", "*"):
        rejected = client.post(
            "/v1/permissions/grants",
            json={"action": action, "level": 3, "scope": {"categories": ["plan"]}},
            headers=auth_headers,
        )
        assert rejected.status_code == 422, (action, rejected.text)
        assert rejected.json()["error"]["code"] == "validation_error"

    unknown = client.post(
        "/v1/permissions/grants",
        json={"action": "does.not.exist", "level": 3, "scope": {"categories": ["plan"]}},
        headers=auth_headers,
    )
    assert unknown.status_code == 422
    assert unknown.json()["error"]["code"] == "validation_error"

    # Concrete policy keys still land: the upsert face is otherwise unchanged.
    ok = client.post(
        "/v1/permissions/grants",
        json={"action": "task.update", "level": 2, "scope": {"task_ids": []}},
        headers=auth_headers,
    )
    assert ok.status_code == 201
