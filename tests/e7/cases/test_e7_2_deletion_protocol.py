"""E7-2 driver: the deletion protocol — idempotency, expiry, scope/digest
409s, lost-202 convergence and the durable-ledger outage-resume face.

Pre-registered ops (manifest E7-2) mapped to the faces below:

1. 同 target 二次 preview → 内容变化 → digest 409 — the same
   ``client_request_id`` against a DIFFERENT preview (s1 vs s2) is
   ``409 idempotency_conflict`` (a replay may never switch targets); the
   wrong-digest variant of the same family is ``409 preview_stale``.
2. preview 过期后 confirm → 409 — delivered code ``preview_stale``; the
   expiry itself is injected by moving only the preview row's
   ``expires_at`` (metadata time surgery, the integration-suite
   technique). The A-draft §4 order pin is asserted alongside: replaying
   an EXPIRED preview under the SAME key still converges on the original
   operation (idempotency runs before the expiry check).
3. 同 client_request_id 重放 → 同 operation — exact id+version replay.
4. 202 丢响应后重发同 key → 收敛同 op — a third identical confirm.
5. 注入失败后 retry → 同 operation 继续 — redis outage parks the
   accepted operation QUEUED in the durable ledger (the arq worker dies
   with redis — the real process-crash face); after recovery the SAME
   operation runs to COMPLETED and the manual-retry endpoint answers its
   frozen negatives (``version_conflict`` / ``not_retryable``) on the
   terminal op. The FAILED→manual-ladder-reset form needs an item family
   a chat deletion can deterministically fail and is driven in E7-6 (S3
   family); a mid-item redis kill is not deterministic and is not faked.

Single-deletion ledger: exactly one ``data_operations`` row for U.
"""

from __future__ import annotations

import httpx

from tests.e7.conftest import (
    confirm_target,
    login,
    raw_confirm,
    read_operation_visible,
    respawn_e7_worker,
    sql_exec,
    sql_scalar,
    start_e7_redis,
    stop_e7_redis,
    verify_report,
    wait_operation,
    write_evidence,
)


def _confirm(
    e7_api: httpx.Client,
    headers: dict[str, str],
    preview: dict,
    key: str,  # type: ignore[type-arg]
) -> httpx.Response:
    return raw_confirm(e7_api, headers, preview, key=key)


