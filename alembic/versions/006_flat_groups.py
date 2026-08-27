"""Flatten groups tree and switch group ids to varchar.

Revision ID: 006
Revises: 005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "006"
down_revision: str | None = "005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("fk_chunks_group_id", "chunks", type_="foreignkey")
    op.drop_constraint("fk_documents_group_id", "documents", type_="foreignkey")
    op.drop_constraint("groups_parent_id_fkey", "groups", type_="foreignkey")

    op.execute("DROP INDEX IF EXISTS ix_chunks_group_path")
    op.execute("DROP INDEX IF EXISTS ix_groups_path")
    op.execute("DROP INDEX IF EXISTS ix_groups_parent_id")
    op.execute("DROP INDEX IF EXISTS uq_groups_root_name")
    op.execute("DROP INDEX IF EXISTS uq_groups_sibling_name")

    op.execute(
        """
        UPDATE groups
        SET name = name || '-' || left(id::text, 8)
        WHERE id IN (
            SELECT id FROM (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY name ORDER BY depth, created_at, id
                       ) AS rn
                FROM groups
            ) ranked
            WHERE rn > 1
        )
        """
    )

    op.alter_column(
        "groups",
        "id",
        existing_type=postgresql.UUID(as_uuid=True),
        type_=sa.String(128),
        postgresql_using="id::text",
    )
    op.alter_column(
        "documents",
        "group_id",
        existing_type=postgresql.UUID(as_uuid=True),
        type_=sa.String(128),
        postgresql_using="group_id::text",
    )
    op.alter_column(
        "chunks",
        "group_id",
        existing_type=postgresql.UUID(as_uuid=True),
        type_=sa.String(128),
        postgresql_using="group_id::text",
    )

    op.drop_column("chunks", "group_path")
    op.drop_column("groups", "parent_id")
    op.drop_column("groups", "path")
    op.drop_column("groups", "depth")

    op.create_index("uq_groups_name", "groups", ["name"], unique=True)
    op.create_foreign_key(
        "fk_documents_group_id",
        "documents",
        "groups",
        ["group_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_chunks_group_id",
        "chunks",
        "groups",
        ["group_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint("fk_chunks_group_id", "chunks", type_="foreignkey")
    op.drop_constraint("fk_documents_group_id", "documents", type_="foreignkey")
    op.drop_index("uq_groups_name", table_name="groups")

    op.add_column(
        "groups",
        sa.Column("depth", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "groups",
        sa.Column("path", sa.String(2048), nullable=False, server_default=""),
    )
    op.add_column(
        "groups",
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "chunks",
        sa.Column("group_path", sa.String(2048), nullable=False, server_default=""),
    )
    op.alter_column("groups", "depth", server_default=None)
    op.alter_column("groups", "path", server_default=None)
    op.alter_column("chunks", "group_path", server_default=None)

    op.alter_column(
        "chunks",
        "group_id",
        existing_type=sa.String(128),
        type_=postgresql.UUID(as_uuid=True),
        postgresql_using="group_id::uuid",
    )
    op.alter_column(
        "documents",
        "group_id",
        existing_type=sa.String(128),
        type_=postgresql.UUID(as_uuid=True),
        postgresql_using="group_id::uuid",
    )
    op.alter_column(
        "groups",
        "id",
        existing_type=sa.String(128),
        type_=postgresql.UUID(as_uuid=True),
        postgresql_using="id::uuid",
    )

    op.execute("UPDATE groups SET path = '/' || id::text")
    op.execute("UPDATE chunks SET group_path = '/' || group_id::text")

    op.create_index("ix_groups_parent_id", "groups", ["parent_id"])
    op.execute("CREATE INDEX ix_groups_path ON groups (path text_pattern_ops)")
    op.execute("CREATE UNIQUE INDEX uq_groups_root_name ON groups (name) WHERE parent_id IS NULL")
    op.execute(
        "CREATE UNIQUE INDEX uq_groups_sibling_name "
        "ON groups (parent_id, name) WHERE parent_id IS NOT NULL"
    )
    op.execute("CREATE INDEX ix_chunks_group_path ON chunks (group_path text_pattern_ops)")
    op.create_foreign_key(
        "groups_parent_id_fkey",
        "groups",
        "groups",
        ["parent_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_documents_group_id",
        "documents",
        "groups",
        ["group_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_chunks_group_id",
        "chunks",
        "groups",
        ["group_id"],
        ["id"],
        ondelete="RESTRICT",
    )
