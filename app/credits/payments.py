from __future__ import annotations

import base64
import json
import secrets
from datetime import datetime
from pathlib import Path

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import settings
from app.models import PaymentOrder, PaymentProvider


def create_payment_qr(order: PaymentOrder) -> tuple[str, dict]:
    provider = PaymentProvider(order.provider)
    if settings.PAYMENT_MOCK_MODE:
        qr = f"mock://{provider.value}/pay/{order.merchant_order_no}"
        return qr, {"mode": "mock", "qr_code_url": qr}
    if provider == PaymentProvider.wechat:
        return _create_wechat_native_order(order)
    if provider == PaymentProvider.alipay:
        return _create_alipay_precreate_order(order)
    raise ValueError(f"Unsupported payment provider: {provider.value}")


def parse_wechat_notification(headers: dict[str, str], body: dict) -> dict:
    if settings.PAYMENT_MOCK_MODE:
        return dict(body)
    _verify_wechat_signature(headers, json.dumps(body, ensure_ascii=False, separators=(",", ":")))
    resource = body.get("resource") or {}
    ciphertext = resource["ciphertext"]
    nonce = resource["nonce"]
    associated_data = resource.get("associated_data") or ""
    key = settings.WECHAT_PAY_API_V3_KEY.encode("utf-8")
    plaintext = AESGCM(key).decrypt(
        nonce.encode("utf-8"),
        base64.b64decode(ciphertext),
        associated_data.encode("utf-8"),
    )
    return json.loads(plaintext.decode("utf-8"))


def verify_alipay_notification(form: dict[str, str]) -> dict[str, str]:
    if settings.PAYMENT_MOCK_MODE:
        return dict(form)
    sign = form.get("sign") or ""
    sign_type = form.get("sign_type") or "RSA2"
    payload = {
        key: value
        for key, value in form.items()
        if key not in {"sign", "sign_type"} and value != ""
    }
    message = "&".join(f"{key}={payload[key]}" for key in sorted(payload))
    public_key = _load_public_key(settings.ALIPAY_PUBLIC_KEY, settings.ALIPAY_PUBLIC_KEY_PATH)
    algorithm = hashes.SHA256() if sign_type == "RSA2" else hashes.SHA1()
    public_key.verify(base64.b64decode(sign), message.encode("utf-8"), padding.PKCS1v15(), algorithm)
    return dict(form)


def _create_wechat_native_order(order: PaymentOrder) -> tuple[str, dict]:
    notify_url = _notify_url("/payments/wechat/notify")
    path = "/v3/pay/transactions/native"
    body = {
        "appid": settings.WECHAT_PAY_APPID,
        "mchid": settings.WECHAT_PAY_MCHID,
        "description": f"EvoData {order.credit_amount} credits",
        "out_trade_no": order.merchant_order_no,
        "notify_url": notify_url,
        "amount": {
            "total": int(order.fiat_amount),
            "currency": order.fiat_currency,
        },
    }
    body_text = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    headers = {
        "Authorization": _wechat_authorization("POST", path, body_text),
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=15.0, trust_env=False) as client:
        response = client.post(f"https://api.mch.weixin.qq.com{path}", content=body_text, headers=headers)
    response.raise_for_status()
    payload = response.json()
    qr = str(payload["code_url"])
    return qr, payload


def _create_alipay_precreate_order(order: PaymentOrder) -> tuple[str, dict]:
    biz_content = {
        "out_trade_no": order.merchant_order_no,
        "total_amount": f"{order.fiat_amount / 100:.2f}",
        "subject": f"EvoData {order.credit_amount} credits",
    }
    params = {
        "app_id": settings.ALIPAY_APP_ID,
        "method": "alipay.trade.precreate",
        "charset": "utf-8",
        "sign_type": "RSA2",
        "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "version": "1.0",
        "notify_url": _notify_url("/payments/alipay/notify"),
        "biz_content": json.dumps(biz_content, ensure_ascii=False, separators=(",", ":")),
    }
    params["sign"] = _alipay_sign(params)
    with httpx.Client(timeout=15.0, trust_env=False) as client:
        response = client.post(settings.ALIPAY_GATEWAY, data=params)
    response.raise_for_status()
    payload = response.json()
    body = payload.get("alipay_trade_precreate_response") or {}
    if body.get("code") != "10000":
        raise RuntimeError(body.get("sub_msg") or body.get("msg") or "支付宝预下单失败")
    qr = str(body["qr_code"])
    return qr, payload


def _wechat_authorization(method: str, path: str, body: str) -> str:
    timestamp = str(int(datetime.utcnow().timestamp()))
    nonce = secrets.token_hex(16)
    message = f"{method}\n{path}\n{timestamp}\n{nonce}\n{body}\n"
    private_key = _load_private_key(
        settings.WECHAT_PAY_MERCHANT_PRIVATE_KEY,
        settings.WECHAT_PAY_MERCHANT_PRIVATE_KEY_PATH,
    )
    signature = base64.b64encode(
        private_key.sign(message.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
    ).decode("utf-8")
    return (
        'WECHATPAY2-SHA256-RSA2048 '
        f'mchid="{settings.WECHAT_PAY_MCHID}",'
        f'nonce_str="{nonce}",'
        f'signature="{signature}",'
        f'timestamp="{timestamp}",'
        f'serial_no="{settings.WECHAT_PAY_MERCHANT_SERIAL_NO}"'
    )


def _verify_wechat_signature(headers: dict[str, str], body: str) -> None:
    signature = headers.get("wechatpay-signature") or headers.get("Wechatpay-Signature") or ""
    timestamp = headers.get("wechatpay-timestamp") or headers.get("Wechatpay-Timestamp") or ""
    nonce = headers.get("wechatpay-nonce") or headers.get("Wechatpay-Nonce") or ""
    message = f"{timestamp}\n{nonce}\n{body}\n"
    public_key = _load_public_key(settings.WECHAT_PAY_PLATFORM_CERT, settings.WECHAT_PAY_PLATFORM_CERT_PATH)
    public_key.verify(base64.b64decode(signature), message.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())


def _alipay_sign(params: dict[str, str]) -> str:
    unsigned = "&".join(f"{key}={params[key]}" for key in sorted(params) if params[key] != "")
    private_key = _load_private_key(settings.ALIPAY_PRIVATE_KEY, settings.ALIPAY_PRIVATE_KEY_PATH)
    signature = private_key.sign(unsigned.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
    return base64.b64encode(signature).decode("utf-8")


def _notify_url(path: str) -> str:
    base = settings.PAYMENT_NOTIFY_BASE_URL.rstrip("/")
    if not base:
        raise RuntimeError("PAYMENT_NOTIFY_BASE_URL is required when PAYMENT_MOCK_MODE=false")
    return f"{base}{path}"


def _load_private_key(pem_text: str, path: str):
    text = pem_text or _read_text(path)
    if not text:
        raise RuntimeError("Payment private key is not configured")
    if "BEGIN" not in text:
        text = f"-----BEGIN PRIVATE KEY-----\n{text}\n-----END PRIVATE KEY-----"
    return serialization.load_pem_private_key(text.encode("utf-8"), password=None)


def _load_public_key(pem_text: str, path: str):
    text = pem_text or _read_text(path)
    if not text:
        raise RuntimeError("Payment public key is not configured")
    if "BEGIN" not in text:
        text = f"-----BEGIN PUBLIC KEY-----\n{text}\n-----END PUBLIC KEY-----"
    return serialization.load_pem_public_key(text.encode("utf-8"))


def _read_text(path: str) -> str:
    if not path:
        return ""
    return Path(path).read_text(encoding="utf-8")
