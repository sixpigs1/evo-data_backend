"""
STS 签发接口
用户获取临时凭证后，直接从浏览器上传文件到 OSS
"""
import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.deps import get_current_user
from app.models import User
from app.schemas import STSCredentials

router = APIRouter(prefix="/sts", tags=["sts"])


@router.get("", response_model=STSCredentials)
def get_sts_credentials(current_user: User = Depends(get_current_user)):
    """获取 STS 临时凭证，用于前端直传 OSS"""
    upload_id = str(uuid.uuid4())
    upload_dir = f"user_uploads/{current_user.id}/{upload_id}/"

    # 构造最小权限策略：只允许写入当前用户自己的目录
    policy = {
        "Version": "1",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["oss:PutObject"],
                "Resource": [
                    f"acs:oss:*:*:{settings.OSS_BUCKET_NAME}/{upload_dir}*"
                ],
            }
        ],
    }

    try:
        import json
        from alibabacloud_sts20150401.client import Client
        from alibabacloud_tea_openapi import models as open_api_models
        from alibabacloud_sts20150401 import models as sts_models

        config = open_api_models.Config(
            access_key_id=settings.OSS_ACCESS_KEY_ID,
            access_key_secret=settings.OSS_ACCESS_KEY_SECRET,
            endpoint="sts.aliyuncs.com",
        )
        client = Client(config)
        req = sts_models.AssumeRoleRequest(
            role_arn=settings.STS_ROLE_ARN,
            role_session_name=f"{settings.STS_SESSION_NAME}-{current_user.id}",
            duration_seconds=settings.STS_DURATION_SECONDS,
            policy=json.dumps(policy),
        )
        resp = client.assume_role(req)
        creds = resp.body.credentials

        return STSCredentials(
            access_key_id=creds.access_key_id,
            access_key_secret=creds.access_key_secret,
            security_token=creds.security_token,
            expiration=creds.expiration,
            upload_dir=upload_dir,
            upload_id=upload_id,
            bucket=settings.OSS_BUCKET_NAME,
            endpoint=settings.OSS_ENDPOINT,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"STS 签发失败: {str(e)}")


class PresignRequest(BaseModel):
    upload_dir: str          # 来自 STS 响应的 upload_dir，如 user_uploads/{uid}/{upload_id}/
    relative_paths: List[str]  # 文件相对路径列表，如 ["data/ep0.parquet", ...]


class PresignResponse(BaseModel):
    urls: dict  # { relative_path: presigned_put_url }


@router.post("/presign", response_model=PresignResponse)
def get_presign_urls(
    body: PresignRequest,
    current_user: User = Depends(get_current_user),
):
    """
    为每个文件生成预签名 PUT URL，前端直接 PUT 无需任何 Authorization 头。
    预签名 URL 有效期 1 小时，且每个 URL 仅能写入指定的 object key。
    """
    # 安全校验：upload_dir 必须属于当前用户
    expected_prefix = f"user_uploads/{current_user.id}/"
    if not body.upload_dir.startswith(expected_prefix):
        raise HTTPException(status_code=403, detail="upload_dir 不属于当前用户")

    try:
        import oss2

        # 使用公网 endpoint（前端浏览器无法访问内网）
        public_endpoint = settings.OSS_ENDPOINT.replace(
            "-internal.aliyuncs.com", ".aliyuncs.com"
        )
        auth = oss2.Auth(settings.OSS_ACCESS_KEY_ID, settings.OSS_ACCESS_KEY_SECRET)
        bucket = oss2.Bucket(auth, public_endpoint, settings.OSS_BUCKET_NAME)

        urls = {}
        for rel_path in body.relative_paths:
            # 拼接完整 object key，并再次校验路径安全
            key = body.upload_dir + rel_path
            if not key.startswith(expected_prefix):
                raise HTTPException(status_code=400, detail=f"非法路径: {rel_path}")
            # 生成预签名 PUT URL，有效期 3600 秒
            # 签名时指定 Content-Type，前端上传时也必须发送相同的 Content-Type
            urls[rel_path] = bucket.sign_url(
                "PUT", key, 3600,
                headers={"Content-Type": "application/octet-stream"}
            )

        return PresignResponse(urls=urls)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"预签名 URL 生成失败: {str(e)}")
