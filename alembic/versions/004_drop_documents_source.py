"""Drop redundant documents.source column.

Revision ID: 004
Revises: 003
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("documents", "source")


def downgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("source", sa.String(512), nullable=False, server_default=""),
    )
    op.execute("UPDATE documents SET source = filename WHERE source = ''")
    op.alter_column("documents", "source", server_default=None)
