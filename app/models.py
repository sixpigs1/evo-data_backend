import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, CHAR, Column, Date, DateTime, Enum, ForeignKey,
    Index, Integer, String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import relationship

from app.database import Base


# MySQL 兼容的 UUID 类型：存储为 CHAR(36) 字符串
def new_uuid() -> str:
    return str(uuid.uuid4())


class UserStatus(str, enum.Enum):
    active = "active"
    disabled = "disabled"


class PlatformRole(str, enum.Enum):
    user = "user"
    system_admin = "system_admin"


class OrganizationStatus(str, enum.Enum):
    active = "active"
    disabled = "disabled"


class MembershipRole(str, enum.Enum):
    owner = "owner"
    admin = "admin"
    member = "member"


class MembershipStatus(str, enum.Enum):
    active = "active"
    invited = "invited"
    disabled = "disabled"


class UploadStatus(str, enum.Enum):
    pending = "pending"
    validating = "validating"
    passed = "passed"
    failed = "failed"


class DatasetVersion(str, enum.Enum):
    v2_1 = "2.1"
    v3_0 = "3.0"
    unknown = "unknown"


class CollectionRunStatus(str, enum.Enum):
    active = "active"
    finished = "finished"
    interrupted = "interrupted"
    failed = "failed"


class CollectionRunUploadStatus(str, enum.Enum):
    pending = "pending"
    uploading = "uploading"
    uploaded = "uploaded"
    validating = "validating"
    passed = "passed"
    failed = "failed"


class CreditAccountType(str, enum.Enum):
    data = "data"
    training = "training"


class CreditAccountStatus(str, enum.Enum):
    active = "active"
    frozen = "frozen"
    closed = "closed"


class CreditLedgerEntryType(str, enum.Enum):
    initial_grant = "initial_grant"
    recharge = "recharge"
    upload_reward = "upload_reward"
    dataset_purchase = "dataset_purchase"
    training_hold = "training_hold"
    training_release = "training_release"
    training_settle = "training_settle"
    manual_adjust = "manual_adjust"


class PaymentProvider(str, enum.Enum):
    wechat = "wechat"
    alipay = "alipay"
    manual = "manual"


class PaymentOrderStatus(str, enum.Enum):
    created = "created"
    paid = "paid"
    failed = "failed"
    closed = "closed"
    refunded = "refunded"


class UploadRewardGrantStatus(str, enum.Enum):
    pending_review = "pending_review"
    approved = "approved"
    rewarded = "rewarded"
    rejected = "rejected"
    revoked = "revoked"


class ResourceUsageStatus(str, enum.Enum):
    pending = "pending"
    held = "held"
    settled = "settled"
    failed = "failed"
    refunded = "refunded"


class DatasetPriceStatus(str, enum.Enum):
    active = "active"
    inactive = "inactive"


class DatasetPurchaseGrantStatus(str, enum.Enum):
    active = "active"
    refunded = "refunded"


class RemoteTrainingJobStatus(str, enum.Enum):
    held = "held"
    running = "running"
    settled = "settled"
    failed = "failed"


