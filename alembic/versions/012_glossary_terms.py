"""Add glossary_terms for Sparse synonym expansion.

Revision ID: 012
Revises: 011
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "012"
down_revision: str | None = "011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "glossary_terms",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("standard_term", sa.String(length=256), nullable=False),
        sa.Column(
            "synonyms",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("category", sa.String(length=128), nullable=True),
        sa.Column("definition", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("standard_term", name="uq_glossary_terms_standard_term"),
    )
    op.create_index("ix_glossary_terms_enabled", "glossary_terms", ["enabled"])


def downgrade() -> None:
    op.drop_index("ix_glossary_terms_enabled", table_name="glossary_terms")
    op.drop_table("glossary_terms")
