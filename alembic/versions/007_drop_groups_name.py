"""Drop groups.name; group identity is id only.

Revision ID: 007
Revises: 006
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "007"
down_revision: str | None = "006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("uq_groups_name", table_name="groups")
    op.drop_column("groups", "name")


def downgrade() -> None:
    op.add_column("groups", sa.Column("name", sa.String(256), nullable=True))
    op.execute("UPDATE groups SET name = id WHERE name IS NULL")
    op.alter_column("groups", "name", nullable=False)
    op.create_index("uq_groups_name", "groups", ["name"], unique=True)
