from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

import json

from pydantic import BaseModel, field_validator


# ─── Tag 配置（后端权威定义，与前端 tagConfig.ts 保持同步）──────────────────────
#
# 扩展说明：
#   - 增加新分类：在 TAG_CATEGORIES 末尾追加一个 dict
#   - 增加某分类的选项：在对应 options 列表末尾追加
#   - key 一旦确定不可修改（已写入数据库的 JSON key）
#
TAG_CATEGORIES: List[Dict[str, Any]] = [
    {
        "key": "robot_type",
        "label": "本体类型",
        "labelEn": "Robot Type",
        "type": "single",
        "required": False,
        "options": ["SO100", "SO101", "Piper", "UR5", "Franka-Panda", "xArm6"],
    },
    {
        "key": "task_type",
        "label": "任务类型",
        "labelEn": "Task Type",
        "type": "single",
        "required": False,
        # 存储/传输使用英文 key，前端负责翻译展示
        "options": [
            "industrial_assembly",
            "retail_display",
            "hospitality",
            "food_service",
            "home_daily",
            "medical_assist",
            "research",
            "education",
            "simple_test",
        ],
    },
    {
        "key": "other",
        "label": "其他标签",
        "labelEn": "Other Tags",
        "type": "multi",
        "required": False,
        "options": ["dual_arm", "flexible_objects", "mobile_base"],
    },
    {
        "key": "data_type",
        "label": "数据类型",
        "labelEn": "Data Type",
        "type": "single",
        "required": False,
        "options": ["standard_operation", "evo_rl"],
    },
    {
        "key": "data_format",
        "label": "数据格式",
        "labelEn": "Data Format",
        "type": "single",
        "required": False,
        "options": ["LeRobot 2.1", "LeRobot 3.0"],
    },
]

# 有效选项集合，用于快速校验
_VALID_OPTIONS: Dict[str, set] = {
    c["key"]: set(c["options"]) for c in TAG_CATEGORIES
}


def validate_tags_json(tags_str: Optional[str]) -> Optional[str]:
    """校验并清理 tags JSON 字符串，返回规范化后的字符串"""
    if not tags_str:
        return None
    try:
        data = json.loads(tags_str)
    except (json.JSONDecodeError, TypeError):
        raise ValueError("tags 必须是合法的 JSON 字符串")
    if not isinstance(data, dict):
        raise ValueError("tags JSON 必须是对象")
    clean: Dict[str, Any] = {}
    for cat in TAG_CATEGORIES:
        key = cat["key"]
        if key not in data:
            continue
        val = data[key]
        valid_set = _VALID_OPTIONS[key]
        if cat["type"] == "single":
            if not isinstance(val, str):
                raise ValueError(f"tags.{key} 必须是字符串")
            if val not in valid_set:
                raise ValueError(f"tags.{key} 的值 '{val}' 不在允许范围内")
            clean[key] = val
        else:  # multi
            if not isinstance(val, list):
                raise ValueError(f"tags.{key} 必须是数组")
            for v in val:
                if v not in valid_set:
                    raise ValueError(f"tags.{key} 的值 '{v}' 不在允许范围内")
            if val:
                clean[key] = val
    return json.dumps(clean, ensure_ascii=False) if clean else None


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
    captcha_id: str
    captcha_text: str

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


class NicknameUpdateRequest(BaseModel):
    nickname: Optional[str] = None

    @field_validator("nickname")
    @classmethod
    def validate_nickname(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if len(v) > 20:
                raise ValueError("昵称最多20个字符")
            return v or None
        return v


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
    description: Optional[str] = None
    tags: Optional[str] = None  # JSON 序列化后的 TagsData 字符串
    is_public: bool = False  # 上传时即可设置是否公开，默认不公开

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: Optional[str]) -> Optional[str]:
        return validate_tags_json(v)


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
    tags: Optional[str] = None          # JSON 序列化后的 TagsData 字符串
    is_public: Optional[bool] = None
    license: Optional[str] = None

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: Optional[str]) -> Optional[str]:
        return validate_tags_json(v)


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
