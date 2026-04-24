"""Baseline: enable pgvector extension

Revision ID: 001
Revises:
Create Date: 2026-04-23 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(
        "DO $$ BEGIN CREATE EXTENSION IF NOT EXISTS vector; "
        "EXCEPTION WHEN insufficient_privilege THEN NULL; END $$"
    ))


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS vector")
