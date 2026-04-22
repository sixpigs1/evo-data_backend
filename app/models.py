import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, Enum, ForeignKey,
    Integer, String, Text, func, CHAR,
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


# ─── Users ────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id = Column(CHAR(36), primary_key=True, default=new_uuid)
    phone = Column(String(20), unique=True, nullable=False, index=True)
    hashed_password = Column(String(128), nullable=True)  # 预留密码字段
    nickname = Column(String(64), nullable=True)
    level = Column(Enum(UserLevel), default=UserLevel.normal, nullable=False)
    rank = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    is_active = Column(Boolean, default=True)

    datasets = relationship("Dataset", back_populates="owner")
    uploads = relationship("Upload", back_populates="user")
    contributions = relationship("Contribution", back_populates="user")


# ─── Datasets ─────────────────────────────────────────────────────────────────

class Dataset(Base):
    __tablename__ = "datasets"

    id = Column(CHAR(36), primary_key=True, default=new_uuid)
    owner_id = Column(CHAR(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(256), nullable=False)
    description = Column(Text, nullable=True)
    tags = Column(String(512), nullable=True)          # 逗号分隔
    is_public = Column(Boolean, default=False)
    version = Column(Enum(DatasetVersion), default=DatasetVersion.unknown)
    oss_path = Column(String(1024), nullable=True)     # 正式区路径
    total_episodes = Column(Integer, nullable=True)
    total_frames = Column(Integer, nullable=True)
    size_bytes = Column(BigInteger, nullable=True)
    robot = Column(String(128), nullable=True)
    license = Column(String(128), default="Apache-2.0")
    has_preview = Column(Boolean, default=False)
    preview_path = Column(String(1024), nullable=True)  # previews/{dataset_id}/episode_0/
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
    status = Column(Enum(UploadStatus), default=UploadStatus.pending, nullable=False)
    error_message = Column(Text, nullable=True)
    detected_version = Column(Enum(DatasetVersion), nullable=True)
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
    status = Column(Enum(UploadStatus), default=UploadStatus.pending, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    user = relationship("User", back_populates="contributions")
    dataset = relationship("Dataset", back_populates="contributions")
