"""E7-6 driver: chaos against the deletion ledger — redis outage, S3
outage, process death, bounded ladder, same-operation resume.

Deterministic sequence (every fault is in place BEFORE the machinery that
would hit it runs — no cron-timing races):

1. stop redis → the arq worker dies with it (real process-crash face:
   the poll loop has no reconnect tolerance on this stack). Preview and
   confirm still work — the durable ledger is the truth, redis only
   wakes work.
2. accept the f2 source deletion → the operation sits QUEUED in the DB;
   assert the ledger rows exist with nothing executing
   (op1: DB 已接受后 Redis 断供，账本仍有 key).
3. stop s3mock, restart redis, respawn a worker → the operation stays
   QUEUED through a full cron cycle: ``sweep_data_operations`` calls
   ``get_storage()`` unconditionally and a dead endpoint raises raw
   ``EndpointConnectionError`` out of ``ensure_bucket`` (the
   build_storage degrade guard catches StorageError only), so the whole
   dispatch loop is hostage to object-store availability. Structural
   finding reported with this driver (D1 notes); its consequence here is
   deterministic and is op2's delivered face: 非 COMPLETED for the whole
   outage window and NOTHING about the outage may read as absence
   (403/超时不当 404 — no erasure claim is ever made while the store is
   down; the trichotomy's runtime FORBIDDEN/UNAVAILABLE branches are
   unreachable through the cron on this code and stay pinned in-repo at
   the storage unit level; s3mock accepts any credentials so no real 403
   exists on this stack).
4. start s3mock → the next healthy sweep dispatches the SAME operation,
   which runs to COMPLETED (op3: 恢复后继续同 operation). Ladder bound:
   every item DONE, attempts within the frozen 5-cap.

Residual (honestly not driven): the FAILED→manual-ladder-reset face and
ladder-exhaustion audit — an item can only fail mid-execution, and
dispatch is storage-gated, so no deterministic mid-ladder outage exists
on this code. Product follow-up candidate: dispatch due operations
before/independently of storage touches so mid-execution store outages
become reachable (then this driver grows the mid-ladder phase).
"""

from __future__ import annotations

import time

from sqlalchemy import text

from tests.e7.conftest import (
    confirm_target,
    login,
    read_operation_visible,
    respawn_e7_worker,
    start_e7_object_store,
    start_e7_redis,
    stop_e7_object_store,
    stop_e7_redis,
    verify_report,
    wait_operation,
    write_evidence,
)

#: One full cron cycle (the sweep ticks at second {0,30}) — the outage
#: observation window must span it to prove dispatch stayed blocked.
_CRON_CYCLE_S = 40.0


def test_e7_6_outages_ladder_and_same_operation_resume(
    e7_api, e7_fresh_world, e7_verifier, e7_engine
) -> None:  # type: ignore[no-untyped-def]
    headers = login(e7_api, e7_fresh_world, "U")
    file_id = str(e7_fresh_world.rid("U", "f2"))
    handle = e7_fresh_world.users["U"].owner_handle

    # 1 — redis outage kills the worker; the accept still lands durably.
    stop_e7_redis()
    preview, operation = confirm_target(
        e7_api,
        headers,
        target={"kind": "source", "source_kind": "file", "ids": [file_id]},
        key="e7-6-confirm",
    )
    ledger = read_operation_visible(e7_api, headers, operation["id"])
    assert ledger["status"] == "QUEUED", ledger
    with e7_engine.connect() as conn:
        operations = conn.execute(
            text("SELECT count(*) FROM data_operations WHERE owner_handle = :h"),
            {"h": handle},
        ).scalar_one()
        items = conn.execute(
            text("SELECT count(*) FROM data_cleanup_items WHERE operation_id = :o"),
            {"o": operation["id"]},
        ).scalar_one()
    assert operations == 1
    assert items >= 1, "the durable ledger must carry the cleanup keys"

    # 2 — S3 outage in place BEFORE recovery: with the store dead the
    # sweep cannot dispatch (structural), so the operation must sit
    # QUEUED — non-COMPLETED, no erasure claimed — for a full cron cycle.
    stop_e7_object_store()
    start_e7_redis()
    respawn_e7_worker()

    window_deadline = time.monotonic() + _CRON_CYCLE_S
    outage_view: dict = {}
    while time.monotonic() < window_deadline:
        current = e7_api.get(f"/v1/data/operations/{operation['id']}", headers=headers)
        if current.status_code == 200:
            outage_view = current.json()
            assert outage_view["status"] == "QUEUED", outage_view
        time.sleep(2.0)
    outage_view = read_operation_visible(e7_api, headers, operation["id"])
    write_evidence("E7-6", "outage-operation.json", outage_view)
    write_evidence(
        "E7-6",
        "outage-observation.json",
        {
            "window_s": _CRON_CYCLE_S,
            "operation_status": outage_view["status"],
            "preview_id": preview["id"],
            "note": "sweep dispatch storage-gated; nothing executed, nothing claimed absent",
        },
    )

    # 3 — recovery: the next healthy sweep dispatches the SAME operation.
    start_e7_object_store()
    settled = wait_operation(e7_api, headers, operation["id"], timeout_s=180.0)
    assert settled["status"] == "COMPLETED", settled

    # Ladder bound: one operation, every item DONE inside the frozen cap.
    with e7_engine.connect() as conn:
        operations = conn.execute(
            text("SELECT count(*) FROM data_operations WHERE owner_handle = :h"),
            {"h": handle},
        ).scalar_one()
        ladder = conn.execute(
            text(
                "SELECT state, max(attempts) FROM data_cleanup_items "
                "WHERE operation_id = :o GROUP BY state"
            ),
            {"o": operation["id"]},
        ).all()
    assert operations == 1, "chaos must never mint a second operation"
    states = {state for state, _ in ladder}
    assert states == {"DONE"}, ladder
    assert all(attempts <= 5 for _state, attempts in ladder), ladder

    write_evidence("E7-6", "operation.json", settled)
    report = verify_report(e7_verifier, "E7-6")
    write_evidence("E7-6", "verify.json", report.to_dict())
