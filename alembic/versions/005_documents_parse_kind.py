"""Add documents.parse_kind for original vs pre-parsed markdown.

Revision ID: 005
Revises: 004
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "005"
down_revision: str | None = "004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("parse_kind", sa.String(16), nullable=False, server_default="original"),
    )
    op.alter_column("documents", "parse_kind", server_default=None)


def downgrade() -> None:
    op.drop_column("documents", "parse_kind")
