"""E7-8 driver: permission-grant gates and the real notification channel.

Faces, each asserted on its real surface:

- 窄 scope grant: POST /permissions/grants creates a Level-3 grant for
  ``notify.push`` — the ONLY auto-level notification action in
  ACTION_POLICY. The seeded pg1 (``plan.auto_send``) is a pre-guard
  legacy row: the creation face refuses it today
  (validate_grant_action), so the live cycle runs on notify.push.
- 错 action 拒绝: unknown actions and fnmatch patterns are 422 at the
  creation face (validation_error).
- L2 不被自动通知: a level-2 action with no grant answers
  requires_confirmation (never auto) on POST /permissions/check.
- 到期/撤销阻发 (grant_revocation_blocks_send): DELETE the grant, the
  same check flips to denied.
- 实际渠道: ``settle_and_deliver`` is a service function with NO frozen
  HTTP route (contract §6 gate order category → quiet hours → budget);
  the driver calls it in-process against the acceptance DB — the same
  no-route/in-process precedent as E7-7's release. Budget is tightened
  to 1 via the real PATCH route first, so the four settlements are
  exactly: wrong category / quiet hours / delivered / budget exhausted.
- 两类 consent: PUT both consent faces to disabled (state flips, the
  rows persist — row counts unchanged; disabling needs no version echo).

Audit ledger (registered with the driver in the manifest): each
``/permissions/check`` writes one ``permission.check`` row and each
settlement writes exactly one ``notification.*`` row → 3 checks + 4
settlements = audit_logs +7. The grant row is NEVER deleted (D-034
soft-revoke keeps it) → permission_grants +1.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from backend.services.notification_delivery import settle_and_deliver
from tests.e7.conftest import login, verify_report, write_evidence

LOCAL_TZ = "Asia/Shanghai"

GRANT_SCOPE = {"categories": ["replan"], "channels": ["notification"], "daily_budget": 2}


def _local(hour: int, minute: int) -> datetime:
    return datetime(2026, 10, 12, hour, minute, tzinfo=ZoneInfo(LOCAL_TZ))


def test_e7_8_grant_gates_and_channel_settlement(
    e7_api, e7_fresh_world, e7_verifier, e7_engine
) -> None:  # type: ignore[no-untyped-def]
    headers = login(e7_api, e7_fresh_world, "U")
    user = e7_fresh_world.users["U"]
    evidence: dict = {"faces": []}

    # -- creation face: unknown action and fnmatch pattern are refused ----
    for bad_action in ("definitely.not.a.policy.action", "plan.*"):
        refused = e7_api.post(
            "/v1/permissions/grants",
            json={"action": bad_action, "level": 3, "scope": GRANT_SCOPE},
            headers=headers,
        )
        assert refused.status_code == 422, f"{bad_action}: {refused.text}"
    evidence["faces"].append({"face": "unknown-and-pattern-actions-refused", "status": 422})

    # -- narrow-scope Level-3 grant on the real auto-notification action --
    created = e7_api.post(
        "/v1/permissions/grants",
        json={"action": "notify.push", "level": 3, "scope": GRANT_SCOPE, "note": "E7-8 driver"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    grant = created.json()
    assert grant["revoked_at"] is None

    allowed = e7_api.post(
        "/v1/permissions/check",
        json={"action": "notify.push", "required_level": 3},
        headers=headers,
    )
    assert allowed.status_code == 200
    assert allowed.json()["allowed"] is True, allowed.text
    assert allowed.json()["requires_confirmation"] is False
    evidence["faces"].append({"face": "l3-grant-allows", "check": allowed.json()})

    # -- L2 never auto-notifies: confirm-first, no grant, no auto path ----
    level2 = e7_api.post(
        "/v1/permissions/check",
        json={"action": "task.create", "required_level": 2},
        headers=headers,
    )
    assert level2.status_code == 200
    assert level2.json()["allowed"] is False
    assert level2.json()["requires_confirmation"] is True, level2.text
    evidence["faces"].append({"face": "l2-requires-confirmation", "check": level2.json()})

    # -- revocation blocks the send authorization -------------------------
    revoked = e7_api.delete(f"/v1/permissions/grants/{grant['id']}", headers=headers)
    assert revoked.status_code == 204, revoked.text
    blocked = e7_api.post(
        "/v1/permissions/check",
        json={"action": "notify.push", "required_level": 3},
        headers=headers,
    )
    assert blocked.status_code == 200
    assert blocked.json()["allowed"] is False, blocked.text
    evidence["faces"].append({"face": "grant-revoked-blocks", "check": blocked.json()})

    # -- real channel gates (contract §6 order, budget tightened to 1) ----
    prefs = e7_api.get("/v1/notification-preferences", headers=headers)
    assert prefs.status_code == 200, prefs.text
    patched = e7_api.patch(
        "/v1/notification-preferences",
        json={"expected_version": prefs.json()["version"], "daily_budget": 1},
        headers=headers,
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["daily_budget"] == 1

    with Session(e7_engine) as session:
        settlements = [
            (
                "wrong-category",
                settle_and_deliver(
                    session, user_id=user.user_id, category="exercise", now=_local(12, 0)
                ),
            ),
            (
                "quiet-hours",
                settle_and_deliver(
                    session, user_id=user.user_id, category="replan", now=_local(23, 30)
                ),
            ),
            (
                "delivered",
                settle_and_deliver(
                    session, user_id=user.user_id, category="replan", now=_local(12, 0)
                ),
            ),
            (
                "budget-exhausted",
                settle_and_deliver(
                    session, user_id=user.user_id, category="replan", now=_local(12, 5)
                ),
            ),
        ]
        session.commit()
    by_face = dict(settlements)
    assert by_face["wrong-category"]["reason"] == "category_disabled", by_face
    assert by_face["quiet-hours"]["reason"] == "quiet_hours", by_face
    assert by_face["delivered"]["delivered"] is True, by_face
    assert by_face["budget-exhausted"]["reason"] == "budget_exhausted", by_face
    evidence["settlements"] = dict(settlements)

    # -- both consent faces: state flips, rows persist ---------------------
    grounding = e7_api.put(
        "/v1/grounding-consent",
        json={"course_name": "线性代数", "enabled": False, "consent_text_version": "v1"},
        headers=headers,
    )
    assert grounding.status_code == 200, grounding.text
    assert grounding.json()["enabled"] is False
    model_context = e7_api.put(
        "/v1/model-context-consent",
        json={"enabled": False, "consent_text_version": "v1"},
        headers=headers,
    )
    assert model_context.status_code == 200, model_context.text
    assert model_context.json()["enabled"] is False
    evidence["faces"].append({"face": "both-consents-disabled-rows-persist"})

    write_evidence("E7-8", "protocol.json", evidence)
    report = verify_report(e7_verifier, "E7-8")
    write_evidence("E7-8", "verify.json", report.to_dict())
