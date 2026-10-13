"""E7-3 reference driver: source deletion graph closures (three sub-cases).

Proves the harness end-to-end shape: real HTTP preview/confirm against the
stack, real worker drain, then the pre-registered E7-3a/b/c expectations
checked by the verify pack. Frozen hard asserts live in
m5-e7-acceptance §2 E7-3 (anchored criteria, transient projection edits die
with the whole delete, edge-only survival, invalid basis without original
text). Fixtures come from tests/e7/conftest.py by pytest name resolution.
"""

from __future__ import annotations

import httpx

from tests.e7.conftest import login, verify_report, wait_operation, write_evidence


def _confirm_source(
    e7_api: httpx.Client,
    headers: dict[str, str],
    *,
    source_kind: str,
    ids: list[str],
    key: str,
) -> tuple[dict, dict]:  # type: ignore[type-arg]
    preview_response = e7_api.post(
        "/v1/data/previews",
        json={"kind": "source", "source_kind": source_kind, "ids": ids},
        headers=headers,
    )
    assert preview_response.status_code == 201, preview_response.text
    preview = preview_response.json()
    confirm_response = e7_api.post(
        "/v1/data/deletions",
        json={
            "preview_id": preview["id"],
            "preview_digest": preview["preview_digest"],
            "client_request_id": key,
            "confirmed": True,
        },
        headers=headers,
    )
    assert confirm_response.status_code == 202, confirm_response.text
    return preview, confirm_response.json()


def test_e7_3a_delete_anchored_event_whole_deletes_derived_task(
    e7_api,
    e7_fresh_world,
    e7_verifier,  # type: ignore[no-untyped-def]
) -> None:
    headers = login(e7_api, e7_fresh_world, "U")
    event_id = str(e7_fresh_world.rid("U", "e1"))
    _preview, operation = _confirm_source(
        e7_api, headers, source_kind="event", ids=[event_id], key="e7-3a-confirm"
    )
    settled = wait_operation(e7_api, headers, operation["id"])
    assert settled["status"] == "COMPLETED", settled

    # Invalid-basis face (frozen criterion 失效basis不再有原文): the p1/pi1/r1
    # survivors keep serving the dead e1/t1 ids as dangling references, but
    # the deleted originals must be absent from every response body. The
    # E7-10 driver mirrors this exact face for its own anchored delete.
    plan_face = e7_api.get(f"/v1/plans/{e7_fresh_world.rid('U', 'p1')}", headers=headers)
    assert plan_face.status_code == 200, plan_face.text
    run_face = e7_api.get(f"/v1/agent/runs/{e7_fresh_world.rid('U', 'r1')}", headers=headers)
    assert run_face.status_code == 200, run_face.text
    task_id = str(e7_fresh_world.rid("U", "t1"))
    plan_body = plan_face.json()
    served_refs = {ref["id"] for ref in plan_body["basis"]["references"]}
    assert served_refs == {event_id, task_id}, served_refs
    pi1_face = next(
        item for item in plan_body["items"] if item["id"] == str(e7_fresh_world.rid("U", "pi1"))
    )
    assert pi1_face["task_id"] is None  # FK SET NULL marks the basis invalid
    assert set(pi1_face["basis"].values()) == {event_id, task_id}
    assert event_id in run_face.text  # the run face still serves the dead id
    leaked = [
        name
        for name in ("e1.title", "t1.title")
        if e7_fresh_world.marker_names["U"][name] in plan_face.text + run_face.text
    ]
    assert not leaked, leaked
    write_evidence(
        "E7-3a",
        "invalid-basis-face.json",
        {
            "plan_references_served": sorted(served_refs),
            "pi1_task_link": None,
            "run_face_serves_deleted_event_id": True,
            "original_text_leaked_markers": leaked,
        },
    )
    write_evidence("E7-3a", "operation.json", settled)

    report = verify_report(e7_verifier, "E7-3a")
    write_evidence("E7-3a", "verify.json", report.to_dict())


def test_e7_3b_delete_file_clears_chunks_and_citing_answers(
    e7_api,
    e7_fresh_world,
    e7_verifier,  # type: ignore[no-untyped-def]
) -> None:
    headers = login(e7_api, e7_fresh_world, "U")
    file_id = str(e7_fresh_world.rid("U", "f1"))
    _preview, operation = _confirm_source(
        e7_api, headers, source_kind="file", ids=[file_id], key="e7-3b-confirm"
    )
    settled = wait_operation(e7_api, headers, operation["id"])
    assert settled["status"] == "COMPLETED", settled
    write_evidence("E7-3b", "operation.json", settled)

    report = verify_report(e7_verifier, "E7-3b")
    write_evidence("E7-3b", "verify.json", report.to_dict())


def test_e7_3c_delete_chat_session_hard_clears_soft_deleted_content(
    e7_api,
    e7_fresh_world,
    e7_verifier,  # type: ignore[no-untyped-def]
) -> None:
    headers = login(e7_api, e7_fresh_world, "U")
    session_id = str(e7_fresh_world.rid("U", "s2"))
    _preview, operation = _confirm_source(
        e7_api, headers, source_kind="chat_session", ids=[session_id], key="e7-3c-confirm"
    )
    settled = wait_operation(e7_api, headers, operation["id"])
    assert settled["status"] == "COMPLETED", settled
    write_evidence("E7-3c", "operation.json", settled)

    report = verify_report(e7_verifier, "E7-3c")
    write_evidence("E7-3c", "verify.json", report.to_dict())
