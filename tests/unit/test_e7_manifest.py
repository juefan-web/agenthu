"""The committed E7 manifest must always match the seed spec.

Ordinary-CI drift pin for the pre-registration contract (task doc ruling ②):
any seed_spec/registry change that moves expectations must regenerate and
re-commit tests/e7/manifest.json in the same change, so the expectations B
signed are never silently different from the ones the runners check.
"""

from __future__ import annotations

import json

from tests.e7.manifest import MANIFEST_PATH, build_manifest


def test_committed_manifest_matches_seed_spec() -> None:
    committed = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert committed == build_manifest()


def test_every_expected_marker_name_exists_in_inventory() -> None:
    manifest = build_manifest()
    inventory = manifest["marker_inventory"]
    expectations = manifest["case_expectations"]
    assert isinstance(inventory, dict) and isinstance(expectations, dict)
    for case_id, expectation in expectations.items():
        assert isinstance(expectation, dict)
        for name in expectation["marker_absence"]:
            assert name in inventory["U"], f"{case_id}: unknown marker name {name!r}"
        for tag in expectation["all_markers_absent_for"]:
            assert inventory[tag], f"{case_id}: {tag} has no allocated markers"
