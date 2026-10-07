"""E7-9 / E7-10 blocked stubs.

These cases are pre-registered in the manifest (expected counts and
invariants) but their drivers cannot execute until the required surfaces
land. The skip reason carries the exact blocked-by so a gated run reports
them as blocked, never as silent skips — and the invariants stay
un-implementable in verify.py until then (verify.py BLOCKED_INVARIANTS
fails if requested).
"""

from __future__ import annotations

import pytest


def test_e7_9_observability_and_shared_multiprocess() -> None:
    pytest.skip(
        "blocked_by=P0-5: OTel trace surface, shared rate limiting and the "
        "2API+2worker topology do not exist yet (m5-e7-acceptance E7-9)"
    )


def test_e7_10_recovery_and_release_gates() -> None:
    pytest.skip(
        "blocked_by=P0-6: backup restore drill, key rotation evidence and "
        "the per-file license gate are release-phase work "
        "(m5-e7-acceptance E7-10)"
    )
