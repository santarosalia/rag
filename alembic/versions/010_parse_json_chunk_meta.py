"""Store ParseResponse on documents; chunk type/bbox; drop s3_key.

Revision ID: 010
Revises: 009
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "010"
down_revision: str | None = "009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EMPTY_PARSE = '{"status":"FAIL","results":[],"error":"pre-migration document"}'


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("parse_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.execute(sa.text(f"UPDATE documents SET parse_json = '{_EMPTY_PARSE}'::jsonb WHERE parse_json IS NULL"))
    op.alter_column("documents", "parse_json", nullable=False)
    op.drop_column("documents", "s3_key")

    op.add_column("chunks", sa.Column("type", sa.String(length=64), nullable=True))
    op.add_column(
        "chunks",
        sa.Column("bbox", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chunks", "bbox")
    op.drop_column("chunks", "type")
    op.add_column(
        "documents",
        sa.Column("s3_key", sa.String(length=1024), nullable=False, server_default=""),
    )
    op.alter_column("documents", "s3_key", server_default=None)
    op.drop_column("documents", "parse_json")
