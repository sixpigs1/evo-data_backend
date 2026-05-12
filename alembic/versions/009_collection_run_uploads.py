"""add collection run upload tracking

Revision ID: 009_collection_run_uploads
Revises: 008_membership_single_org
Create Date: 2026-05-12
"""
from alembic import op
import sqlalchemy as sa


revision = "009_collection_run_uploads"
down_revision = "008_membership_single_org"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "collection_run_uploads",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("run_id", sa.CHAR(36), nullable=False),
        sa.Column("upload_id", sa.CHAR(36), nullable=True),
        sa.Column("oss_path", sa.String(1024), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "uploading",
                "uploaded",
                "validating",
                "passed",
                "failed",
                name="collectionrunuploadstatus",
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("total_files", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("uploaded_files", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("total_bytes", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("uploaded_bytes", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_uploaded_path", sa.String(1024), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["collection_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", name="uq_collection_run_uploads_run_id"),
    )
    op.create_index("ix_collection_run_uploads_status", "collection_run_uploads", ["status"])
    op.create_index("ix_collection_run_uploads_upload_id", "collection_run_uploads", ["upload_id"])


def downgrade() -> None:
    op.drop_index("ix_collection_run_uploads_upload_id", table_name="collection_run_uploads")
    op.drop_index("ix_collection_run_uploads_status", table_name="collection_run_uploads")
    op.drop_table("collection_run_uploads")
