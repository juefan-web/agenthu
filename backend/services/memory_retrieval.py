"""The shared memory-retrieval path for decision contexts (D-031 §5).

Frozen semantics (TASKS/m3-memory-schema-migration.md §5, DECISIONS D-031,
liveness widened by D-036 §1): only live rows
(:func:`backend.services.memory_lifecycle.live_memory_conditions`),
REJECTED rows filtered, and a confidence floor of 0.3 that callers may raise
but never bypass. Vector recall (M3) must be applied AFTER this filter,
never instead of it.

Two gates live in this codebase on purpose:

- THIS floor serves general decision contexts (M4 context assembly and the
  future grounding answers).
- The estimate ladder (``services/estimates.py``) is gated by sample count
  instead: a 2-sample course row carries confidence ``min(0.9, 2/10) = 0.2``
  and must still drive ``learned:course`` (D-031 §4), so routing it through
  the 0.3 floor would silently break the frozen ladder. The two paths share
  the live/non-rejected row semantics but deliberately not the floor.

Telemetry (task doc §8a.2): ``use_count`` counts "entered a decision
context" only. Retrieval here is candidate selection and must NOT bump
anything — the planner calls :func:`record_decision_use` for the rows whose
estimates actually landed in a generated plan's basis, once per row per
generated plan (batch dedup: three tasks of one course = one decision for
the course row, even though ``estimate_for_task`` ran three times).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.base import utcnow
from backend.models.enums import MemoryCorrectionStatus, MemoryKind
from backend.models.memory import Memory
from backend.services.memory_lifecycle import live_memory_conditions

RETRIEVAL_CONFIDENCE_FLOOR = 0.3
MAX_RETRIEVAL_LIMIT = 200


def retrieve_memories(
    session: Session,
    *,
    user_id: uuid.UUID,
    min_confidence: float | None = None,
    level: int | None = None,
    kinds: Sequence[MemoryKind] | None = None,
    domains: Sequence[str] | None = None,
    subject_key: str | None = None,
    limit: int = 50,
) -> list[Memory]:
    """Candidate memories for a decision context, under the §5 floor.

    ``min_confidence`` raises the floor; values below
    :data:`RETRIEVAL_CONFIDENCE_FLOOR` are clamped up to it (the floor is a
    lower bound the caller cannot talk the query out of). Results are newest
    first — deterministic on ``(updated_at, id)``; recall-based re-ranking
    happens above this function, not inside it.
    """

    floor = (
        RETRIEVAL_CONFIDENCE_FLOOR
        if min_confidence is None
        else max(RETRIEVAL_CONFIDENCE_FLOOR, min_confidence)
    )
    conditions: list[Any] = [
        Memory.user_id == user_id,
        *live_memory_conditions(),
        Memory.correction_status != MemoryCorrectionStatus.REJECTED,
        Memory.confidence >= floor,
    ]
    if level is not None:
        conditions.append(Memory.level == level)
    if kinds:
        conditions.append(Memory.kind.in_(list(kinds)))
    if domains:
        conditions.append(Memory.domain.in_(list(domains)))
    if subject_key is not None:
        conditions.append(Memory.subject_key == subject_key)
    stmt = (
        select(Memory)
        .where(*conditions)
        .order_by(Memory.updated_at.desc(), Memory.id.desc())
        .limit(max(1, min(limit, MAX_RETRIEVAL_LIMIT)))
    )
    return list(session.scalars(stmt))


def record_decision_use(
    session: Session,
    memory_ids: Iterable[uuid.UUID | None],
    *,
    now: datetime | None = None,
) -> None:
    """Mark memories as having entered a decision context (§8a.2).

    The only writers of ``use_count``/``last_used_at``: today the planner
    (rows whose estimates landed in a generated plan's basis), later the M4
    context assembly (rows in the run's context snapshot). Deduplicated by
    id so one generation pass counts a row once no matter how many tasks
    read it. Attribute increments (not a bulk UPDATE) keep the rows already
    in the identity map coherent and commit atomically with the decision
    they attest.
    """

    distinct_ids = [id_ for id_ in dict.fromkeys(memory_ids) if id_ is not None]
    if not distinct_ids:
        return
    stamp = now if now is not None else utcnow()
    rows = session.scalars(select(Memory).where(Memory.id.in_(distinct_ids))).all()
    for row in rows:
        row.use_count += 1
        row.last_used_at = stamp
