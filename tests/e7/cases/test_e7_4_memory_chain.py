"""E7-4 drivers: memory-chain closures.

E7-4a — U 对 m2b 执行整链忘记（lifecycle): ``kind=memory`` preview with
``include_history=true`` over the LIVE row; the superseded history row
(m2a) dies with the chain and never revives (D-036 §1: SET NULL is not a
resurrection path). Retained: m1/m3/m4 stay readable over HTTP.

E7-4b — 删除 L2 源事件 e5：the evidence chain drains the whole chain
(m2b live + m2a history; the L2 sample count falls below the threshold
and the chain is removed together — 外审 #6 修订 form), vector recall for
U:m2b goes to zero and the subject key has no live row. Retained: m1
(e3-anchored)/m3/m4 and the e6 event row survive; the e6 reference dies
with the chain (引用随链断开).
"""

from __future__ import annotations

from tests.e7.conftest import (
    confirm_target,
    login,
    verify_report,
    wait_operation,
    write_evidence,
)


def test_e7_4a_forget_whole_memory_chain(e7_api, e7_fresh_world, e7_verifier) -> None:  # type: ignore[no-untyped-def]
    headers = login(e7_api, e7_fresh_world, "U")
    memory_id = str(e7_fresh_world.rid("U", "m2b"))

    _preview, operation = confirm_target(
        e7_api,
        headers,
        target={"kind": "memory", "ids": [memory_id], "include_history": True},
        key="e7-4a-confirm",
    )
    settled = wait_operation(e7_api, headers, operation["id"])
    assert settled["status"] == "COMPLETED", settled

    # Retained face over HTTP: the untouched memories stay readable.
    for name in ("m1", "m3", "m4"):
        survivor = e7_api.get(f"/v1/memory/{e7_fresh_world.rid('U', name)}", headers=headers)
        assert survivor.status_code == 200, f"{name} should survive: {survivor.text}"

    write_evidence("E7-4a", "operation.json", settled)
    report = verify_report(e7_verifier, "E7-4a")
    write_evidence("E7-4a", "verify.json", report.to_dict())


def test_e7_4b_delete_source_event_drains_l2_chain(e7_api, e7_fresh_world, e7_verifier) -> None:  # type: ignore[no-untyped-def]
    headers = login(e7_api, e7_fresh_world, "U")
    event_id = str(e7_fresh_world.rid("U", "e5"))

    _preview, operation = confirm_target(
        e7_api,
        headers,
        target={"kind": "source", "source_kind": "event", "ids": [event_id]},
        key="e7-4b-confirm",
    )
    settled = wait_operation(e7_api, headers, operation["id"])
    assert settled["status"] == "COMPLETED", settled

    # Retained faces over HTTP: m1/m3/m4 stay readable and the independent
    # e6 event row survives (its reference dies with the chain, not itself).
    for name in ("m1", "m3", "m4"):
        survivor = e7_api.get(f"/v1/memory/{e7_fresh_world.rid('U', name)}", headers=headers)
        assert survivor.status_code == 200, f"{name} should survive: {survivor.text}"
    e6_read = e7_api.get(f"/v1/events/{e7_fresh_world.rid('U', 'e6')}", headers=headers)
    assert e6_read.status_code == 200, e6_read.text

    # Invalid-basis face (invalid_basis_no_original_text): the surviving
    # grounded answer a1 still serves its dangling memory reference (m2b's
    # id in memory_ids — the chain row is gone), but the deleted chain's
    # original text must be absent from the answer face.
    answers_face = e7_api.get(
        "/v1/material/answers",
        params={"course_name": "线性代数"},
        headers=headers,
    )
    assert answers_face.status_code == 200, answers_face.text
    a1_face = next(
        item
        for item in answers_face.json()["items"]
        if item["id"] == str(e7_fresh_world.rid("U", "a1"))
    )
    memory_ids = {str(value) for value in a1_face["memory_ids"]}
    assert str(e7_fresh_world.rid("U", "m2b")) in memory_ids, memory_ids
    leaked = [
        name
        for name in ("m2a.content", "m2b.content")
        if e7_fresh_world.marker_names["U"][name] in answers_face.text
    ]
    assert not leaked, leaked
    write_evidence(
        "E7-4b",
        "invalid-basis-face.json",
        {
            "answer_serves_dangling_memory_id": True,
            "chain_original_text_leaked_markers": leaked,
        },
    )

    write_evidence("E7-4b", "operation.json", settled)
    report = verify_report(e7_verifier, "E7-4b")
    write_evidence("E7-4b", "verify.json", report.to_dict())