def test_e7_2_deletion_protocol_lifecycle(e7_api, e7_fresh_world, e7_verifier, e7_engine) -> None:  # type: ignore[no-untyped-def]
    headers = login(e7_api, e7_fresh_world, "U")
    session_id = str(e7_fresh_world.rid("U", "s2"))
    other_session_id = str(e7_fresh_world.rid("U", "s1"))
    handle = e7_fresh_world.users["U"].owner_handle

    # Outage parked BEFORE the accept: nothing can sweep the operation, so
    # every protocol face below runs against a durably accepted, not yet
    # executed deletion (deterministic — no cron-timing race).
    stop_e7_redis()
    preview, operation = confirm_target(
        e7_api,
        headers,
        target={"kind": "source", "source_kind": "chat_session", "ids": [session_id]},
        key="e7-2-confirm",
    )
    parked = read_operation_visible(e7_api, headers, operation["id"])
    assert parked["status"] == "QUEUED", parked
    operations_before = sql_scalar(
        e7_engine, "SELECT count(*) FROM data_operations WHERE owner_handle = :h", {"h": handle}
    )
    assert operations_before == 1

    protocol: dict = {"operation_id": operation["id"], "faces": []}

    def face(name: str, response: httpx.Response, status: int, code: str | None = None) -> dict:  # type: ignore[type-arg]
        assert response.status_code == status, f"{name}: {response.text}"
        entry: dict = {"face": name, "status": response.status_code}
        if code is not None:
            assert response.json()["error"]["code"] == code, f"{name}: {response.text}"
            entry["code"] = code
        protocol["faces"].append(entry)
        return response.json()

    # op3 — same key replay converges on the same operation.
    replay = face(
        "replay-same-key-same-operation",
        _confirm(e7_api, headers, preview, "e7-2-confirm"),
        202,
    )
    assert replay["id"] == operation["id"]
    assert replay["version"] == operation["version"]

    # op4 — resend after a lost 202 still converges (no second deletion).
    resend = face(
        "lost-202-resend-same-operation",
        _confirm(e7_api, headers, preview, "e7-2-confirm"),
        202,
    )
    assert resend["id"] == operation["id"]

    # op1a — same key against a DIFFERENT preview (content change) 409s.
    other_preview = e7_api.post(
        "/v1/data/previews",
        json={"kind": "source", "source_kind": "chat_session", "ids": [other_session_id]},
        headers=headers,
    )
    assert other_preview.status_code == 201, other_preview.text
    face(
        "same-key-different-preview-409",
        _confirm(e7_api, headers, other_preview.json(), "e7-2-confirm"),
        409,
        "idempotency_conflict",
    )

    # Barrier face — a fresh preview of the same scope under a NEW key hits
    # the ACTIVE barrier: one effective deletion per scope.
    fresh = e7_api.post(
        "/v1/data/previews",
        json={"kind": "source", "source_kind": "chat_session", "ids": [session_id]},
        headers=headers,
    )
    assert fresh.status_code == 201, fresh.text
    face(
        "second-deletion-same-scope-409",
        _confirm(e7_api, headers, fresh.json(), "e7-2-second"),
        409,
        "deletion_in_progress",
    )

    # op2 — an expired preview under a new key 409s preview_stale.
    sql_exec(
        e7_engine,
        "UPDATE data_previews SET expires_at = now() - interval '1 minute' WHERE id = :i",
        {"i": fresh.json()["id"]},
    )
    face(
        "expired-preview-new-key-409",
        _confirm(e7_api, headers, fresh.json(), "e7-2-expired"),
        409,
        "preview_stale",
    )

    # A-draft §4 order pin — idempotency runs BEFORE the expiry check: the
    # original preview is expired too, and the same key still converges.
    sql_exec(
        e7_engine,
        "UPDATE data_previews SET expires_at = now() - interval '1 minute' WHERE id = :i",
        {"i": preview["id"]},
    )
    expired_replay = face(
        "expired-preview-same-key-replay",
        _confirm(e7_api, headers, preview, "e7-2-confirm"),
        202,
    )
    assert expired_replay["id"] == operation["id"]

    # op1b — wrong digest 409s the same family.
    third = e7_api.post(
        "/v1/data/previews",
        json={"kind": "source", "source_kind": "chat_session", "ids": [session_id]},
        headers=headers,
    )
    assert third.status_code == 201, third.text
    face(
        "wrong-digest-409",
        raw_confirm(e7_api, headers, third.json(), key="e7-2-digest", digest="0" * 64),
        409,
        "preview_stale",
    )

    # op5 — recovery: redis back, a replacement worker drains the SAME
    # operation from the durable ledger to COMPLETED.
    start_e7_redis()
    respawn_e7_worker()
    settled = wait_operation(e7_api, headers, operation["id"], timeout_s=180.0)
    assert settled["status"] == "COMPLETED", settled

    # The manual-retry endpoint answers its frozen negatives on the
    # terminal op: a stale version conflicts first, the current version is
    # not retryable, and neither ever mints a second operation.
    face(
        "retry-stale-version-409",
        e7_api.post(
            f"/v1/data/operations/{operation['id']}/retry",
            json={"expected_version": settled["version"] + 5},
            headers=headers,
        ),
        409,
        "version_conflict",
    )
    face(
        "retry-completed-op-409",
        e7_api.post(
            f"/v1/data/operations/{operation['id']}/retry",
            json={"expected_version": settled["version"]},
            headers=headers,
        ),
        409,
        "not_retryable",
    )
    # Single deletion: the ledger still holds exactly one operation for U.
    operations_after = sql_scalar(
        e7_engine, "SELECT count(*) FROM data_operations WHERE owner_handle = :h", {"h": handle}
    )
    assert operations_after == 1, f"expected one operation, found {operations_after}"

    write_evidence("E7-2", "protocol.json", protocol)
    write_evidence("E7-2", "operation.json", settled)
    report = verify_report(e7_verifier, "E7-2")
    write_evidence("E7-2", "verify.json", report.to_dict())
