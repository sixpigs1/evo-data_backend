import base64
import io
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from jose import JWTError, jwt
from PIL import Image, ImageDraw, ImageFilter

from app.config import settings


# ─── Password ─────────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


# ─── JWT ──────────────────────────────────────────────────────────────────────

def create_access_token(user_id: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode({"sub": user_id, "exp": exp, "type": "access"}, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    return jwt.encode({"sub": user_id, "exp": exp, "type": "refresh"}, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except JWTError:
        return None


# ─── Captcha ──────────────────────────────────────────────────────────────────

CAPTCHA_CHARS = string.ascii_uppercase.replace("O", "").replace("I", "") + string.digits.replace("0", "").replace("1", "")


def generate_captcha_image(text: str) -> str:
    """生成图形验证码，返回 base64 编码的 PNG 图片"""
    width, height = 120, 40
    img = Image.new("RGB", (width, height), color=(245, 245, 250))
    draw = ImageDraw.Draw(img)

    # 背景噪点
    for _ in range(200):
        x = random.randint(0, width)
        y = random.randint(0, height)
        draw.point((x, y), fill=(random.randint(160, 220), random.randint(160, 220), random.randint(160, 220)))

    # 干扰线
    for _ in range(4):
        x1, y1 = random.randint(0, width // 2), random.randint(0, height)
        x2, y2 = random.randint(width // 2, width), random.randint(0, height)
        draw.line([(x1, y1), (x2, y2)], fill=(random.randint(100, 180), random.randint(100, 180), random.randint(100, 180)), width=1)

    # 绘制字符
    char_w = width // len(text)
    for i, ch in enumerate(text):
        x = char_w * i + random.randint(2, 8)
        y = random.randint(4, 12)
        color = (random.randint(30, 120), random.randint(30, 120), random.randint(30, 120))
        draw.text((x, y), ch, fill=color)

    img = img.filter(ImageFilter.SMOOTH)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/png;base64,{b64}"


def generate_captcha_text(length: int = 4) -> str:
    return "".join(random.choices(CAPTCHA_CHARS, k=length))


# ─── SMS ──────────────────────────────────────────────────────────────────────

# 场景 → 模板 Code 的映射键，与 config.py 中字段对应
SMS_SCENE_LOGIN = "login"            # 登录/注册  → SMS_TEMPLATE_LOGIN
SMS_SCENE_CHANGE_PHONE = "change_phone"  # 修改绑定手机号 → SMS_TEMPLATE_CHANGE_PHONE
SMS_SCENE_RESET_PASSWORD = "reset_password"  # 重置密码 → SMS_TEMPLATE_RESET_PASSWORD


def _get_template_code(scene: str) -> str:
    mapping = {
        SMS_SCENE_LOGIN: settings.SMS_TEMPLATE_LOGIN,
        SMS_SCENE_CHANGE_PHONE: settings.SMS_TEMPLATE_CHANGE_PHONE,
        SMS_SCENE_RESET_PASSWORD: settings.SMS_TEMPLATE_RESET_PASSWORD,
    }
    return mapping.get(scene, settings.SMS_TEMPLATE_LOGIN)


def generate_sms_code(length: int = 6) -> str:
    return "".join(random.choices(string.digits, k=length))


def send_sms_code(phone: str, scene: str = SMS_SCENE_LOGIN) -> Optional[str]:
    """
    通过阿里云号码认证服务（Dypnsapi）发送短信验证码。
    验证码由阿里云生成，通过 ReturnVerifyCode=True 返回给后端存入 Redis。
    scene 决定使用哪个模板：
      - SMS_SCENE_LOGIN          → 模板 100001（登录/注册）
      - SMS_SCENE_CHANGE_PHONE   → 模板 100002（修改手机号）
      - SMS_SCENE_RESET_PASSWORD → 模板 100003（重置密码）
    成功返回验证码字符串，失败返回 None。
    """
    template_code = _get_template_code(scene)
    expire_min = settings.SMS_CODE_EXPIRE_MINUTES

    if settings.SMS_DEV_MODE:
        code = generate_sms_code(6)
        print(f"[DEV SMS] 手机号: {phone}  验证码: {code}  场景: {scene}  模板: {template_code}")
        return code

    try:
        import json
        from alibabacloud_dypnsapi20170525.client import Client
        from alibabacloud_dypnsapi20170525 import models as dypns_models
        from alibabacloud_tea_openapi import models as open_api_models

        config = open_api_models.Config(
            access_key_id=settings.SMS_ACCESS_KEY_ID,
            access_key_secret=settings.SMS_ACCESS_KEY_SECRET,
        )
        config.endpoint = "dypnsapi.aliyuncs.com"
        client = Client(config)

        template_param = json.dumps({"code": "##code##", "min": str(expire_min)}, ensure_ascii=False)
        req = dypns_models.SendSmsVerifyCodeRequest(
            phone_number=phone,
            sign_name=settings.SMS_SIGN_NAME,
            template_code=template_code,
            template_param=template_param,
            code_type=1,                    # 纯数字
            code_length=6,
            valid_time=expire_min * 60,     # 转换为秒
            return_verify_code=True,        # 返回实际验证码
        )
        resp = client.send_sms_verify_code(req)
        if resp.body.code == "OK" and resp.body.model and resp.body.model.verify_code:
            return resp.body.model.verify_code
        else:
            print(f"[SMS ERROR] code={resp.body.code} message={resp.body.message}")
            return None
    except Exception as e:
        print(f"[SMS ERROR] {e}")
        return None
