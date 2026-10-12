"""E7-5 driver: account deletion racing the worker pipelines.

Accept ``kind=account`` with Level-2 confirm: the account deactivates in
the confirm transaction, the receipt capability issues EXACTLY ONCE on
the accepting 202, and business auth is closed from then on — the narrow
receipt path (capability in the Authorization header, never the URL) is
the only live read while the worker executes the whole-domain closure.

Race injection (op2 与 worker 在 context/dispatch/embed/写回各注入竞态):
U is SADDed to the trigger wake-up set right after the accept and again
mid-flight, so the 30s trigger drain and the agent-runtime sweeps overlap
the deletion's fence/relational/objects phases on the worker's own clock.
The oracle is the frozen-closure + exact-negative pair: closure ids froze
at confirm, so any row a racing pipeline manages to write SURVIVES the
frozen sweep and flips the exact count negatives red. No fake timing, no
monkeypatch — real concurrency on the real stack.

Driver-asserted invariants: receipt_issued_once (single DataReceipt row,
digest == sha256 of the one-time capability) and
single_effective_worker_claim (one operation; every cleanup item DONE
exactly once within the frozen ladder).
"""

from __future__ import annotations

import hashlib
import time

from sqlalchemy import text

from tests.e7.conftest import (
    confirm_target,
    login,
    mark_user_dirty,
    verify_report,
    write_evidence,
)


def test_e7_5_account_deletion_with_worker_races(
    e7_api, e7_fresh_world, e7_verifier, e7_engine
) -> None:  # type: ignore[no-untyped-def]
    user = e7_fresh_world.users["U"]
    observer_headers = login(e7_api, e7_fresh_world, "V")
    headers = login(e7_api, e7_fresh_world, "U")

    _preview, operation = confirm_target(
        e7_api, headers, target={"kind": "account"}, key="e7-5-confirm"
    )
    capability = operation["receipt_capability"]
    receipt_id = operation["receipt_id"]
    assert capability, operation
    assert receipt_id, operation

    # Deactivated at confirm: business auth is closed from here on. The
    # visibility poll waits out the post-202 commit window (see
    # conftest.wait_operation) — the deactivation itself is not in doubt.
    me_deadline = time.monotonic() + 10.0
    while True:
        me = e7_api.get("/v1/auth/me", headers=headers)
        if me.status_code == 401:
            break
        assert me.status_code == 200, me.text
        assert time.monotonic() < me_deadline, f"account stayed active: {me.text}"
        time.sleep(0.25)

    # Anti-enumeration: a wrong capability gets the uniform 404.
    wrong = e7_api.get(
        f"/v1/data/receipts/{receipt_id}",
        headers={"Authorization": "Bearer not-the-capability"},
    )
    assert wrong.status_code == 404, wrong.text

    # Race injection: dirty at accept, dirty again mid-flight (the drain
    # consumes the member; re-mark so a later sweep overlaps too).
    mark_user_dirty(str(user.user_id))
    re_marked = False
    started = time.monotonic()

    receipt: dict = {}
    while time.monotonic() - started < 300.0:
        response = e7_api.get(
            f"/v1/data/receipts/{receipt_id}",
            headers={"Authorization": f"Bearer {capability}"},
        )
        if response.status_code == 404:
            time.sleep(0.5)
            continue
        response.raise_for_status()
        receipt = response.json()
        if receipt["operation_status"] == "COMPLETED":
            break
        if receipt["operation_status"] in {"FAILED", "EXPIRED", "CANCELLED"}:
            raise AssertionError(f"account deletion settled badly: {receipt}")
        if not re_marked and time.monotonic() - started > 12.0:
            mark_user_dirty(str(user.user_id))
            re_marked = True
        time.sleep(1.0)
    else:
        raise AssertionError(f"account deletion did not settle: {receipt}")
    assert receipt["operation_status"] == "COMPLETED", receipt

    # receipt_issued_once: exactly one receipt, keyed to the one-time
    # capability the 202 returned (the receipt read never re-issues it).
    with e7_engine.connect() as conn:
        receipt_rows = conn.execute(
            text("SELECT capability_digest FROM data_receipts WHERE id = :i"),
            {"i": receipt_id},
        ).scalar_one_or_none()
        receipt_total = conn.execute(text("SELECT count(*) FROM data_receipts")).scalar_one()
        operation_total = conn.execute(
            text("SELECT count(*) FROM data_operations WHERE owner_handle = :h"),
            {"h": user.owner_handle},
        ).scalar_one()
        items = conn.execute(
            text(
                "SELECT state, max(attempts) FROM data_cleanup_items "
                "WHERE operation_id = :o GROUP BY state"
            ),
            {"o": operation["id"]},
        ).all()
    assert receipt_rows == hashlib.sha256(capability.encode()).hexdigest()
    assert receipt_total == 1
    assert operation_total == 1
    # single_effective_worker_claim: every item settled DONE (none left
    # claimed/pending/failed) within the frozen retry ladder.
    states = {state for state, _ in items}
    assert states == {"DONE"}, items
    assert all(attempts <= 5 for _state, attempts in items), items

    # The control user is untouched end to end.
    observer = e7_api.get("/v1/auth/me", headers=observer_headers)
    assert observer.status_code == 200, observer.text

    write_evidence("E7-5", "operation.json", operation)
    write_evidence("E7-5", "receipt.json", receipt)
    report = verify_report(e7_verifier, "E7-5")
    write_evidence("E7-5", "verify.json", report.to_dict())