# ─── Users ────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id = Column(CHAR(36), primary_key=True, default=new_uuid)
    phone = Column(String(20), unique=True, nullable=False, index=True)
    hashed_password = Column(String(128), nullable=True)  # 预留密码字段
    nickname = Column(String(64), nullable=True)
    status = Column(Enum(UserStatus, values_callable=lambda x: [e.value for e in x]), default=UserStatus.active, nullable=False)
    platform_role = Column(Enum(PlatformRole, values_callable=lambda x: [e.value for e in x]), default=PlatformRole.user, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    datasets = relationship("Dataset", back_populates="owner")
    uploads = relationship("Upload", back_populates="user")
    contributions = relationship("Contribution", back_populates="user")
    collection_tasks = relationship(
        "CollectionTask",
        back_populates="creator",
        foreign_keys="CollectionTask.created_by_id",
    )
    collection_assignments = relationship(
        "CollectionAssignment",
        back_populates="user",
        foreign_keys="CollectionAssignment.user_id",
    )
    collection_runs = relationship("CollectionRun", back_populates="user")
    memberships = relationship(
        "Membership",
        back_populates="user",
        foreign_keys="Membership.user_id",
    )
    created_organizations = relationship(
        "Organization",
        back_populates="creator",
        foreign_keys="Organization.created_by_user_id",
    )

    @property
    def has_password(self) -> bool:
        return bool(self.hashed_password)


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(CHAR(36), primary_key=True, default=new_uuid)
    name = Column(String(128), nullable=False)
    status = Column(
        Enum(OrganizationStatus, values_callable=lambda x: [e.value for e in x]),
        default=OrganizationStatus.active,
        nullable=False,
    )
    created_by_user_id = Column(CHAR(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    creator = relationship("User", back_populates="created_organizations", foreign_keys=[created_by_user_id])
    memberships = relationship("Membership", back_populates="organization")
    collection_tasks = relationship("CollectionTask", back_populates="organization")


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_membership_user"),
        UniqueConstraint("user_id", "org_id", name="uq_membership_user_org"),
        Index("ix_memberships_user_status", "user_id", "status"),
        Index("ix_memberships_org_status_role", "org_id", "status", "role_code"),
    )

    id = Column(CHAR(36), primary_key=True, default=new_uuid)
    user_id = Column(CHAR(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    org_id = Column(CHAR(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    role_code = Column(
        Enum(MembershipRole, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    status = Column(
        Enum(MembershipStatus, values_callable=lambda x: [e.value for e in x]),
        default=MembershipStatus.active,
        nullable=False,
    )
    invited_by_user_id = Column(CHAR(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    joined_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="memberships", foreign_keys=[user_id])
    organization = relationship("Organization", back_populates="memberships")
    inviter = relationship("User", foreign_keys=[invited_by_user_id])


# ─── Datasets ─────────────────────────────────────────────────────────────────

class Dataset(Base):
    __tablename__ = "datasets"

    id = Column(CHAR(36), primary_key=True, default=new_uuid)
    owner_id = Column(CHAR(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(256), nullable=False)
    description = Column(Text, nullable=True)
    tags = Column(String(512), nullable=True)          # 逗号分隔
    is_public = Column(Boolean, default=False)
    version = Column(Enum(DatasetVersion, values_callable=lambda x: [e.value for e in x]), default=DatasetVersion.unknown)
    oss_path = Column(String(1024), nullable=True)     # 正式区路径
    total_episodes = Column(Integer, nullable=True)
    total_frames = Column(Integer, nullable=True)
    size_bytes = Column(BigInteger, nullable=True)
    robot = Column(String(128), nullable=True)
    license = Column(String(128), default="Apache-2.0")
    has_preview = Column(Boolean, default=False)
    preview_path = Column(String(1024), nullable=True)  # previews/{dataset_id}/episode_0/
    thumbnail_path = Column(String(1024), nullable=True)  # previews/{dataset_id}/thumbnail.jpg
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    owner = relationship("User", back_populates="datasets")
    uploads = relationship("Upload", back_populates="dataset")
    contributions = relationship("Contribution", back_populates="dataset")


# ─── Uploads ──────────────────────────────────────────────────────────────────

class Upload(Base):
    __tablename__ = "uploads"

    id = Column(CHAR(36), primary_key=True, default=new_uuid)
    user_id = Column(CHAR(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    dataset_id = Column(CHAR(36), ForeignKey("datasets.id", ondelete="SET NULL"), nullable=True)
    oss_path = Column(String(1024), nullable=False)     # 临时区路径 user_uploads/{user_id}/{upload_id}/
    dataset_name = Column(String(256), nullable=True)
    status = Column(Enum(UploadStatus, values_callable=lambda x: [e.value for e in x]), default=UploadStatus.pending, nullable=False)
    error_message = Column(Text, nullable=True)
    detected_version = Column(Enum(DatasetVersion, values_callable=lambda x: [e.value for e in x]), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="uploads")
    dataset = relationship("Dataset", back_populates="uploads")


# ─── Contributions ────────────────────────────────────────────────────────────

class Contribution(Base):
    __tablename__ = "contributions"

    id = Column(CHAR(36), primary_key=True, default=new_uuid)
    user_id = Column(CHAR(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    dataset_id = Column(CHAR(36), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True)
    upload_id = Column(CHAR(36), ForeignKey("uploads.id", ondelete="SET NULL"), nullable=True)
    status = Column(Enum(UploadStatus, values_callable=lambda x: [e.value for e in x]), default=UploadStatus.pending, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    user = relationship("User", back_populates="contributions")
    dataset = relationship("Dataset", back_populates="contributions")


# ─── Collection Tasks ─────────────────────────────────────────────────────────

class CollectionTask(Base):
    __tablename__ = "collection_tasks"

    id = Column(CHAR(36), primary_key=True, default=new_uuid)
    org_id = Column(CHAR(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(128), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
    task_prompt = Column(Text, nullable=False)
    num_episodes = Column(Integer, default=10, nullable=False)
    fps = Column(Integer, default=30, nullable=False)
    episode_time_s = Column(Integer, default=300, nullable=False)
    reset_time_s = Column(Integer, default=10, nullable=False)
    use_cameras = Column(Boolean, default=True, nullable=False)
    dataset_prefix = Column(String(64), default="rec", nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_by_id = Column(CHAR(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    organization = relationship("Organization", back_populates="collection_tasks")
    creator = relationship("User", back_populates="collection_tasks", foreign_keys=[created_by_id])
    assignments = relationship("CollectionAssignment", back_populates="task")
    runs = relationship("CollectionRun", back_populates="task")


class CollectionAssignment(Base):
    __tablename__ = "collection_assignments"
    __table_args__ = (
        UniqueConstraint("phone", "task_id", "target_date", name="uq_collection_assignment_phone_task_date"),
        Index("ix_collection_assignments_date_phone", "target_date", "phone"),
    )

    id = Column(CHAR(36), primary_key=True, default=new_uuid)
    org_id = Column(CHAR(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    phone = Column(String(20), nullable=False, index=True)
    user_id = Column(CHAR(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    task_id = Column(CHAR(36), ForeignKey("collection_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    target_date = Column(Date, nullable=False, index=True)
    target_seconds = Column(Integer, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_by_id = Column(CHAR(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="collection_assignments", foreign_keys=[user_id])
    creator = relationship("User", foreign_keys=[created_by_id])
    task = relationship("CollectionTask", back_populates="assignments")
    runs = relationship("CollectionRun", back_populates="assignment")


class CollectionRun(Base):
    __tablename__ = "collection_runs"
    __table_args__ = (
        Index("ix_collection_runs_user_status", "user_id", "status"),
        Index("ix_collection_runs_assignment_status", "assignment_id", "status"),
    )

    id = Column(CHAR(36), primary_key=True, default=new_uuid)
    org_id = Column(CHAR(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(CHAR(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    assignment_id = Column(CHAR(36), ForeignKey("collection_assignments.id", ondelete="SET NULL"), nullable=True, index=True)
    task_id = Column(CHAR(36), ForeignKey("collection_tasks.id", ondelete="SET NULL"), nullable=True, index=True)
    dataset_name = Column(String(256), nullable=False, index=True)
    status = Column(Enum(CollectionRunStatus, values_callable=lambda x: [e.value for e in x]), default=CollectionRunStatus.active, nullable=False)
    started_at = Column(DateTime, server_default=func.now(), nullable=False)
    last_heartbeat_at = Column(DateTime, nullable=True)
    stopped_at = Column(DateTime, nullable=True)
    saved_episodes = Column(Integer, default=0, nullable=False)
    total_frames = Column(Integer, nullable=True)
    fps = Column(Integer, nullable=True)
    duration_seconds = Column(Integer, default=0, nullable=False)
    error_message = Column(Text, nullable=True)
    metadata_json = Column(Text, nullable=True)
    client_info_json = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="collection_runs")
    assignment = relationship("CollectionAssignment", back_populates="runs")
    task = relationship("CollectionTask", back_populates="runs")
    upload = relationship(
        "CollectionRunUpload",
        back_populates="run",
        uselist=False,
        cascade="all, delete-orphan",
    )


class CollectionRunUpload(Base):
    __tablename__ = "collection_run_uploads"
    __table_args__ = (
        UniqueConstraint("run_id", name="uq_collection_run_uploads_run_id"),
        Index("ix_collection_run_uploads_status", "status"),
        Index("ix_collection_run_uploads_upload_id", "upload_id"),
    )

    id = Column(CHAR(36), primary_key=True, default=new_uuid)
    run_id = Column(CHAR(36), ForeignKey("collection_runs.id", ondelete="CASCADE"), nullable=False)
    upload_id = Column(CHAR(36), nullable=True)
    oss_path = Column(String(1024), nullable=True)
    status = Column(
        Enum(CollectionRunUploadStatus, values_callable=lambda x: [e.value for e in x]),
        default=CollectionRunUploadStatus.pending,
        server_default=CollectionRunUploadStatus.pending.value,
        nullable=False,
    )
    total_files = Column(Integer, default=0, server_default="0", nullable=False)
    uploaded_files = Column(Integer, default=0, server_default="0", nullable=False)
    total_bytes = Column(BigInteger, default=0, server_default="0", nullable=False)
    uploaded_bytes = Column(BigInteger, default=0, server_default="0", nullable=False)
    last_uploaded_path = Column(String(1024), nullable=True)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    run = relationship("CollectionRun", back_populates="upload")


# ─── Credits ──────────────────────────────────────────────────────────────────

class CreditAccount(Base):
    __tablename__ = "credit_accounts"
    __table_args__ = (
        UniqueConstraint("user_id", "account_type", "org_scope_key", name="uq_credit_accounts_user_type_scope"),
        Index("ix_credit_accounts_org_user", "org_id", "user_id"),
    )

    id = Column(CHAR(36), primary_key=True, default=new_uuid)
    org_id = Column(CHAR(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True)
    user_id = Column(CHAR(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    account_type = Column(
        Enum(CreditAccountType, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    org_scope_key = Column(String(64), nullable=False)
    available_balance = Column(BigInteger, default=0, server_default="0", nullable=False)
    held_balance = Column(BigInteger, default=0, server_default="0", nullable=False)
    status = Column(
        Enum(CreditAccountStatus, values_callable=lambda x: [e.value for e in x]),
        default=CreditAccountStatus.active,
        server_default=CreditAccountStatus.active.value,
        nullable=False,
    )
    version = Column(Integer, default=0, server_default="0", nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class CreditLedgerEntry(Base):
    __tablename__ = "credit_ledger_entries"
    __table_args__ = (
        UniqueConstraint("account_id", "entry_type", "source_type", "source_id", name="uq_credit_ledger_source"),
        Index("ix_credit_ledger_account_created", "account_id", "created_at"),
        Index("ix_credit_ledger_source", "source_type", "source_id"),
    )

    id = Column(CHAR(36), primary_key=True, default=new_uuid)
    account_id = Column(CHAR(36), ForeignKey("credit_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    entry_type = Column(
        Enum(CreditLedgerEntryType, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    available_delta = Column(BigInteger, default=0, server_default="0", nullable=False)
    held_delta = Column(BigInteger, default=0, server_default="0", nullable=False)
    available_balance_after = Column(BigInteger, nullable=False)
    held_balance_after = Column(BigInteger, nullable=False)
    source_type = Column(String(64), nullable=False)
    source_id = Column(String(128), nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class RechargePackage(Base):
    __tablename__ = "recharge_packages"
    __table_args__ = (
        UniqueConstraint("account_type", "credit_amount", name="uq_recharge_packages_type_amount"),
        Index("ix_recharge_packages_type_active", "account_type", "is_active"),
    )

    id = Column(CHAR(36), primary_key=True, default=new_uuid)
    account_type = Column(
        Enum(CreditAccountType, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    name = Column(String(64), nullable=False)
    fiat_currency = Column(String(8), default="CNY", server_default="CNY", nullable=False)
    fiat_amount = Column(BigInteger, nullable=False)
    credit_amount = Column(BigInteger, nullable=False)
    is_active = Column(Boolean, default=True, server_default="1", nullable=False)
    sort_order = Column(Integer, default=0, server_default="0", nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class PaymentOrder(Base):
    __tablename__ = "payment_orders"
    __table_args__ = (
        UniqueConstraint("merchant_order_no", name="uq_payment_orders_merchant_order_no"),
        UniqueConstraint("provider", "provider_order_id", name="uq_payment_orders_provider_order"),
        Index("ix_payment_orders_account_status", "account_id", "status"),
    )

    id = Column(CHAR(36), primary_key=True, default=new_uuid)
    account_id = Column(CHAR(36), ForeignKey("credit_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    package_id = Column(CHAR(36), ForeignKey("recharge_packages.id", ondelete="SET NULL"), nullable=True)
    merchant_order_no = Column(String(64), nullable=False)
    provider = Column(Enum(PaymentProvider, values_callable=lambda x: [e.value for e in x]), nullable=False)
    provider_order_id = Column(String(128), nullable=True)
    fiat_currency = Column(String(8), default="CNY", server_default="CNY", nullable=False)
    fiat_amount = Column(BigInteger, nullable=False)
    credit_amount = Column(BigInteger, nullable=False)
    status = Column(
        Enum(PaymentOrderStatus, values_callable=lambda x: [e.value for e in x]),
        default=PaymentOrderStatus.created,
        server_default=PaymentOrderStatus.created.value,
        nullable=False,
    )
    ledger_entry_id = Column(CHAR(36), ForeignKey("credit_ledger_entries.id", ondelete="SET NULL"), nullable=True)
    qr_code_url = Column(String(2048), nullable=True)
    provider_payload_json = Column(Text, nullable=True)
    paid_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class UploadRewardGrant(Base):
    __tablename__ = "upload_reward_grants"
    __table_args__ = (
        UniqueConstraint("upload_id", name="uq_upload_reward_grants_upload_id"),
        Index("ix_upload_reward_grants_account_status", "account_id", "status"),
    )

    id = Column(CHAR(36), primary_key=True, default=new_uuid)
    account_id = Column(CHAR(36), ForeignKey("credit_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    upload_id = Column(CHAR(36), ForeignKey("uploads.id", ondelete="CASCADE"), nullable=False)
    dataset_id = Column(CHAR(36), ForeignKey("datasets.id", ondelete="SET NULL"), nullable=True)
    base_credit = Column(BigInteger, default=100, server_default="100", nullable=False)
    factor_json = Column(Text, nullable=True)
    final_credit = Column(BigInteger, default=100, server_default="100", nullable=False)
    status = Column(
        Enum(UploadRewardGrantStatus, values_callable=lambda x: [e.value for e in x]),
        default=UploadRewardGrantStatus.pending_review,
        server_default=UploadRewardGrantStatus.pending_review.value,
        nullable=False,
    )
    ledger_entry_id = Column(CHAR(36), ForeignKey("credit_ledger_entries.id", ondelete="SET NULL"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    rewarded_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class ResourceUsageRecord(Base):
    __tablename__ = "resource_usage_records"
    __table_args__ = (
        Index("ix_resource_usage_account_status", "account_id", "status"),
        Index("ix_resource_usage_resource", "resource_type", "resource_id"),
    )

    id = Column(CHAR(36), primary_key=True, default=new_uuid)
    account_id = Column(CHAR(36), ForeignKey("credit_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    org_id = Column(CHAR(36), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True)
    user_id = Column(CHAR(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    resource_type = Column(String(64), nullable=False)
    resource_id = Column(String(128), nullable=False)
    quantity = Column(BigInteger, default=1, server_default="1", nullable=False)
    unit = Column(String(32), nullable=False)
    credit_amount = Column(BigInteger, nullable=False)
    ledger_entry_id = Column(CHAR(36), ForeignKey("credit_ledger_entries.id", ondelete="SET NULL"), nullable=True)
    status = Column(
        Enum(ResourceUsageStatus, values_callable=lambda x: [e.value for e in x]),
        default=ResourceUsageStatus.pending,
        server_default=ResourceUsageStatus.pending.value,
        nullable=False,
    )
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class CreditPriceRule(Base):
    __tablename__ = "credit_price_rules"
    __table_args__ = (
        UniqueConstraint("resource_type", "resource_key", "unit", name="uq_credit_price_rules_resource"),
    )

    id = Column(CHAR(36), primary_key=True, default=new_uuid)
    resource_type = Column(String(64), nullable=False)
    resource_key = Column(String(128), nullable=False)
    unit = Column(String(32), nullable=False)
    credit_amount = Column(BigInteger, nullable=False)
    is_active = Column(Boolean, default=True, server_default="1", nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class DatasetPrice(Base):
    __tablename__ = "dataset_prices"
    __table_args__ = (
        UniqueConstraint("dataset_id", name="uq_dataset_prices_dataset_id"),
        Index("ix_dataset_prices_status", "status"),
    )

    id = Column(CHAR(36), primary_key=True, default=new_uuid)
    dataset_id = Column(CHAR(36), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False)
    credit_amount = Column(BigInteger, nullable=False)
    status = Column(
        Enum(DatasetPriceStatus, values_callable=lambda x: [e.value for e in x]),
        default=DatasetPriceStatus.active,
        server_default=DatasetPriceStatus.active.value,
        nullable=False,
    )
    created_by_user_id = Column(CHAR(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class DatasetPurchaseGrant(Base):
    __tablename__ = "dataset_purchase_grants"
    __table_args__ = (
        UniqueConstraint("dataset_id", "account_id", name="uq_dataset_purchase_grants_dataset_account"),
        Index("ix_dataset_purchase_grants_user", "user_id", "status"),
        Index("ix_dataset_purchase_grants_org", "org_id", "status"),
    )

    id = Column(CHAR(36), primary_key=True, default=new_uuid)
    dataset_id = Column(CHAR(36), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False)
    account_id = Column(CHAR(36), ForeignKey("credit_accounts.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(CHAR(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    org_id = Column(CHAR(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True)
    resource_usage_record_id = Column(CHAR(36), ForeignKey("resource_usage_records.id", ondelete="SET NULL"), nullable=True)
    source_type = Column(String(64), nullable=False)
    source_id = Column(String(128), nullable=False)
    status = Column(
        Enum(DatasetPurchaseGrantStatus, values_callable=lambda x: [e.value for e in x]),
        default=DatasetPurchaseGrantStatus.active,
        server_default=DatasetPurchaseGrantStatus.active.value,
        nullable=False,
    )
    created_at = Column(DateTime, server_default=func.now())


class RemoteTrainingJob(Base):
    __tablename__ = "remote_training_jobs"
    __table_args__ = (
        Index("ix_remote_training_jobs_account_status", "account_id", "status"),
        Index("ix_remote_training_jobs_user_task_status", "user_id", "task_name", "status"),
    )

    id = Column(CHAR(36), primary_key=True, default=new_uuid)
    account_id = Column(CHAR(36), ForeignKey("credit_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    usage_record_id = Column(CHAR(36), ForeignKey("resource_usage_records.id", ondelete="SET NULL"), nullable=True)
    org_id = Column(CHAR(36), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True)
    user_id = Column(CHAR(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    username = Column(String(128), nullable=False)
    task_name = Column(String(150), nullable=False)
    gpu_type = Column(String(128), nullable=False)
    gpu_count = Column(Integer, default=1, server_default="1", nullable=False)
    expected_seconds = Column(Integer, default=0, server_default="0", nullable=False)
    hold_credit = Column(BigInteger, default=0, server_default="0", nullable=False)
    settled_credit = Column(BigInteger, nullable=True)
    status = Column(
        Enum(RemoteTrainingJobStatus, values_callable=lambda x: [e.value for e in x]),
        default=RemoteTrainingJobStatus.held,
        server_default=RemoteTrainingJobStatus.held.value,
        nullable=False,
    )
    request_json = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
