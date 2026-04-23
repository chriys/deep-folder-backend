"""files table

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-23

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "files",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("folder_id", sa.Integer(), nullable=False),
        sa.Column("drive_file_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("modified_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["folder_id"], ["folders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_files_folder_id", "files", ["folder_id"])
    op.create_index("ix_files_drive_file_id", "files", ["drive_file_id"])


def downgrade() -> None:
    op.drop_index("ix_files_drive_file_id", table_name="files")
    op.drop_index("ix_files_folder_id", table_name="files")
    op.drop_table("files")
