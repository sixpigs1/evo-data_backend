"""limit users to one membership

Revision ID: 008_membership_single_org
Revises: 007_collection_org_scope
Create Date: 2026-05-04
"""

from alembic import op


revision = "008_membership_single_org"
down_revision = "007_collection_org_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint("uq_membership_user", "memberships", ["user_id"])
    op.drop_index(op.f("ix_memberships_user_id"), table_name="memberships")


def downgrade() -> None:
    op.create_index(op.f("ix_memberships_user_id"), "memberships", ["user_id"])
    op.drop_constraint("uq_membership_user", "memberships", type_="unique")
