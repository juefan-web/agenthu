from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_permission_policy_exposes_levels(client, auth_headers) -> None:
    response = client.get("/api/v1/permissions/policy", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert set(body["levels"]) == {"0", "1", "2", "3"}
    actions = {entry["action"]: entry["level"] for entry in body["actions"]}
    assert actions["plan.confirm"] == 2
    assert actions["state.read"] == 0


def test_confirm_requires_grant_then_is_allowed(client, auth_headers) -> None:
    check = client.post(
        "/api/v1/permissions/check",
        json={"action": "plan.confirm"},
        headers=auth_headers,
    ).json()
    assert check["allowed"] is False
    assert check["requires_confirmation"] is True
    assert check["required_level"] == 2

    grant = client.post(
        "/api/v1/permissions/grants",
        json={"action": "plan.confirm", "level": 3, "note": "auto-confirm study plans"},
        headers=auth_headers,
    )
    assert grant.status_code == 201

    allowed = client.post(
        "/api/v1/permissions/check",
        json={"action": "plan.confirm"},
        headers=auth_headers,
    ).json()
    assert allowed["allowed"] is True

    assert (
        client.delete(
            f"/api/v1/permissions/grants/{grant.json()['id']}", headers=auth_headers
        ).status_code
        == 204
    )
    after_revoke = client.post(
        "/api/v1/permissions/check",
        json={"action": "plan.confirm"},
        headers=auth_headers,
    ).json()
    assert after_revoke["allowed"] is False


def test_read_only_action_needs_no_confirmation(client, auth_headers) -> None:
    check = client.post(
        "/api/v1/permissions/check",
        json={"action": "state.read"},
        headers=auth_headers,
    ).json()
    assert check["allowed"] is True
    assert check["requires_confirmation"] is False


def test_permission_decisions_are_audited(client, auth_headers) -> None:
    client.post("/api/v1/permissions/check", json={"action": "plan.confirm"}, headers=auth_headers)
    audit = client.get("/api/v1/audit", params={"action": "permission.check"}, headers=auth_headers)
    assert audit.status_code == 200
    assert audit.json()["total"] >= 1
    entry = audit.json()["items"][0]
    assert entry["decision"] in {"allow", "require_confirmation", "deny"}
    assert entry["details"]["checked_action"] == "plan.confirm"
