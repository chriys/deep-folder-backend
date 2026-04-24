"""traces table

Revision ID: 0012
Revises: 0010, 0011
Create Date: 2026-04-24

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012"
down_revision: str | Sequence[str] | None = ("0010", "0011")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "traces",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=20), nullable=False),
        sa.Column("tool_name", sa.String(length=100), nullable=True),
        sa.Column("input", sa.JSON(), nullable=True),
        sa.Column("output", sa.JSON(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_traces_conversation_id", "traces", ["conversation_id"])
    op.create_index("ix_traces_message_id", "traces", ["message_id"])


def downgrade() -> None:
    op.drop_index("ix_traces_message_id", table_name="traces")
    op.drop_index("ix_traces_conversation_id", table_name="traces")
    op.drop_table("traces")
