"""
数据集 API 路由
"""
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import get_current_user, get_optional_user
from app.models import Contribution, Dataset, Upload, UploadStatus, User
from app.schemas import (
    DatasetDetail,
    DatasetListItem,
    DatasetUpdateRequest,
    DownloadUrlRequest,
    DownloadUrlResponse,
    UploadCompleteRequest,
    UploadStatusResponse,
)
from app.worker.tasks import validate_dataset_task

router = APIRouter(prefix="/datasets", tags=["datasets"])


def _mask_phone(phone: str) -> str:
    """脱敏手机号，保留前3后4位"""
    if len(phone) == 11:
        return phone[:3] + "****" + phone[7:]
    return phone[:2] + "***"


def _has_valid_contribution(user: User, db: Session) -> bool:
    """检查用户是否有至少一个通过校验的贡献"""
    return db.query(Contribution).filter(
        Contribution.user_id == user.id,
        Contribution.status == UploadStatus.passed,
    ).count() > 0


# ─── 列出公开数据集 ────────────────────────────────────────────────────────────

@router.get("", response_model=List[DatasetListItem])
def list_datasets(
    search: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    q = db.query(Dataset).filter(Dataset.is_public == True)
    if search:
        q = q.filter(
            Dataset.name.ilike(f"%{search}%") | Dataset.description.ilike(f"%{search}%")
        )
    if tag:
        q = q.filter(Dataset.tags.ilike(f"%{tag}%"))

    datasets = q.order_by(Dataset.created_at.desc()).offset(skip).limit(limit).all()

    result = []
    for d in datasets:
        item = DatasetListItem.model_validate(d)
        item.owner_phone = _mask_phone(d.owner.phone) if d.owner else None
        result.append(item)
    return result


# ─── 获取数据集详情 ───────────────────────────────────────────────────────────

@router.get("/{dataset_id}", response_model=DatasetDetail)
def get_dataset(
    dataset_id: str,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    d = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="数据集不存在")
    if not d.is_public and (not current_user or str(current_user.id) != str(d.owner_id)):
        raise HTTPException(status_code=403, detail="无权访问此数据集")

    detail = DatasetDetail.model_validate(d)
    detail.owner_phone = _mask_phone(d.owner.phone) if d.owner else None

    # 仅登录用户且有贡献时才返回 oss_path（用于下载签名）
    if not current_user or not _has_valid_contribution(current_user, db):
        detail.oss_path = None

    return detail


# ─── 完成上传 ─────────────────────────────────────────────────────────────────

@router.post("/upload/complete", response_model=UploadStatusResponse)
def complete_upload(
    body: UploadCompleteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """用户上传完成后通知后端，触发校验任务"""
    # 验证 oss_path 属于当前用户
    expected_prefix = f"user_uploads/{current_user.id}/"
    if not body.oss_path.startswith(expected_prefix):
        raise HTTPException(status_code=403, detail="无权访问此上传路径")

    upload = Upload(
        id=uuid.UUID(body.upload_id) if body.upload_id else uuid.uuid4(),
        user_id=current_user.id,
        oss_path=body.oss_path,
        dataset_name=body.dataset_name,
        status=UploadStatus.pending,
    )
    db.add(upload)
    db.commit()
    db.refresh(upload)

    # 合并两类 tag
    combined_tags = ",".join(filter(None, [body.robot_type_tags, body.task_type_tags])) or None

    # 触发异步校验任务，传入描述和 tags
    validate_dataset_task.delay(str(upload.id), body.description, combined_tags)

    return UploadStatusResponse(
        upload_id=str(upload.id),
        status=upload.status.value,
    )


# ─── 查询上传状态 ─────────────────────────────────────────────────────────────

@router.get("/upload/{upload_id}/status", response_model=UploadStatusResponse)
def get_upload_status(
    upload_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    upload = db.query(Upload).filter(
        Upload.id == upload_id,
        Upload.user_id == current_user.id,
    ).first()
    if not upload:
        raise HTTPException(status_code=404, detail="上传记录不存在")

    return UploadStatusResponse(
        upload_id=str(upload.id),
        status=upload.status.value,
        error_message=upload.error_message,
        dataset_id=str(upload.dataset_id) if upload.dataset_id else None,
        detected_version=upload.detected_version.value if upload.detected_version else None,
    )


# ─── 获取下载签名 URL ─────────────────────────────────────────────────────────

@router.get("/{dataset_id}/download-url", response_model=DownloadUrlResponse)
def get_download_url(
    dataset_id: str,
    file: str = Query(..., description="相对于数据集根目录的文件路径"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    生成 OSS 签名下载 URL。
    权限要求：用户必须有至少一个通过校验的贡献。
    """
    if not _has_valid_contribution(current_user, db):
        raise HTTPException(
            status_code=403,
            detail="需要先贡献至少一个有效数据集才能下载",
        )

    d = db.query(Dataset).filter(Dataset.id == dataset_id, Dataset.is_public == True).first()
    if not d:
        raise HTTPException(status_code=404, detail="数据集不存在或未公开")

    if not d.oss_path:
        raise HTTPException(status_code=404, detail="数据集文件不可用")

    # 构造完整 OSS 键
    full_key = d.oss_path.rstrip("/") + "/" + file.lstrip("/")

    try:
        import oss2
        auth = oss2.Auth(settings.OSS_ACCESS_KEY_ID, settings.OSS_ACCESS_KEY_SECRET)
        bucket = oss2.Bucket(auth, settings.OSS_ENDPOINT, settings.OSS_BUCKET_NAME)

        expires = 3600  # 1小时有效
        url = bucket.sign_url("GET", full_key, expires)
        return DownloadUrlResponse(url=url, expires_in=expires)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成下载链接失败: {str(e)}")


# ─── 我的数据集 ───────────────────────────────────────────────────────────────

@router.get("/my/datasets", response_model=List[DatasetListItem])
def my_datasets(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    datasets = db.query(Dataset).filter(Dataset.owner_id == current_user.id).all()
    result = []
    for d in datasets:
        item = DatasetListItem.model_validate(d)
        item.owner_phone = _mask_phone(d.owner.phone) if d.owner else None
        result.append(item)
    return result


# ─── 更新数据集元信息 ─────────────────────────────────────────────────────────

@router.patch("/{dataset_id}", response_model=DatasetDetail)
def update_dataset(
    dataset_id: str,
    body: DatasetUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    d = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="数据集不存在")
    if str(d.owner_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="无权修改此数据集")

    if body.description is not None:
        d.description = body.description
    if body.tags is not None:
        d.tags = body.tags
    if body.is_public is not None:
        d.is_public = body.is_public
    if body.robot is not None:
        d.robot = body.robot
    if body.license is not None:
        d.license = body.license

    db.commit()
    db.refresh(d)
    return DatasetDetail.model_validate(d)
