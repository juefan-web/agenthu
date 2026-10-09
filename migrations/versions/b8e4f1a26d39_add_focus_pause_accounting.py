"""add focus_sessions pause accounting columns

Revision ID: b8e4f1a26d39
Revises: c7a3f02d9e51
Create Date: 2026-10-09

活雷② §0（AGENT_CONTEXT/TASKS/m1-focus-pause-accounting.md）：两列内部
暂停记账——paused_at 标记未闭合暂停段起点，accumulated_pause_seconds 存
已闭合段累计。内部列，不入 client 契约（ClientFocusSession 不变，OpenAPI
无漂移）。存量行回填 NULL/0：迁移前 actual_minutes＝含暂停的墙钟上界
（AGENT_CONTEXT/DECISIONS.md D-037），不回改、不标注。
"""

from alembic import op
import sqlalchemy as sa

revision: str = "b8e4f1a26d39"
down_revision: str | None = "c7a3f02d9e51"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "focus_sessions",
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "focus_sessions",
        sa.Column(
            "accumulated_pause_seconds",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("focus_sessions", "accumulated_pause_seconds")
    op.drop_column("focus_sessions", "paused_at")
