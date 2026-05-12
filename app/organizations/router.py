from typing import Literal, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import Membership, MembershipRole, MembershipStatus, OrganizationStatus, User
from app.organization_access import require_active_membership, require_task_admin

router = APIRouter(prefix="/organizations", tags=["organizations"])

RoleCode = Literal["owner", "admin", "member"]
InviteRoleCode = Literal["admin", "member"]
MemberStatus = Literal["active", "invited", "disabled"]


class OrganizationMemberResponse(BaseModel):
    id: str
    user_id: str
    phone: str
    nickname: Optional[str]
    role_code: RoleCode
    status: str
    joined_at: Optional[str] = None


class CurrentOrganizationResponse(BaseModel):
    id: str
    name: str
    role_code: RoleCode
    members: list[OrganizationMemberResponse]


class MemberUpsertRequest(BaseModel):
    phone: str
    role_code: InviteRoleCode = "member"

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        value = value.strip()
        if not value.isdigit() or len(value) != 11 or not value.startswith("1"):
            raise ValueError("手机号格式不正确")
        return value


class MemberUpdateRequest(BaseModel):
    role_code: Optional[InviteRoleCode] = None
    status: Optional[MemberStatus] = None


def _enum_value(value):
    return value.value if hasattr(value, "value") else value


def _member_response(membership: Membership) -> OrganizationMemberResponse:
    return OrganizationMemberResponse(
        id=str(membership.id),
        user_id=str(membership.user_id),
        phone=membership.user.phone,
        nickname=membership.user.nickname,
        role_code=_enum_value(membership.role_code),
        status=_enum_value(membership.status),
        joined_at=membership.joined_at.isoformat() if membership.joined_at else None,
    )


def _active_owner_count(db: Session, org_id: str) -> int:
    return (
        db.query(Membership)
        .filter(
            Membership.org_id == org_id,
            Membership.role_code == MembershipRole.owner,
            Membership.status == MembershipStatus.active,
        )
        .count()
    )


def _ensure_owner_remains(db: Session, membership: Membership, next_role: MembershipRole, next_status: MembershipStatus) -> None:
    if membership.role_code != MembershipRole.owner or membership.status != MembershipStatus.active:
        return
    if next_role == MembershipRole.owner and next_status == MembershipStatus.active:
        return
    if _active_owner_count(db, str(membership.org_id)) <= 1:
        raise HTTPException(status_code=409, detail="组织至少需要保留一个 active owner")


def _organization_members(db: Session, org_id: str) -> list[Membership]:
    return (
        db.query(Membership)
        .join(User, User.id == Membership.user_id)
        .filter(Membership.org_id == org_id)
        .order_by(Membership.created_at.asc())
        .all()
    )


def _ensure_invite_role(actor_membership: Membership, role_code: InviteRoleCode, existing: Membership | None) -> None:
    if actor_membership.role_code == MembershipRole.owner:
        return
    if role_code != "member":
        raise HTTPException(status_code=403, detail="admin 只能邀请 member")
    if existing is not None and existing.role_code != MembershipRole.member:
        raise HTTPException(status_code=403, detail="admin 只能管理 member 邀请")


def _ensure_member_management(
    actor_membership: Membership,
    membership: Membership,
    next_role: MembershipRole,
    next_status: MembershipStatus,
) -> None:
    if actor_membership.role_code == MembershipRole.owner:
        return
    if membership.role_code != MembershipRole.member or next_role != MembershipRole.member:
        raise HTTPException(status_code=403, detail="admin 只能管理 member")
    if next_status not in (MembershipStatus.invited, MembershipStatus.disabled):
        raise HTTPException(status_code=403, detail="admin 只能取消 member 邀请或移除 member")


def _active_membership_in_other_org(db: Session, user_id: str, org_id: str) -> Membership | None:
    return (
        db.query(Membership)
        .filter(
            Membership.user_id == user_id,
            Membership.org_id != org_id,
            Membership.status == MembershipStatus.active,
        )
        .first()
    )


