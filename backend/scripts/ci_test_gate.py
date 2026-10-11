"""Fail CI when the backend suite passes far fewer tests than it should.

`pytest --junitxml` reports the whole suite's shape even when everything
skips, and a wholesale-skip run still exits 0 — a green build that proved
nothing (observed locally: the test DB being down flipped 357 integration
tests to skip and the suite stayed "green" in 33 seconds). This gate reads
the junit XML and enforces two invariants:

- at least FLOOR tests actually passed (the anchored suite total minus the
  six clock-sensitive tests that legitimately skip in the late-night
  window; see tests/conftest.py skip_late_night);
- at most SKIP_CEILING tests skipped (a run that skips more than the
  night window allows is hiding a broken environment).

Both constants live in the CI workflow env block so the anchor is a
reviewed, greppable workflow change: bump the floor when the suite grows,
never to make a broken run pass. `--floor`/`--skip-ceiling` fall back to
CI_TEST_FLOOR / CI_TEST_SKIP_CEILING so the workflow stays the single
source of truth.
"""

from __future__ import annotations

import argparse
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

DEFAULT_SKIP_CEILING = 8


def parse_junit(path: Path) -> dict[str, int]:
    """Aggregate the pytest junit counts (testsuites wrapper or bare suite)."""

    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    if not suites:
        raise ValueError(f"no testsuite element found in {path}")

    totals = {"tests": 0, "errors": 0, "failures": 0, "skipped": 0}
    for suite in suites:
        for key in totals:
            totals[key] += int(suite.get(key, "0"))
    return totals


def evaluate(totals: dict[str, int], *, floor: int, skip_ceiling: int) -> list[str]:
    """The violations, empty when the run is healthy."""

    problems: list[str] = []
    passed = totals["tests"] - totals["errors"] - totals["failures"] - totals["skipped"]
    if totals["errors"] or totals["failures"]:
        problems.append(
            f"{totals['errors'] + totals['failures']} test(s) failed or errored "
            "(pytest already reports the details above)"
        )
    if passed < floor:
        problems.append(
            f"only {passed} test(s) passed, below the floor of {floor} — "
            "a broken environment is skipping the suite away to green"
        )
    if totals["skipped"] > skip_ceiling:
        problems.append(
            f"{totals['skipped']} test(s) skipped, above the ceiling of "
            f"{skip_ceiling} (the late-night window flips at most 6)"
        )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--junit", default="pytest-results.xml", type=Path)
    parser.add_argument(
        "--floor",
        type=int,
        default=None,
        help="minimum passed count (default: env CI_TEST_FLOOR)",
    )
    parser.add_argument(
        "--skip-ceiling",
        type=int,
        default=None,
        help="maximum skipped count (default: env CI_TEST_SKIP_CEILING)",
    )
    args = parser.parse_args(argv)
    floor = args.floor if args.floor is not None else int(os.environ.get("CI_TEST_FLOOR", "0"))
    skip_ceiling = (
        args.skip_ceiling
        if args.skip_ceiling is not None
        else int(os.environ.get("CI_TEST_SKIP_CEILING", str(DEFAULT_SKIP_CEILING)))
    )

    try:
        totals = parse_junit(args.junit)
    except (OSError, ET.ParseError, ValueError) as error:
        print(f"ci-test-gate: cannot read junit xml: {error}", file=sys.stderr)
        return 2

    problems = evaluate(totals, floor=floor, skip_ceiling=skip_ceiling)
    passed = totals["tests"] - totals["errors"] - totals["failures"] - totals["skipped"]
    print(
        f"ci-test-gate: {passed} passed, {totals['skipped']} skipped "
        f"(floor {floor}, skip ceiling {skip_ceiling})"
    )
    if problems:
        for problem in problems:
            print(f"ci-test-gate: FAIL: {problem}", file=sys.stderr)
        return 1
    print("ci-test-gate: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
