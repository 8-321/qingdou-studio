import base64
import json
import os
import time
import uuid
from pathlib import Path

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

API_BASE = os.getenv("WECHATPAY_BASE", "https://api.mch.weixin.qq.com").rstrip("/")


class PayError(RuntimeError):
    pass


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def configured() -> bool:
    return all(_env(n) for n in (
        "WECHATPAY_MCHID", "WECHATPAY_APPID", "WECHATPAY_SERIAL_NO",
        "WECHATPAY_PRIVATE_KEY_PATH", "WECHATPAY_APIV3_KEY", "WECHATPAY_NOTIFY_URL",
    ))


def _private_key():
    path = Path(_env("WECHATPAY_PRIVATE_KEY_PATH"))
    if not path.exists():
        raise PayError("PRIVATE_KEY_MISSING")
    return serialization.load_pem_private_key(path.read_bytes(), password=None)


def _sign(message: str) -> str:
    sig = _private_key().sign(message.encode(), padding.PKCS1v15(), hashes.SHA256())
    return base64.b64encode(sig).decode()


def _headers(method: str, path: str, body: str) -> dict:
    ts = str(int(time.time()))
    nonce = uuid.uuid4().hex
    message = f"{method}\n{path}\n{ts}\n{nonce}\n{body}\n"
    sig = _sign(message)
    auth = (
        f'WECHATPAY2-SHA256-RSA2048 mchid="{_env("WECHATPAY_MCHID")}",'
        f'nonce_str="{nonce}",signature="{sig}",timestamp="{ts}",'
        f'serial_no="{_env("WECHATPAY_SERIAL_NO")}"'
    )
    return {"Authorization": auth, "Accept": "application/json",
            "Content-Type": "application/json", "User-Agent": "script-studio/1.0"}


def _post(path: str, payload: dict) -> dict:
    if not configured():
        raise PayError("PAY_NOT_CONFIGURED")
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    try:
        with httpx.Client(timeout=15) as client:
            r = client.post(API_BASE + path, content=body, headers=_headers("POST", path, body))
    except httpx.TimeoutException as e:
        raise PayError("PAY_TIMEOUT") from e
    if r.status_code >= 300:
        raise PayError(f"PAY_HTTP_{r.status_code}:{r.text[:160]}")
    return r.json()


def create_native(order: dict, description: str) -> dict:
    data = _post("/v3/pay/transactions/native", {
        "appid": _env("WECHATPAY_APPID"),
        "mchid": _env("WECHATPAY_MCHID"),
        "description": description[:127],
        "out_trade_no": order["id"],
        "notify_url": _env("WECHATPAY_NOTIFY_URL"),
        "amount": {"total": int(order["amount_cent"]), "currency": "CNY"},
    })
    return {"mode": "native", "code_url": data.get("code_url", "")}


def create_jsapi(order: dict, description: str, openid: str) -> dict:
    data = _post("/v3/pay/transactions/jsapi", {
        "appid": _env("WECHATPAY_APPID"),
        "mchid": _env("WECHATPAY_MCHID"),
        "description": description[:127],
        "out_trade_no": order["id"],
        "notify_url": _env("WECHATPAY_NOTIFY_URL"),
        "amount": {"total": int(order["amount_cent"]), "currency": "CNY"},
        "payer": {"openid": openid},
    })
    prepay = data.get("prepay_id") or ""
    if not prepay:
        raise PayError("NO_PREPAY_ID")
    ts = str(int(time.time()))
    nonce = uuid.uuid4().hex
    package = "prepay_id=" + prepay
    pay_sign = _sign(f"{_env('WECHATPAY_APPID')}\n{ts}\n{nonce}\n{package}\n")
    return {"mode": "jsapi", "pay_params": {
        "timeStamp": ts, "nonceStr": nonce, "package": package,
        "signType": "RSA", "paySign": pay_sign,
    }}


def _verify(headers: dict, body: bytes) -> None:
    cert_path = Path(_env("WECHATPAY_PLATFORM_CERT_PATH"))
    if not cert_path.exists():
        raise PayError("PLATFORM_CERT_MISSING")
    raw = cert_path.read_bytes()
    try:
        from cryptography import x509
        cert = x509.load_pem_x509_certificate(raw).public_key()
    except Exception:
        cert = serialization.load_pem_public_key(raw)
    ts = headers.get("wechatpay-timestamp", "")
    nonce = headers.get("wechatpay-nonce", "")
    sig = headers.get("wechatpay-signature", "")
    message = f"{ts}\n{nonce}\n{body.decode()}\n".encode()
    try:
        cert.verify(base64.b64decode(sig), message, padding.PKCS1v15(), hashes.SHA256())
    except Exception as e:
        raise PayError("SIGNATURE_INVALID") from e


def parse_notify(headers: dict, body: bytes) -> dict:
    if not configured():
        raise PayError("PAY_NOT_CONFIGURED")
    _verify({k.lower(): v for k, v in headers.items()}, body)
    data = json.loads(body.decode())
    res = data.get("resource") or {}
    key = _env("WECHATPAY_APIV3_KEY").encode()
    plain = AESGCM(key).decrypt(
        res.get("nonce", "").encode(),
        base64.b64decode(res.get("ciphertext", "")),
        (res.get("associated_data") or "").encode() or None,
    )
    return json.loads(plain.decode())
