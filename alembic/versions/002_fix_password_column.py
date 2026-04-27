"""Fix password column name: password_hash -> hashed_password

Revision ID: 002_fix_password_column
Revises: 001_initial
Create Date: 2026-04-23
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = '002_fix_password_column'
down_revision = '001_initial'
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = inspect(bind)
    return any(c['name'] == column for c in insp.get_columns(table))


def upgrade() -> None:
    # 仅当旧列 password_hash 存在时才重命名（RDS 上可能已是 hashed_password）
    if _column_exists('users', 'password_hash'):
        op.alter_column(
            'users',
            'password_hash',
            new_column_name='hashed_password',
            existing_type=sa.String(length=128),
            existing_nullable=True,
        )
    # 已经是 hashed_password 则无需操作


def downgrade() -> None:
    if _column_exists('users', 'hashed_password'):
        op.alter_column(
            'users',
            'hashed_password',
            new_column_name='password_hash',
            existing_type=sa.String(length=128),
            existing_nullable=True,
        )
