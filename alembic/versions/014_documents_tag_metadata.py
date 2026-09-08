"""Add documents.tag and documents.metadata.

Revision ID: 014
Revises: 013
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "014"
down_revision: str | None = "013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("tag", sa.String(length=128), nullable=True))
    op.add_column(
        "documents",
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
    )
    op.create_index("ix_documents_tag", "documents", ["tag"])


def downgrade() -> None:
    op.drop_index("ix_documents_tag", table_name="documents")
    op.drop_column("documents", "metadata")
    op.drop_column("documents", "tag")
