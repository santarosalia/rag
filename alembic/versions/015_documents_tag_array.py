"""Convert documents.tag from varchar to text[] for multi-tag AND filters.

Revision ID: 015
Revises: 014
"""

from collections.abc import Sequence

from alembic import op

revision: str = "015"
down_revision: str | None = "014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_documents_tag", table_name="documents")
    op.execute(
        """
        ALTER TABLE documents
        ALTER COLUMN tag TYPE text[]
        USING CASE
            WHEN tag IS NULL THEN NULL
            ELSE ARRAY[tag]::text[]
        END
        """
    )
    op.create_index(
        "ix_documents_tag",
        "documents",
        ["tag"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_documents_tag", table_name="documents")
    op.execute(
        """
        ALTER TABLE documents
        ALTER COLUMN tag TYPE character varying(128)
        USING CASE
            WHEN tag IS NULL OR cardinality(tag) = 0 THEN NULL
            ELSE tag[1]
        END
        """
    )
    op.create_index("ix_documents_tag", "documents", ["tag"])
