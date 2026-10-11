"""The CI minimal-pass gate holds against synthetic junit shapes.

The shapes mirror what pytest actually emits (a testsuites wrapper, or a
bare testsuite) plus the two failure families the gate exists for: an
environment that skips the suite away to green, and a run that genuinely
dropped below the anchored floor.
"""

from __future__ import annotations

from pathlib import Path

from backend.scripts.ci_test_gate import evaluate, main, parse_junit

FULL_TOTAL = 554
FLOOR = FULL_TOTAL - 6  # the six clock-sensitive late-night skips


def _write_junit(path: Path, *, tests: int, skipped: int = 0, failures: int = 0) -> Path:
    errors = tests - skipped - failures
    path.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        '<testsuites name="pytest">'
        f'<testsuite name="backend" tests="{tests}" errors="0" '
        f'failures="{failures}" skipped="{skipped}">'
        f"{'<testcase classname="t" name="x" />' * errors}"
        f"{'<testcase classname="t" name="s"><skipped /></testcase>' * skipped}"
        "</testsuite></testsuites>",
        encoding="utf-8",
    )
    return path


def test_parse_reads_the_pytest_wrapper_shape(tmp_path: Path) -> None:
    junit = _write_junit(tmp_path / "r.xml", tests=10, skipped=2)
    assert parse_junit(junit) == {"tests": 10, "errors": 0, "failures": 0, "skipped": 2}


def test_full_run_at_the_floor_boundary_passes() -> None:
    totals = {"tests": FULL_TOTAL - 6, "errors": 0, "failures": 0, "skipped": 0}
    assert evaluate(totals, floor=FLOOR, skip_ceiling=8) == []


def test_late_night_form_six_skips_still_passes() -> None:
    totals = {"tests": FULL_TOTAL, "errors": 0, "failures": 0, "skipped": 6}
    assert evaluate(totals, floor=FLOOR, skip_ceiling=8) == []


def test_wholesale_skip_run_is_below_the_floor() -> None:
    # The observed shape: the test DB down, 357 integration tests skip and
    # the suite stays green in seconds. The floor must go red here.
    totals = {"tests": FULL_TOTAL, "errors": 0, "failures": 0, "skipped": 357}
    problems = evaluate(totals, floor=FLOOR, skip_ceiling=8)
    assert any("below the floor" in problem for problem in problems)
    assert any("above the ceiling" in problem for problem in problems)


def test_skip_ceiling_breach_alone_goes_red() -> None:
    # 9 skips keep the passed count at/above the floor but exceed the
    # ceiling, so the ceiling check must stand on its own.
    totals = {"tests": FULL_TOTAL + 3, "errors": 0, "failures": 0, "skipped": 9}
    assert any(
        "above the ceiling" in problem for problem in evaluate(totals, floor=FLOOR, skip_ceiling=8)
    )


def test_failures_are_reported_even_above_the_floor() -> None:
    totals = {"tests": FULL_TOTAL, "errors": 0, "failures": 3, "skipped": 0}
    assert any(
        "failed or errored" in problem for problem in evaluate(totals, floor=FLOOR, skip_ceiling=8)
    )


def test_main_exits_red_on_below_floor_run_and_green_on_health(tmp_path: Path) -> None:
    broken = _write_junit(tmp_path / "broken.xml", tests=FULL_TOTAL, skipped=357)
    assert main(["--junit", str(broken), "--floor", str(FLOOR)]) == 1

    healthy = _write_junit(tmp_path / "healthy.xml", tests=FULL_TOTAL, skipped=6)
    assert main(["--junit", str(healthy), "--floor", str(FLOOR), "--skip-ceiling", "8"]) == 0
