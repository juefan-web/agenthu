"""E7-10 blocked stub.

Pre-registered in the manifest (expected counts and invariants) but its
driver cannot execute until the required surfaces land. The skip reason
carries the exact blocked-by so a gated run reports it as blocked, never as
a silent skip — and the invariants stay un-implementable in verify.py until
then (verify.py BLOCKED_INVARIANTS fails if requested).

E7-9 moved out of this file in D2: its surfaces (shared rate-limit ledger,
traceparent seam, allowlist exporter, the agenthu-multi compose stack) are
in main, so its driver now runs for real — the third "silent skip" form
(a stub whose blocked-by has gone stale) is exactly what this batch was
re-scoped to eliminate.
"""

from __future__ import annotations

import pytest


def test_e7_10_recovery_and_release_gates() -> None:
    pytest.skip(
        "blocked_by=P0-6: backup restore drill, key rotation evidence and "
        "the per-file license gate are release-phase work "
        "(m5-e7-acceptance E7-10)"
    )
