"""add organizations and memberships

Revision ID: 006_organizations_memberships
Revises: 005_collection_tasks
Create Date: 2026-05-04
"""
from alembic import op
import sqlalchemy as sa

revision = "006_organizations_memberships"
down_revision = "005_collection_tasks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    user_status = sa.Enum("active", "disabled", name="userstatus")
    platform_role = sa.Enum("user", "system_admin", name="platformrole")

    op.add_column(
        "users",
        sa.Column("status", user_status, nullable=False, server_default="active"),
    )
    op.add_column(
        "users",
        sa.Column("platform_role", platform_role, nullable=False, server_default="user"),
    )

    op.execute(
        """
        UPDATE users
        SET status = CASE WHEN is_active = 0 THEN 'disabled' ELSE 'active' END,
            platform_role = CASE WHEN level = 'admin' THEN 'system_admin' ELSE 'user' END
        """
    )

    op.alter_column(
        "users",
        "status",
        server_default=None,
        existing_type=user_status,
        existing_nullable=False,
    )
    op.alter_column(
        "users",
        "platform_role",
        server_default=None,
        existing_type=platform_role,
        existing_nullable=False,
    )
    op.drop_column("users", "rank")
    op.drop_column("users", "level")
    op.drop_column("users", "is_active")

    op.create_table(
        "organizations",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column(
            "status",
            sa.Enum("active", "disabled", name="organizationstatus"),
            nullable=False,
        ),
        sa.Column("created_by_user_id", sa.CHAR(36), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_organizations_created_by_user_id"), "organizations", ["created_by_user_id"])
    op.create_index(op.f("ix_organizations_status"), "organizations", ["status"])

    op.create_table(
        "memberships",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("user_id", sa.CHAR(36), nullable=False),
        sa.Column("org_id", sa.CHAR(36), nullable=False),
        sa.Column(
            "role_code",
            sa.Enum("owner", "admin", "member", "viewer", name="membershiprole"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("active", "invited", "disabled", name="membershipstatus"),
            nullable=False,
        ),
        sa.Column("invited_by_user_id", sa.CHAR(36), nullable=True),
        sa.Column("joined_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["invited_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "org_id", name="uq_membership_user_org"),
    )
    op.create_index(op.f("ix_memberships_invited_by_user_id"), "memberships", ["invited_by_user_id"])
    op.create_index(op.f("ix_memberships_org_id"), "memberships", ["org_id"])
    op.create_index("ix_memberships_org_status_role", "memberships", ["org_id", "status", "role_code"])
    op.create_index(op.f("ix_memberships_user_id"), "memberships", ["user_id"])
    op.create_index("ix_memberships_user_status", "memberships", ["user_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_memberships_user_status", table_name="memberships")
    op.drop_index(op.f("ix_memberships_user_id"), table_name="memberships")
    op.drop_index("ix_memberships_org_status_role", table_name="memberships")
    op.drop_index(op.f("ix_memberships_org_id"), table_name="memberships")
    op.drop_index(op.f("ix_memberships_invited_by_user_id"), table_name="memberships")
    op.drop_table("memberships")
    op.drop_index(op.f("ix_organizations_status"), table_name="organizations")
    op.drop_index(op.f("ix_organizations_created_by_user_id"), table_name="organizations")
    op.drop_table("organizations")

    user_level = sa.Enum("normal", "contributor", "admin", name="userlevel")
    op.add_column("users", sa.Column("level", user_level, nullable=False, server_default="normal"))
    op.add_column("users", sa.Column("rank", sa.Integer(), nullable=True, server_default="0"))
    op.add_column("users", sa.Column("is_active", sa.Boolean(), nullable=True, server_default=sa.text("1")))
    op.execute(
        """
        UPDATE users
        SET level = CASE WHEN platform_role = 'system_admin' THEN 'admin' ELSE 'normal' END,
            is_active = CASE WHEN status = 'disabled' THEN 0 ELSE 1 END
        """
    )
    op.alter_column(
        "users",
        "level",
        server_default=None,
        existing_type=user_level,
        existing_nullable=False,
    )
    op.alter_column(
        "users",
        "rank",
        server_default=None,
        existing_type=sa.Integer(),
        existing_nullable=True,
    )
    op.alter_column(
        "users",
        "is_active",
        server_default=None,
        existing_type=sa.Boolean(),
        existing_nullable=True,
    )
    op.drop_column("users", "platform_role")
    op.drop_column("users", "status")
