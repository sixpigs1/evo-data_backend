from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import (
    Membership,
    MembershipRole,
    MembershipStatus,
    Organization,
    OrganizationStatus,
    User,
)


TASK_ADMIN_ROLES = (MembershipRole.owner, MembershipRole.admin)


def active_memberships(db: Session, user: User) -> list[Membership]:
    return (
        db.query(Membership)
        .join(Organization)
        .filter(
            Membership.user_id == user.id,
            Membership.status == MembershipStatus.active,
            Organization.status == OrganizationStatus.active,
        )
        .order_by(Membership.created_at.asc())
        .all()
    )


def account_memberships(db: Session, user: User) -> list[Membership]:
    return (
        db.query(Membership)
        .join(Organization)
        .filter(
            Membership.user_id == user.id,
            Membership.status.in_((MembershipStatus.active, MembershipStatus.invited)),
            Organization.status == OrganizationStatus.active,
        )
        .order_by(Membership.created_at.asc())
        .all()
    )


def current_membership(db: Session, user: User) -> Membership | None:
    memberships = active_memberships(db, user)
    return memberships[0] if memberships else None


def require_active_membership(db: Session, user: User) -> Membership:
    membership = current_membership(db, user)
    if membership is None:
        raise HTTPException(status_code=403, detail="请先加入组织")
    return membership


def require_task_admin(db: Session, user: User) -> Membership:
    membership = require_active_membership(db, user)
    if membership.role_code not in TASK_ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="仅组织 owner 或 admin 可访问")
    return membership


def require_owner(db: Session, user: User) -> Membership:
    membership = require_active_membership(db, user)
    if membership.role_code != MembershipRole.owner:
        raise HTTPException(status_code=403, detail="仅组织 owner 可访问")
    return membership
