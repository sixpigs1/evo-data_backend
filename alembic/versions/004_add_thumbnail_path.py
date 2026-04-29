"""add thumbnail_path to datasets

Revision ID: 004
Revises: 003
Create Date: 2026-04-29
"""
from alembic import op
import sqlalchemy as sa

revision = '004_add_thumbnail_path'
down_revision = '003_tags_text'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('datasets', sa.Column('thumbnail_path', sa.String(1024), nullable=True))


def downgrade():
    op.drop_column('datasets', 'thumbnail_path')
