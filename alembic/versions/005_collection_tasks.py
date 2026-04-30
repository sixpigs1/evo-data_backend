"""add collection task tracking

Revision ID: 005_collection_tasks
Revises: 004_add_thumbnail_path
Create Date: 2026-04-30
"""
from alembic import op
import sqlalchemy as sa

revision = '005_collection_tasks'
down_revision = '004_add_thumbnail_path'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'collection_tasks',
        sa.Column('id', sa.CHAR(36), nullable=False),
        sa.Column('name', sa.String(128), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('task_prompt', sa.Text(), nullable=False),
        sa.Column('num_episodes', sa.Integer(), nullable=False),
        sa.Column('fps', sa.Integer(), nullable=False),
        sa.Column('episode_time_s', sa.Integer(), nullable=False),
        sa.Column('reset_time_s', sa.Integer(), nullable=False),
        sa.Column('use_cameras', sa.Boolean(), nullable=False),
        sa.Column('arms', sa.String(128), nullable=False),
        sa.Column('dataset_prefix', sa.String(64), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_by_id', sa.CHAR(36), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.create_index(op.f('ix_collection_tasks_created_by_id'), 'collection_tasks', ['created_by_id'])
    op.create_index(op.f('ix_collection_tasks_name'), 'collection_tasks', ['name'])

    op.create_table(
        'collection_devices',
        sa.Column('id', sa.CHAR(36), nullable=False),
        sa.Column('name', sa.String(128), nullable=False),
        sa.Column('token_hash', sa.String(128), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(), nullable=True),
        sa.Column('metadata_json', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.create_index(op.f('ix_collection_devices_name'), 'collection_devices', ['name'])

    op.create_table(
        'collection_assignments',
        sa.Column('id', sa.CHAR(36), nullable=False),
        sa.Column('user_id', sa.CHAR(36), nullable=False),
        sa.Column('task_id', sa.CHAR(36), nullable=False),
        sa.Column('target_date', sa.Date(), nullable=False),
        sa.Column('target_seconds', sa.Integer(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_by_id', sa.CHAR(36), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['task_id'], ['collection_tasks.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'task_id', 'target_date', name='uq_collection_assignment_user_task_date'),
    )
    op.create_index(op.f('ix_collection_assignments_created_by_id'), 'collection_assignments', ['created_by_id'])
    op.create_index(op.f('ix_collection_assignments_task_id'), 'collection_assignments', ['task_id'])
    op.create_index(op.f('ix_collection_assignments_target_date'), 'collection_assignments', ['target_date'])
    op.create_index('ix_collection_assignments_date_user', 'collection_assignments', ['target_date', 'user_id'])
    op.create_index(op.f('ix_collection_assignments_user_id'), 'collection_assignments', ['user_id'])

    op.create_table(
        'collection_runs',
        sa.Column('id', sa.CHAR(36), nullable=False),
        sa.Column('user_id', sa.CHAR(36), nullable=False),
        sa.Column('assignment_id', sa.CHAR(36), nullable=True),
        sa.Column('task_id', sa.CHAR(36), nullable=True),
        sa.Column('device_id', sa.CHAR(36), nullable=True),
        sa.Column('dataset_name', sa.String(256), nullable=False),
        sa.Column('status', sa.Enum('active', 'finished', 'interrupted', 'failed', name='collectionrunstatus'), nullable=False),
        sa.Column('started_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('last_heartbeat_at', sa.DateTime(), nullable=True),
        sa.Column('stopped_at', sa.DateTime(), nullable=True),
        sa.Column('saved_episodes', sa.Integer(), nullable=False),
        sa.Column('total_frames', sa.Integer(), nullable=True),
        sa.Column('fps', sa.Integer(), nullable=True),
        sa.Column('duration_seconds', sa.Integer(), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('metadata_json', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['assignment_id'], ['collection_assignments.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['device_id'], ['collection_devices.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['task_id'], ['collection_tasks.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_collection_runs_assignment_id'), 'collection_runs', ['assignment_id'])
    op.create_index('ix_collection_runs_assignment_status', 'collection_runs', ['assignment_id', 'status'])
    op.create_index(op.f('ix_collection_runs_dataset_name'), 'collection_runs', ['dataset_name'])
    op.create_index(op.f('ix_collection_runs_device_id'), 'collection_runs', ['device_id'])
    op.create_index(op.f('ix_collection_runs_task_id'), 'collection_runs', ['task_id'])
    op.create_index(op.f('ix_collection_runs_user_id'), 'collection_runs', ['user_id'])
    op.create_index('ix_collection_runs_user_status', 'collection_runs', ['user_id', 'status'])


def downgrade():
    op.drop_index('ix_collection_runs_user_status', table_name='collection_runs')
    op.drop_index(op.f('ix_collection_runs_user_id'), table_name='collection_runs')
    op.drop_index(op.f('ix_collection_runs_task_id'), table_name='collection_runs')
    op.drop_index(op.f('ix_collection_runs_device_id'), table_name='collection_runs')
    op.drop_index(op.f('ix_collection_runs_dataset_name'), table_name='collection_runs')
    op.drop_index('ix_collection_runs_assignment_status', table_name='collection_runs')
    op.drop_index(op.f('ix_collection_runs_assignment_id'), table_name='collection_runs')
    op.drop_table('collection_runs')
    op.drop_index(op.f('ix_collection_assignments_user_id'), table_name='collection_assignments')
    op.drop_index('ix_collection_assignments_date_user', table_name='collection_assignments')
    op.drop_index(op.f('ix_collection_assignments_target_date'), table_name='collection_assignments')
    op.drop_index(op.f('ix_collection_assignments_task_id'), table_name='collection_assignments')
    op.drop_index(op.f('ix_collection_assignments_created_by_id'), table_name='collection_assignments')
    op.drop_table('collection_assignments')
    op.drop_index(op.f('ix_collection_devices_name'), table_name='collection_devices')
    op.drop_table('collection_devices')
    op.drop_index(op.f('ix_collection_tasks_name'), table_name='collection_tasks')
    op.drop_index(op.f('ix_collection_tasks_created_by_id'), table_name='collection_tasks')
    op.drop_table('collection_tasks')
