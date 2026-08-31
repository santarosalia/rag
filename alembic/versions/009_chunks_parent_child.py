"""Add chunks.role, parent_chunk_id, kind for hierarchical parent-child.

Revision ID: 009
Revises: 008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "009"
down_revision: str | None = "008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chunks",
        sa.Column("role", sa.String(16), nullable=False, server_default="child"),
    )
    op.add_column(
        "chunks",
        sa.Column("kind", sa.String(16), nullable=False, server_default="prose"),
    )
    op.add_column(
        "chunks",
        sa.Column("parent_chunk_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_chunks_parent_chunk_id",
        "chunks",
        "chunks",
        ["parent_chunk_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_chunks_parent_chunk_id", "chunks", ["parent_chunk_id"])
    op.alter_column("chunks", "role", server_default=None)
    op.alter_column("chunks", "kind", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_chunks_parent_chunk_id", table_name="chunks")
    op.drop_constraint("fk_chunks_parent_chunk_id", "chunks", type_="foreignkey")
    op.drop_column("chunks", "parent_chunk_id")
    op.drop_column("chunks", "kind")
    op.drop_column("chunks", "role")
