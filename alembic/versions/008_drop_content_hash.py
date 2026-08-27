"""Drop unused content_hash columns.

Revision ID: 008
Revises: 007
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "008"
down_revision: str | None = "007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_documents_content_hash")
    op.drop_column("documents", "content_hash")
    op.drop_column("chunks", "content_hash")


def downgrade() -> None:
    op.add_column(
        "chunks",
        sa.Column("content_hash", sa.String(64), nullable=False, server_default=""),
    )
    op.add_column(
        "documents",
        sa.Column("content_hash", sa.String(64), nullable=False, server_default=""),
    )
    op.alter_column("chunks", "content_hash", server_default=None)
    op.alter_column("documents", "content_hash", server_default=None)
    op.create_index("ix_documents_content_hash", "documents", ["content_hash"])
