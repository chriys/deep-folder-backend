"""add router_label column to messages table

Revision ID: 0012
Revises: 0011
Create Date: 2026-04-24

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("router_label", sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("messages", "router_label")
