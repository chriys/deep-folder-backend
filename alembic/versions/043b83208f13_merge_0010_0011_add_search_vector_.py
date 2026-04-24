"""merge 0010, 0011 — add search_vector tsvector column to chunks

Revision ID: 043b83208f13
Revises: 0010, 0011
Create Date: 2026-04-24

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "043b83208f13"
down_revision: str | Sequence[str] | None = ("0010", "0011")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text(
        "ALTER TABLE chunks ADD COLUMN IF NOT EXISTS search_vector tsvector"
    ))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_chunks_search_vector_gin "
        "ON chunks USING GIN (search_vector)"
    ))
    op.execute(sa.text(
        "CREATE OR REPLACE FUNCTION chunks_search_vector_update() RETURNS trigger AS $$ "
        "BEGIN "
        "  NEW.search_vector := to_tsvector('english', NEW.text); "
        "  RETURN NEW; "
        "END; "
        "$$ LANGUAGE plpgsql"
    ))
    op.execute(sa.text(
        "DROP TRIGGER IF EXISTS trg_chunks_search_vector ON chunks"
    ))
    op.execute(sa.text(
        "CREATE TRIGGER trg_chunks_search_vector "
        "BEFORE INSERT OR UPDATE OF text ON chunks "
        "FOR EACH ROW EXECUTE FUNCTION chunks_search_vector_update()"
    ))


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_chunks_search_vector ON chunks")
    op.execute("DROP FUNCTION IF EXISTS chunks_search_vector_update()")
    op.execute("DROP INDEX IF EXISTS ix_chunks_search_vector_gin")
    op.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS search_vector")
