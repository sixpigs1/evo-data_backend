"""Initial migration

Revision ID: 001_initial
Revises: 
Create Date: 2026-04-21
"""
from alembic import op
import sqlalchemy as sa

revision = '001_initial'
down_revision = None
branch_labels = None
depends_on = None

# MySQL 使用 CHAR(36) 存储 UUID，不使用 PostgreSQL 方言


def upgrade() -> None:
    # users
    op.create_table(
        'users',
        sa.Column('id', sa.CHAR(36), nullable=False),
        sa.Column('phone', sa.String(length=20), nullable=False),
        sa.Column('password_hash', sa.String(length=128), nullable=True),
        sa.Column('nickname', sa.String(length=64), nullable=True),
        sa.Column('level', sa.Enum('normal', 'contributor', 'admin', name='userlevel'), nullable=False),
        sa.Column('rank', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), onupdate=sa.text('now()'), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_users_phone'), 'users', ['phone'], unique=True)

    # datasets
    op.create_table(
        'datasets',
        sa.Column('id', sa.CHAR(36), nullable=False),
        sa.Column('owner_id', sa.CHAR(36), nullable=False),
        sa.Column('name', sa.String(length=256), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('tags', sa.String(length=512), nullable=True),
        sa.Column('is_public', sa.Boolean(), nullable=True),
        sa.Column('version', sa.Enum('2.1', '3.0', 'unknown', name='datasetversion'), nullable=True),
        sa.Column('oss_path', sa.String(length=1024), nullable=True),
        sa.Column('total_episodes', sa.Integer(), nullable=True),
        sa.Column('total_frames', sa.Integer(), nullable=True),
        sa.Column('size_bytes', sa.BigInteger(), nullable=True),
        sa.Column('robot', sa.String(length=128), nullable=True),
        sa.Column('license', sa.String(length=128), nullable=True),
        sa.Column('has_preview', sa.Boolean(), nullable=True),
        sa.Column('preview_path', sa.String(length=1024), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), onupdate=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_datasets_owner_id'), 'datasets', ['owner_id'])

    # uploads
    op.create_table(
        'uploads',
        sa.Column('id', sa.CHAR(36), nullable=False),
        sa.Column('user_id', sa.CHAR(36), nullable=False),
        sa.Column('dataset_id', sa.CHAR(36), nullable=True),
        sa.Column('oss_path', sa.String(length=1024), nullable=False),
        sa.Column('dataset_name', sa.String(length=256), nullable=True),
        sa.Column('status', sa.Enum('pending', 'validating', 'passed', 'failed', name='uploadstatus'), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('detected_version', sa.Enum('2.1', '3.0', 'unknown', name='datasetversion'), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), onupdate=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_uploads_user_id'), 'uploads', ['user_id'])

    # contributions
    op.create_table(
        'contributions',
        sa.Column('id', sa.CHAR(36), nullable=False),
        sa.Column('user_id', sa.CHAR(36), nullable=False),
        sa.Column('dataset_id', sa.CHAR(36), nullable=False),
        sa.Column('upload_id', sa.CHAR(36), nullable=True),
        sa.Column('status', sa.Enum('pending', 'validating', 'passed', 'failed', name='uploadstatus'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['upload_id'], ['uploads.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('contributions')
    op.drop_table('uploads')
    op.drop_index(op.f('ix_datasets_owner_id'), table_name='datasets')
    op.drop_table('datasets')
    op.drop_index(op.f('ix_users_phone'), table_name='users')
    op.drop_table('users')
