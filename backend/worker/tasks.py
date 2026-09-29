"""Arq task functions.

Tasks must be idempotent and safe to retry. The M0 set is intentionally small:
a liveness task proving the Redis -> Arq -> task pipeline. CurrentState is
recomputed synchronously on the request path today; an off-request recompute
task is deferred to M1, where it gets a real caller (DECISIONS.md D-024).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def ping(ctx: dict[str, Any], message: str = "pong") -> dict[str, Any]:
    """Trivial task used to verify Redis -> Arq -> task execution."""

    return {"message": message, "job_try": ctx.get("job_try", 1)}
