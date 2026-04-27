"""expand tags column to Text for JSON storage

Revision ID: 003_tags_text
Revises: 002_fix_password_column
Create Date: 2026-04-27
"""
from alembic import op
import sqlalchemy as sa

revision = '003_tags_text'
down_revision = '002_fix_password_column'
branch_labels = None
depends_on = None


def upgrade():
    # 将 tags 列从 VARCHAR(512) 扩展为 TEXT，以支持 JSON 格式存储
    op.alter_column(
        'datasets',
        'tags',
        existing_type=sa.String(512),
        type_=sa.Text(),
        existing_nullable=True,
    )


def downgrade():
    # 回滚时截断为 VARCHAR(512)（可能导致数据丢失，谨慎操作）
    op.alter_column(
        'datasets',
        'tags',
        existing_type=sa.Text(),
        type_=sa.String(512),
        existing_nullable=True,
    )
