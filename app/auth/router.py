import uuid
from typing import Optional

import redis as redis_lib
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth.utils import (
    SMS_SCENE_CHANGE_PHONE,
    SMS_SCENE_LOGIN,
    SMS_SCENE_RESET_PASSWORD,
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_captcha_image,
    generate_captcha_text,
    generate_sms_code,
    send_sms_code,
    verify_password,
    hash_password,
)
from app.config import settings
from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas import (
    CaptchaResponse,
    ChangePhoneRequest,
    LoginRequest,
    PasswordLoginRequest,
    RefreshRequest,
    ResetPasswordRequest,
    SendSmsRequest,
    TokenResponse,
    UserInfo,
)

router = APIRouter(prefix="/auth", tags=["auth"])

# Redis 客户端（用于存储验证码和短信验证码）
_redis: Optional[redis_lib.Redis] = None


def get_redis() -> redis_lib.Redis:
    global _redis
    if _redis is None:
        _redis = redis_lib.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


# ─── 图形验证码 ────────────────────────────────────────────────────────────────

@router.get("/captcha", response_model=CaptchaResponse)
def get_captcha():
    """生成图形验证码，返回 captcha_id 和 base64 图片"""
    captcha_id = str(uuid.uuid4())
    text = generate_captcha_text(4)
    image_b64 = generate_captcha_image(text)

    r = get_redis()
    r.setex(f"captcha:{captcha_id}", 300, text.upper())  # 5分钟有效

    return CaptchaResponse(captcha_id=captcha_id, image_base64=image_b64)


# ─── 发送短信验证码 ─────────────────────────────────────────────────────────────

@router.post("/send_sms")
def send_sms(body: SendSmsRequest, request: Request):
    """校验图形验证码后发送短信验证码"""
    r = get_redis()

    # 校验图形验证码
    key = f"captcha:{body.captcha_id}"
    stored = r.get(key)
    if not stored or stored.upper() != body.captcha_text.upper():
        raise HTTPException(status_code=400, detail="图形验证码错误或已过期")
    r.delete(key)

    # 短信限流：每手机号每小时最多 N 次
    rate_key = f"sms_rate:{body.phone}"
    count = r.incr(rate_key)
    if count == 1:
        r.expire(rate_key, 3600)
    if count > settings.RATE_LIMIT_SMS:
        raise HTTPException(status_code=429, detail="短信发送过于频繁，请稍后再试")

    # 生成并存储短信验证码
    code = generate_sms_code(6)
    expire = settings.SMS_CODE_EXPIRE_MINUTES * 60
    r.setex(f"sms:{body.scene}:{body.phone}", expire, code)

    # 将 scene 字符串映射到 utils 常量
    scene_map = {
        "login": SMS_SCENE_LOGIN,
        "change_phone": SMS_SCENE_CHANGE_PHONE,
        "reset_password": SMS_SCENE_RESET_PASSWORD,
    }
    ok = send_sms_code(body.phone, code, scene=scene_map.get(body.scene, SMS_SCENE_LOGIN))
    if not ok:
        raise HTTPException(status_code=500, detail="短信发送失败，请稍后重试")

    return {"message": "验证码已发送"}


# ─── 登录 / 注册 ──────────────────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    """手机号 + 短信验证码登录（若用户不存在则自动注册）"""
    r = get_redis()

    # 校验短信验证码
    code_key = f"sms:login:{body.phone}"
    stored_code = r.get(code_key)
    if not stored_code or stored_code != body.sms_code:
        raise HTTPException(status_code=400, detail="短信验证码错误或已过期")
    r.delete(code_key)

    # 查找或创建用户
    user = db.query(User).filter(User.phone == body.phone).first()
    if not user:
        user = User(phone=body.phone)
        db.add(user)
        db.commit()
        db.refresh(user)

    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已被禁用")

    access_token = create_access_token(str(user.id))
    refresh_token = create_refresh_token(str(user.id))

    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


# ─── 刷新 Token ───────────────────────────────────────────────────────────────

@router.post("/refresh", response_model=TokenResponse)
def refresh_token(body: RefreshRequest, db: Session = Depends(get_db)):
    payload = decode_token(body.refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="refresh_token 无效或已过期")

    user_id = payload.get("sub")
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="用户不存在")

    new_access = create_access_token(str(user.id))
    new_refresh = create_refresh_token(str(user.id))
    return TokenResponse(access_token=new_access, refresh_token=new_refresh)


# ─── 当前用户信息 ──────────────────────────────────────────────────────────────

@router.get("/me", response_model=UserInfo)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


# ─── 密码登录 ──────────────────────────────────────────────────────────────────

@router.post("/login/password", response_model=TokenResponse)
def login_with_password(body: PasswordLoginRequest, db: Session = Depends(get_db)):
    """手机号 + 密码登录（需提前通过短信设置密码）"""
    user = db.query(User).filter(User.phone == body.phone).first()
    if not user or not user.password_hash:
        raise HTTPException(status_code=400, detail="账号不存在或未设置密码")
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=400, detail="密码错误")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已被禁用")

    access_token = create_access_token(str(user.id))
    refresh_token = create_refresh_token(str(user.id))
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


# ─── 重置密码 ──────────────────────────────────────────────────────────────────

@router.post("/reset-password")
def reset_password(body: ResetPasswordRequest, db: Session = Depends(get_db)):
    """通过短信验证码重置密码"""
    r = get_redis()
    code_key = f"sms:reset_password:{body.phone}"
    stored_code = r.get(code_key)
    if not stored_code or stored_code != body.sms_code:
        raise HTTPException(status_code=400, detail="短信验证码错误或已过期")
    r.delete(code_key)

    user = db.query(User).filter(User.phone == body.phone).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    user.password_hash = hash_password(body.new_password)
    db.commit()
    return {"message": "密码已重置"}


# ─── 修改绑定手机号 ────────────────────────────────────────────────────────────

@router.post("/change-phone")
def change_phone(
    body: ChangePhoneRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """验证发到新手机号的短信验证码后，完成手机号变更"""
    r = get_redis()
    code_key = f"sms:change_phone:{body.new_phone}"
    stored_code = r.get(code_key)
    if not stored_code or stored_code != body.sms_code:
        raise HTTPException(status_code=400, detail="短信验证码错误或已过期")
    r.delete(code_key)

    # 检查新号码是否已被使用
    existing = db.query(User).filter(User.phone == body.new_phone).first()
    if existing and existing.id != current_user.id:
        raise HTTPException(status_code=400, detail="该手机号已被其他账号使用")

    current_user.phone = body.new_phone
    db.commit()
    return {"message": "手机号已变更"}
