"""Add embedding column to chunks table

Revision ID: 0010
Revises: 0009
Create Date: 2026-04-23

pgvector dimensionality: 1024 (Voyage embedding dimension)
Index type: IVFFlat is chosen over HNSW for better space efficiency at scale.
IVFFlat is suitable for retrieval of top-K results without exact nearest-neighbor guarantees.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT 1 FROM pg_extension WHERE extname = 'vector'"
    ))
    if result.fetchone() is None:
        return
    op.execute(sa.text("ALTER TABLE chunks ADD COLUMN IF NOT EXISTS embedding vector(1024)"))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_chunks_embedding_ivfflat "
        "ON chunks USING ivfflat (embedding vector_cosine_ops)"
    ))


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chunks_embedding_ivfflat")
    op.execute("ALTER TABLE chunks DROP COLUMN embedding")