@router.get("/current", response_model=CurrentOrganizationResponse)
def current_organization(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    membership = require_active_membership(db, current_user)
    return CurrentOrganizationResponse(
        id=str(membership.organization.id),
        name=membership.organization.name,
        role_code=_enum_value(membership.role_code),
        members=[_member_response(item) for item in _organization_members(db, str(membership.org_id))],
    )


@router.post("/current/members", response_model=OrganizationMemberResponse, status_code=status.HTTP_201_CREATED)
def upsert_member(
    body: MemberUpsertRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    actor_membership = require_task_admin(db, current_user)
    user = db.query(User).filter(User.phone == body.phone).first()
    if user is None:
        user = User(phone=body.phone)
        db.add(user)
        db.flush()

    membership = (
        db.query(Membership)
        .filter(
            Membership.user_id == user.id,
            Membership.org_id == actor_membership.org_id,
        )
        .first()
    )
    invite_role = body.role_code
    _ensure_invite_role(actor_membership, invite_role, membership)
    if membership is None:
        membership = Membership(
            id=str(uuid4()),
            user_id=user.id,
            org_id=actor_membership.org_id,
            role_code=MembershipRole(invite_role),
            status=MembershipStatus.invited,
            invited_by_user_id=current_user.id,
            joined_at=None,
        )
        db.add(membership)
    else:
        if membership.status == MembershipStatus.active:
            raise HTTPException(status_code=409, detail="该用户已经在当前组织中")
        membership.role_code = MembershipRole(invite_role)
        membership.status = MembershipStatus.invited
        membership.invited_by_user_id = current_user.id
    db.commit()
    db.refresh(membership)
    return _member_response(membership)


@router.patch("/current/members/{membership_id}", response_model=OrganizationMemberResponse)
def update_member(
    membership_id: str,
    body: MemberUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    actor_membership = require_task_admin(db, current_user)
    membership = (
        db.query(Membership)
        .filter(
            Membership.id == membership_id,
            Membership.org_id == actor_membership.org_id,
        )
        .first()
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="成员不存在")

    next_role = MembershipRole(body.role_code) if body.role_code is not None else membership.role_code
    next_status = MembershipStatus(body.status) if body.status is not None else membership.status
    if membership.status == MembershipStatus.invited and next_status == MembershipStatus.active:
        raise HTTPException(status_code=409, detail="邀请需要用户本人接受")
    _ensure_member_management(actor_membership, membership, next_role, next_status)
    _ensure_owner_remains(db, membership, next_role, next_status)
    membership.role_code = next_role
    membership.status = next_status
    if next_status == MembershipStatus.active and membership.joined_at is None:
        membership.joined_at = func.now()
    db.commit()
    db.refresh(membership)
    return _member_response(membership)


@router.patch("/memberships/{membership_id}/response", response_model=OrganizationMemberResponse)
def respond_membership_invitation(
    membership_id: str,
    body: MemberUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if body.status not in ("active", "disabled"):
        raise HTTPException(status_code=400, detail="邀请响应只能是 active 或 disabled")
    membership = (
        db.query(Membership)
        .filter(
            Membership.id == membership_id,
            Membership.user_id == current_user.id,
        )
        .first()
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="邀请不存在")
    if membership.organization.status != OrganizationStatus.active:
        raise HTTPException(status_code=409, detail="组织不可用")
    if membership.status not in (MembershipStatus.invited, MembershipStatus.active):
        raise HTTPException(status_code=409, detail="邀请已关闭")

    next_status = MembershipStatus(body.status)
    if next_status == MembershipStatus.active:
        other_membership = _active_membership_in_other_org(db, str(current_user.id), str(membership.org_id))
        if other_membership is not None:
            raise HTTPException(status_code=409, detail="需要先退出已有组织，才能加入新的组织")
        membership.status = MembershipStatus.active
        if membership.joined_at is None:
            membership.joined_at = func.now()
    else:
        _ensure_owner_remains(db, membership, membership.role_code, MembershipStatus.disabled)
        membership.status = MembershipStatus.disabled

    db.commit()
    db.refresh(membership)
    return _member_response(membership)
