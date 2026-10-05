"""narrow the live-subject-key unique index with valid_to IS NULL

Revision ID: 45b7db4cb2cb
Revises: c4f2a8e01d73
Create Date: 2026-10-05

D-036 §1 (M5 P0-1 slice 1): the live-row predicate is
``supersedes_id IS NULL AND validity window covers now`` — an index
predicate cannot contain now(), so the unique index keeps only the
immutable subset and adds ``valid_to IS NULL``. Without it, a retired row
un-pointed by the supersedes FK's SET NULL (its replacement row deleted)
still sits in the index and squats the (user, subject_key): the
predicate-based pre-check passes, the insert then dies on the unique
violation. The index remains a write-order guard, not the read-side live
definition — readers share
``backend.services.memory_lifecycle.live_memory_conditions``.

Narrowing only removes rows from the index (retired rows with a past
``valid_to``), so no existing data can violate the new constraint; no
backfill is needed. Time-bounded rows (``valid_to`` in the future) are
outside the index until a writer that creates them arrives; no current
writer does (retirement always stamps ``valid_to = now``).
"""

from alembic import op

revision: str = "45b7db4cb2cb"
down_revision: str | None = "c4f2a8e01d73"
branch_labels = None
depends_on = None

# Must match backend/models/memory.py byte-for-byte or autogenerate drifts
# (house rule: index expressions identical in model and migration).
_WHERE = "subject_key IS NOT NULL AND supersedes_id IS NULL AND valid_to IS NULL"


def upgrade() -> None:
    op.drop_index("uq_memories_user_subject_live", table_name="memories")
    op.create_index(
        "uq_memories_user_subject_live",
        "memories",
        ["user_id", "subject_key"],
        unique=True,
        postgresql_where=op.f(_WHERE),
    )


def downgrade() -> None:
    op.drop_index("uq_memories_user_subject_live", table_name="memories")
    op.create_index(
        "uq_memories_user_subject_live",
        "memories",
        ["user_id", "subject_key"],
        unique=True,
        postgresql_where=op.f(
            "subject_key IS NOT NULL AND supersedes_id IS NULL"
        ),
    )
