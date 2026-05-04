"""scope collection resources by organization

Revision ID: 007_collection_org_scope
Revises: 006_organizations_memberships
Create Date: 2026-05-04
"""
from alembic import op
import sqlalchemy as sa

revision = "007_collection_org_scope"
down_revision = "006_organizations_memberships"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE memberships SET role_code = 'member' WHERE role_code = 'viewer'")
    op.execute("ALTER TABLE memberships MODIFY role_code ENUM('owner','admin','member') NOT NULL")

    op.execute(
        """
        INSERT INTO organizations (id, name, status, created_at, updated_at)
        SELECT UUID(), 'EvoMind', 'active', NOW(), NOW()
        WHERE NOT EXISTS (
            SELECT 1 FROM organizations WHERE name IN ('EvoMind', 'Evo Mind')
        )
        """
    )
    op.execute("SET @evomind_org_id := (SELECT id FROM organizations WHERE name IN ('EvoMind', 'Evo Mind') ORDER BY created_at LIMIT 1)")

    op.add_column("collection_tasks", sa.Column("org_id", sa.CHAR(36), nullable=True))
    op.add_column("collection_assignments", sa.Column("org_id", sa.CHAR(36), nullable=True))
    op.add_column("collection_runs", sa.Column("org_id", sa.CHAR(36), nullable=True))

    op.execute("UPDATE collection_tasks SET org_id = @evomind_org_id WHERE org_id IS NULL")
    op.execute(
        """
        UPDATE collection_assignments AS assignment
        JOIN collection_tasks AS task ON task.id = assignment.task_id
        SET assignment.org_id = task.org_id
        WHERE assignment.org_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE collection_runs AS run
        LEFT JOIN collection_tasks AS task ON task.id = run.task_id
        LEFT JOIN collection_assignments AS assignment ON assignment.id = run.assignment_id
        SET run.org_id = COALESCE(task.org_id, assignment.org_id, @evomind_org_id)
        WHERE run.org_id IS NULL
        """
    )

    op.alter_column("collection_tasks", "org_id", existing_type=sa.CHAR(36), nullable=False)
    op.alter_column("collection_assignments", "org_id", existing_type=sa.CHAR(36), nullable=False)
    op.alter_column("collection_runs", "org_id", existing_type=sa.CHAR(36), nullable=False)

    op.create_index("ix_collection_tasks_org_id", "collection_tasks", ["org_id"])
    op.create_index("ix_collection_assignments_org_id", "collection_assignments", ["org_id"])
    op.create_index("ix_collection_runs_org_id", "collection_runs", ["org_id"])
    op.create_foreign_key(
        "fk_collection_tasks_org_id",
        "collection_tasks",
        "organizations",
        ["org_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_collection_assignments_org_id",
        "collection_assignments",
        "organizations",
        ["org_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_collection_runs_org_id",
        "collection_runs",
        "organizations",
        ["org_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_collection_runs_org_id", "collection_runs", type_="foreignkey")
    op.drop_constraint("fk_collection_assignments_org_id", "collection_assignments", type_="foreignkey")
    op.drop_constraint("fk_collection_tasks_org_id", "collection_tasks", type_="foreignkey")
    op.drop_index("ix_collection_runs_org_id", table_name="collection_runs")
    op.drop_index("ix_collection_assignments_org_id", table_name="collection_assignments")
    op.drop_index("ix_collection_tasks_org_id", table_name="collection_tasks")
    op.drop_column("collection_runs", "org_id")
    op.drop_column("collection_assignments", "org_id")
    op.drop_column("collection_tasks", "org_id")
    op.execute("ALTER TABLE memberships MODIFY role_code ENUM('owner','admin','member','viewer') NOT NULL")
