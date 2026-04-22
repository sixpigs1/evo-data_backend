from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, field_validator


# ─── Auth ─────────────────────────────────────────────────────────────────────

class CaptchaResponse(BaseModel):
    captcha_id: str
    image_base64: str  # data:image/png;base64,...


# 短信场景枚举（与 auth/utils.py 中常量对应）
SmsScene = Literal["login", "change_phone", "reset_password"]


class SendSmsRequest(BaseModel):
    phone: str
    captcha_id: str
    captcha_text: str
    scene: SmsScene = "login"  # 默认登录/注册场景

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        v = v.strip()
        if not v.isdigit() or len(v) != 11 or not v.startswith("1"):
            raise ValueError("手机号格式不正确")
        return v


# ── 登录方式一：短信验证码登录/注册 ─────────────────────────────────────────────

class SmsLoginRequest(BaseModel):
    phone: str
    sms_code: str

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        v = v.strip()
        if not v.isdigit() or len(v) != 11 or not v.startswith("1"):
            raise ValueError("手机号格式不正确")
        return v


# ── 登录方式二：密码登录 ─────────────────────────────────────────────────────────

class PasswordLoginRequest(BaseModel):
    phone: str
    password: str

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        v = v.strip()
        if not v.isdigit() or len(v) != 11 or not v.startswith("1"):
            raise ValueError("手机号格式不正确")
        return v


# 兼容旧接口的别名（前端沿用 LoginRequest）
LoginRequest = SmsLoginRequest


# ── 重置密码 ──────────────────────────────────────────────────────────────────

class ResetPasswordRequest(BaseModel):
    phone: str
    sms_code: str
    new_password: str

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        v = v.strip()
        if not v.isdigit() or len(v) != 11 or not v.startswith("1"):
            raise ValueError("手机号格式不正确")
        return v

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("密码长度不得少于8位")
        return v


# ── 修改绑定手机号 ──────────────────────────────────────────────────────────────

class ChangePhoneRequest(BaseModel):
    new_phone: str
    sms_code: str          # 发到新手机号的验证码（场景 change_phone）

    @field_validator("new_phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        v = v.strip()
        if not v.isdigit() or len(v) != 11 or not v.startswith("1"):
            raise ValueError("手机号格式不正确")
        return v


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class UserInfo(BaseModel):
    id: str
    phone: str
    nickname: Optional[str]
    level: str
    rank: int
    has_password: bool = False   # 是否已设置密码（前端判断是否显示"设置密码"入口）
    created_at: datetime

    model_config = {"from_attributes": True}


# ─── STS ──────────────────────────────────────────────────────────────────────

class STSCredentials(BaseModel):
    access_key_id: str
    access_key_secret: str
    security_token: str
    expiration: str
    upload_dir: str          # user_uploads/{user_id}/{upload_id}/
    upload_id: str
    bucket: str
    endpoint: str


# ─── Upload ───────────────────────────────────────────────────────────────────

class UploadCompleteRequest(BaseModel):
    upload_id: str
    dataset_name: str
    oss_path: str            # user_uploads/{user_id}/{upload_id}/


class UploadStatusResponse(BaseModel):
    upload_id: str
    status: str
    error_message: Optional[str] = None
    dataset_id: Optional[str] = None
    detected_version: Optional[str] = None

    model_config = {"from_attributes": True}


# ─── Dataset ──────────────────────────────────────────────────────────────────

class DatasetListItem(BaseModel):
    id: str
    name: str
    description: Optional[str]
    tags: Optional[str]
    is_public: bool
    version: str
    total_episodes: Optional[int]
    total_frames: Optional[int]
    size_bytes: Optional[int]
    robot: Optional[str]
    license: str
    has_preview: bool
    created_at: datetime
    owner_phone: Optional[str] = None  # 脱敏后手机号

    model_config = {"from_attributes": True}


class DatasetDetail(DatasetListItem):
    preview_path: Optional[str] = None
    oss_path: Optional[str] = None

    model_config = {"from_attributes": True}


class DatasetUpdateRequest(BaseModel):
    description: Optional[str] = None
    tags: Optional[str] = None
    is_public: Optional[bool] = None
    robot: Optional[str] = None
    license: Optional[str] = None


class DownloadUrlRequest(BaseModel):
    file: str   # 相对于数据集根目录的文件路径


class DownloadUrlResponse(BaseModel):
    url: str
    expires_in: int  # 秒


# ─── Preview ──────────────────────────────────────────────────────────────────

class PreviewMeta(BaseModel):
    dataset_id: str
    episode_index: int
    fps: float
    total_frames: int
    task_instruction: Optional[str] = None
    features: dict
    frames_base_url: str   # OSS 公开访问 URL 前缀
    trajectory_url: str    # trajectory.json URL
