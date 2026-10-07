"""E7-1 reference driver: whole-graph export with ownership boundaries.

Exercises the export face over real HTTP (staged package + download) and
asserts the package-level frozen invariants that the verify pack cannot
see from the outside: U markers present in U's package, V markers absent,
include_files=false omits file blobs, V credentials cannot reach U's
operation. Count/object expectations are verified by the verify pack.
"""

from __future__ import annotations

import httpx

from tests.e7.conftest import (
    login,
    verify_report,
    wait_operation,
    write_evidence,
)


def _run_export(
    e7_api: httpx.Client, headers: dict[str, str], *, include_files: bool, key: str
) -> dict:  # type: ignore[type-arg]
    response = e7_api.post(
        "/v1/data/exports",
        json={"client_request_id": key, "include_files": include_files},
        headers=headers,
    )
    assert response.status_code == 202, response.text
    operation = response.json()
    # READY = staged + verified, awaiting download (export terminal shape).
    settled = wait_operation(
        e7_api, headers, operation["id"], success_states=("READY", "COMPLETED")
    )
    return settled


def _package_text(package: bytes) -> bytes:
    """Concatenated DECOMPRESSED members — zip members are deflate-stored,
    so raw archive bytes never contain the markers (first smoke lesson)."""

    import io
    import zipfile

    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        return b"".join(archive.read(name) for name in archive.namelist())


def _package_names(package: bytes) -> list[str]:
    import io
    import zipfile

    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        return list(archive.namelist())


def test_e7_1_export_whole_graph_with_ownership_boundaries(
    e7_api,
    e7_fresh_world,
    e7_verifier,  # type: ignore[no-untyped-def]
) -> None:
    u_headers = login(e7_api, e7_fresh_world, "U")
    v_headers = login(e7_api, e7_fresh_world, "V")

    settled = _run_export(e7_api, u_headers, include_files=True, key="e7-1-export-full")
    write_evidence("E7-1", "operation-full.json", settled)

    download = e7_api.get(f"/v1/data/operations/{settled['id']}/download", headers=u_headers)
    assert download.status_code == 200, download.text
    package = download.content
    assert len(package) > 0
    haystack = _package_text(package)
    names = _package_names(package)
    assert any(name.startswith("files/") for name in names), "include_files must ship blobs"

    v_markers = list(e7_fresh_world.marker_names["V"].values())
    # Deliberate omissions per frozen export semantics: current_states is a
    # rebuilt projection (registry: "rebuilt rather than exported as-is" —
    # no member at all), audit rows are content-free receipts (A-draft §5 —
    # action/actor/time only, no ip/ua/details), and plan.basis is a
    # decision-support snapshot the serializer does not carry. Everything
    # else the user owns must be in the package.
    omitted = {
        "cs1.context",
        "cs1.recent",
        "p1.basis",
        "al1.details",
        "al1.ua",
        "al2.details",
        "al2.ua",
        "al3.details",
        "al3.ua",
    }
    expected_present = [
        token for name, token in e7_fresh_world.marker_names["U"].items() if name not in omitted
    ]
    missing = [m for m in expected_present if m.encode() not in haystack]
    leaked = [m for m in v_markers if m.encode() in haystack]
    assert not missing, f"U content missing from U package: {missing}"
    assert not leaked, f"V content leaked into U package: {leaked}"
    write_evidence(
        "E7-1",
        "package-scan.json",
        {
            "operation_id": str(settled["id"]),
            "bytes": len(package),
            "members": len(names),
            "u_markers_found": len(expected_present),
            "u_markers_omitted_by_design": sorted(omitted),
            "v_markers_found": 0,
        },
    )

    # include_files=false: file blobs are an explicit, declared omission.
    settled_nofiles = _run_export(e7_api, u_headers, include_files=False, key="e7-1-export-nofiles")
    write_evidence("E7-1", "operation-nofiles.json", settled_nofiles)
    download_nofiles = e7_api.get(
        f"/v1/data/operations/{settled_nofiles['id']}/download", headers=u_headers
    )
    assert download_nofiles.status_code == 200, download_nofiles.text
    names_nofiles = _package_names(download_nofiles.content)
    assert not any(name.startswith("files/") for name in names_nofiles), (
        "include_files=false must omit blobs"
    )
    text_nofiles = _package_text(download_nofiles.content)
    blob_markers = [e7_fresh_world.marker_names["U"][f"{name}.blob"] for name in ("f1", "f2")]
    assert all(m.encode() not in text_nofiles for m in blob_markers), (
        "blob markers must not appear in the no-files package"
    )

    # Ownership boundary: V cannot read or download U's operation.
    assert (
        e7_api.get(f"/v1/data/operations/{settled['id']}", headers=v_headers).status_code == 404
    ), "V must not see U's operation"
    assert e7_api.get(
        f"/v1/data/operations/{settled['id']}/download", headers=v_headers
    ).status_code in (403, 404), "V must not download U's package"

    report = verify_report(e7_verifier, "E7-1")
    write_evidence("E7-1", "verify.json", report.to_dict())
