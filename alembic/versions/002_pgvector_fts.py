"""Add pgvector + FTS columns for PostgreSQL search backend.

Revision ID: 002
Revises: 001
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column("chunks", sa.Column("content_morph", sa.Text(), nullable=True))
    op.add_column("chunks", sa.Column("tsv", sa.dialects.postgresql.TSVECTOR(), nullable=True))
    op.execute("ALTER TABLE chunks ADD COLUMN IF NOT EXISTS embedding vector(1024)")
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw
        ON chunks USING hnsw (embedding vector_cosine_ops)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chunks_tsv_gin
        ON chunks USING GIN (tsv)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_chunks_tsv_gin")
    op.execute("DROP INDEX IF EXISTS idx_chunks_embedding_hnsw")
    op.drop_column("chunks", "embedding")
    op.drop_column("chunks", "tsv")
    op.drop_column("chunks", "content_morph")
