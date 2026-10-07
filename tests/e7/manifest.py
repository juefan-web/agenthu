"""Derive the pre-registration manifest from the seed spec + data registry.

The manifest is the frozen expectation contract for the E7 rounds: before
counts per family, dependency/history chains and per-case expected
delete/redact/recompute/retain deltas with reasons. It is generated BEFORE
any run and committed to the repository; ``verify.py`` refuses to derive
expectations at run time — it reads this file, so "adjust expectations
after the fact" is structurally impossible (m5-e7-acceptance §1).

Regenerate with ``python -m tests.e7.manifest``; drift is pinned by
``tests/unit/test_e7_manifest.py`` in ordinary CI.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from backend.services.data_registry import graph_version
from tests.e7.seed_spec import (
    EXPECTATIONS,
    EXPORT_STAGING_PREFIX,
    SEED_ANCHOR,
    build_world,
)

MANIFEST_PATH = Path(__file__).resolve().parent / "manifest.json"
MANIFEST_VERSION = 1

# Registry POSTGRES tables the seed world intentionally leaves empty (the
# lifecycle ledger is produced by real API flows only — task doc ruling ⑨).
_SEED_EMPTY_FAMILIES = (
    "data_operations",
    "data_cleanup_items",
    "data_barriers",
    "data_previews",
    "data_receipts",
    "data_suppressions",
    "storage_orphan_keys",
)


def _json_canonical(value: object) -> object:
    """Round-trip through JSON so tuples become lists — the manifest must
    compare equal to its own committed file after a JSON load."""

    return json.loads(json.dumps(value, ensure_ascii=False))


def build_manifest() -> dict[str, object]:
    world = build_world()

    before: dict[str, dict[str, int]] = {}
    for tag in ("U", "V"):
        counts: dict[str, int] = {"users": 1}
        for row in world.rows:
            if row.user == tag:
                counts[row.table] = counts.get(row.table, 0) + 1
        for family in _SEED_EMPTY_FAMILIES:
            counts.setdefault(family, 0)
        before[tag] = dict(sorted(counts.items()))

    chains = [
        {
            "family": "tasks",
            "chain": "e1 --(source, source_upstream_id=E7-*-asg-1)--> t1 "
            "(anchored derivation; transient projection edits die with the "
            "whole delete — E7-3)",
            "same_for": ["e2->t2"],
        },
        {
            "family": "task_events",
            "chain": "t3 --edge--> e3 (edge-only association: task survives "
            "decorrelated, edge clears — E7-3)",
        },
        {
            "family": "focus_sessions",
            "chain": "t1 <--task_id-- fs1 (cascade count with anchored "
            "whole delete); result event e4 is independent user content",
        },
        {
            "family": "memories",
            "chain": "m2a --supersedes_id--> m2b (correction history; only "
            "m2b live for the subject key); m2b source_event_ids=[e5,e6] "
            "(L2 samples; deleting one invalidates, not deletes — E7-4b)",
            "also": "m1 source_event_ids=[e3]; m3/m4 user-authored",
        },
        {
            "family": "plans/plan_items",
            "chain": "p1.basis refs t1+e1; pi1.basis refs t1+e1; "
            "pi2.result refs t2+e2 (失效 basis 不再有原文)",
        },
        {
            "family": "material",
            "chain": "f1->c1,c2; f2->c3,c4 (embeddings); a1.chunk_ids="
            "[c1,c2], memory_ids=[m2b] (citing answers clear whole)",
        },
        {
            "family": "agent/pending",
            "chain": "cm2.agent_run_id=r1; r1.basis refs e1+t1; "
            "pa1.basis refs e1; pam1 caches pa1 settlement",
        },
        {
            "family": "objects",
            "chain": "f1/f2 blobs under e7/<tag>/<name>/<file_id>; export "
            f"staging under {EXPORT_STAGING_PREFIX}<owner_handle>/",
        },
    ]

    return {
        "manifest_version": MANIFEST_VERSION,
        "generated_from": "tests/e7/seed_spec.py + backend/services/data_registry.py",
        "registry_graph_version": graph_version(),
        "seed_anchor_utc": SEED_ANCHOR.isoformat(),
        "marker_prefixes": {"U": "E7MARK-U-", "V": "E7MARK-V-"},
        "marker_inventory": {
            tag: dict(sorted(tokens.items())) for tag, tokens in world.marker_names.items()
        },
        "users": {
            tag: {
                "user_id": str(spec.user_id),
                "email": spec.email,
                "owner_handle": spec.owner_handle,
            }
            for tag, spec in world.users.items()
        },
        "vector_probe_names": sorted(world.vector_names),
        "seeded_blob_keys": sorted(world.blobs),
        "before_counts": before,
        "dependency_chains": chains,
        "case_expectations": {
            case_id: _json_canonical(asdict(expectation))
            for case_id, expectation in sorted(EXPECTATIONS.items())
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=MANIFEST_PATH, help="manifest target path")
    parser.add_argument(
        "--check",
        action="store_true",
        help="regenerate and diff against the existing file instead of writing",
    )
    args = parser.parse_args(argv)

    manifest = build_manifest()
    rendered = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    if args.check:
        current = args.output.read_text(encoding="utf-8") if args.output.exists() else ""
        if current != rendered:
            print(f"manifest drift: {args.output} does not match the seed spec", file=sys.stderr)
            return 1
        print(f"manifest up to date: {args.output}")
        return 0
    args.output.write_text(rendered, encoding="utf-8")
    print(f"manifest written: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
