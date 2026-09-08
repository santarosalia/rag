"""Drop ingest_jobs (sync ingest; Celery removed).

Revision ID: 013
Revises: 012
Create Date: 2026-09-08
"""

from alembic import op

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_ingest_jobs_status", table_name="ingest_jobs")
    op.drop_index("ix_ingest_jobs_doc_id", table_name="ingest_jobs")
    op.drop_table("ingest_jobs")
    op.execute("DROP TYPE IF EXISTS jobstatus")


def downgrade() -> None:
    import sqlalchemy as sa
    from sqlalchemy.dialects import postgresql

    op.create_table(
        "ingest_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "doc_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
        ),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "running", "completed", "failed", name="jobstatus"),
            nullable=False,
        ),
        sa.Column("celery_task_id", sa.String(128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
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
    )
    op.create_index("ix_ingest_jobs_doc_id", "ingest_jobs", ["doc_id"])
    op.create_index("ix_ingest_jobs_status", "ingest_jobs", ["status"])
    op.create_unique_constraint("uq_ingest_jobs_idempotency_key", "ingest_jobs", ["idempotency_key"])
