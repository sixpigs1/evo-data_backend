"""
STS 签发接口
用户获取临时凭证后，直接从浏览器上传文件到 OSS
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException

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
