"""Drop documents.parse_kind (Markdown-only ingest).

Revision ID: 009
Revises: 008
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "009"
down_revision: str | None = "008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("documents", "parse_kind")


def downgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("parse_kind", sa.String(16), nullable=False, server_default="markdown"),
    )
    op.alter_column("documents", "parse_kind", server_default=None)
