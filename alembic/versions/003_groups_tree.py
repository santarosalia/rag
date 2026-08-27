"""Add groups tree and replace tenant_id with group_id / group_path.

Revision ID: 003
Revises: 002
"""

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

DEFAULT_GROUP_ID = "00000000-0000-4000-8000-000000000001"
DEFAULT_GROUP_NAME = "default"

revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "groups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("slug", sa.String(128), nullable=True),
        sa.Column("path", sa.String(2048), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["parent_id"], ["groups.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_groups_parent_id", "groups", ["parent_id"])
    op.execute("CREATE INDEX ix_groups_path ON groups (path text_pattern_ops)")
    op.execute("CREATE UNIQUE INDEX uq_groups_root_name ON groups (name) WHERE parent_id IS NULL")
    op.execute(
        "CREATE UNIQUE INDEX uq_groups_sibling_name "
        "ON groups (parent_id, name) WHERE parent_id IS NOT NULL"
    )

    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            INSERT INTO groups (id, parent_id, name, slug, path, depth, created_at, updated_at)
            VALUES (:id, NULL, :name, NULL, :path, 0, NOW(), NOW())
            """
        ),
        {
            "id": DEFAULT_GROUP_ID,
            "name": DEFAULT_GROUP_NAME,
            "path": f"/{DEFAULT_GROUP_ID}",
        },
    )

    op.add_column(
        "documents",
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "chunks",
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column("chunks", sa.Column("group_path", sa.String(2048), nullable=True))

    tenant_rows = conn.execute(
        sa.text(
            """
            SELECT DISTINCT tenant_id
            FROM documents
            WHERE tenant_id IS NOT NULL
              AND btrim(tenant_id) <> ''
              AND tenant_id <> :default_name
            """
        ),
        {"default_name": DEFAULT_GROUP_NAME},
    ).fetchall()
    for (tenant_id,) in tenant_rows:
        group_id = str(uuid4())
        conn.execute(
            sa.text(
                """
                INSERT INTO groups (id, parent_id, name, slug, path, depth, created_at, updated_at)
                VALUES (:id, NULL, :name, NULL, :path, 0, NOW(), NOW())
                """
            ),
            {"id": group_id, "name": tenant_id, "path": f"/{group_id}"},
        )

    conn.execute(
        sa.text(
            """
            UPDATE documents AS d
            SET group_id = g.id
            FROM groups AS g
            WHERE g.parent_id IS NULL
              AND d.tenant_id IS NOT NULL
              AND btrim(d.tenant_id) <> ''
              AND d.tenant_id = g.name
            """
        )
    )
    conn.execute(
        sa.text("UPDATE documents SET group_id = :default_id WHERE group_id IS NULL"),
        {"default_id": DEFAULT_GROUP_ID},
    )
    conn.execute(
        sa.text(
            """
            UPDATE chunks AS c
            SET group_id = d.group_id,
                group_path = g.path
            FROM documents AS d
            JOIN groups AS g ON g.id = d.group_id
            WHERE c.doc_id = d.id
            """
        )
    )

    op.alter_column("documents", "group_id", nullable=False)
    op.alter_column("chunks", "group_id", nullable=False)
    op.alter_column("chunks", "group_path", nullable=False)
    op.create_index("ix_documents_group_id", "documents", ["group_id"])
    op.create_index("ix_chunks_group_id", "chunks", ["group_id"])
    op.execute("CREATE INDEX ix_chunks_group_path ON chunks (group_path text_pattern_ops)")
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

    op.drop_index("ix_documents_tenant_id", table_name="documents")
    op.drop_index("ix_chunks_tenant_id", table_name="chunks")
    op.drop_column("documents", "tenant_id")
    op.drop_column("chunks", "tenant_id")


def downgrade() -> None:
    op.add_column("chunks", sa.Column("tenant_id", sa.String(128), nullable=True))
    op.add_column("documents", sa.Column("tenant_id", sa.String(128), nullable=True))
    op.create_index("ix_chunks_tenant_id", "chunks", ["tenant_id"])
    op.create_index("ix_documents_tenant_id", "documents", ["tenant_id"])

    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE documents AS d
            SET tenant_id = g.name
            FROM groups AS g
            WHERE d.group_id = g.id
            """
        )
    )
    conn.execute(
        sa.text(
            """
            UPDATE chunks AS c
            SET tenant_id = d.tenant_id
            FROM documents AS d
            WHERE c.doc_id = d.id
            """
        )
    )

    op.drop_constraint("fk_chunks_group_id", "chunks", type_="foreignkey")
    op.drop_constraint("fk_documents_group_id", "documents", type_="foreignkey")
    op.execute("DROP INDEX IF EXISTS ix_chunks_group_path")
    op.drop_index("ix_chunks_group_id", table_name="chunks")
    op.drop_index("ix_documents_group_id", table_name="documents")
    op.drop_column("chunks", "group_path")
    op.drop_column("chunks", "group_id")
    op.drop_column("documents", "group_id")
    op.execute("DROP INDEX IF EXISTS uq_groups_sibling_name")
    op.execute("DROP INDEX IF EXISTS uq_groups_root_name")
    op.execute("DROP INDEX IF EXISTS ix_groups_path")
    op.drop_index("ix_groups_parent_id", table_name="groups")
    op.drop_table("groups")
