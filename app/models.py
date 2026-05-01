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


class UserLevel(str, enum.Enum):
    normal = "normal"
    contributor = "contributor"
    admin = "admin"


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


# ─── Users ────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id = Column(CHAR(36), primary_key=True, default=new_uuid)
    phone = Column(String(20), unique=True, nullable=False, index=True)
    hashed_password = Column(String(128), nullable=True)  # 预留密码字段
    nickname = Column(String(64), nullable=True)
    level = Column(Enum(UserLevel, values_callable=lambda x: [e.value for e in x]), default=UserLevel.normal, nullable=False)
    rank = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    is_active = Column(Boolean, default=True)

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
    name = Column(String(128), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
    task_prompt = Column(Text, nullable=False)
    num_episodes = Column(Integer, default=10, nullable=False)
    fps = Column(Integer, default=30, nullable=False)
    episode_time_s = Column(Integer, default=300, nullable=False)
    reset_time_s = Column(Integer, default=10, nullable=False)
    use_cameras = Column(Boolean, default=True, nullable=False)
    arms = Column(String(128), default="", nullable=False)
    dataset_prefix = Column(String(64), default="rec", nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_by_id = Column(CHAR(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

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
