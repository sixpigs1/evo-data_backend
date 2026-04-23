"""Fix password column name: password_hash -> hashed_password

Revision ID: 002_fix_password_column
Revises: 001_initial
Create Date: 2026-04-23
"""
from alembic import op
import sqlalchemy as sa

revision = '002_fix_password_column'
down_revision = '001_initial'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 将 password_hash 列重命名为 hashed_password（MySQL 支持直接 RENAME COLUMN）
    op.alter_column(
        'users',
        'password_hash',
        new_column_name='hashed_password',
        existing_type=sa.String(length=128),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        'users',
        'hashed_password',
        new_column_name='password_hash',
        existing_type=sa.String(length=128),
        existing_nullable=True,
    )
