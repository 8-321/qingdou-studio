import base64
import hashlib
import ipaddress
import os
import socket
from pathlib import Path
from urllib.parse import urlparse

import httpx
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import DATA_DIR

MASTER_FILE = DATA_DIR / "master.key"
PREFIX = "gcm1:"


def _master_key() -> bytes:
    env = os.getenv("BYOK_MASTER_KEY", "").strip()
    if env:
        return hashlib.sha256(env.encode()).digest()
    if MASTER_FILE.exists():
        raw = MASTER_FILE.read_bytes().strip()
        try:
            decoded = base64.urlsafe_b64decode(raw)
            if len(decoded) == 32:
                return decoded
        except Exception:
            pass
        return hashlib.sha256(raw).digest()
    key = base64.urlsafe_b64encode(os.urandom(32))
    MASTER_FILE.write_bytes(key)
    try:
        os.chmod(MASTER_FILE, 0o600)
    except OSError:
        pass
    return base64.urlsafe_b64decode(key)


def encrypt(plain: str) -> str:
    nonce = os.urandom(12)
    ct = AESGCM(_master_key()).encrypt(nonce, plain.encode(), None)
    return PREFIX + base64.urlsafe_b64encode(nonce + ct).decode()


def decrypt(token: str) -> str:
    try:
        if token.startswith(PREFIX):
            blob = base64.urlsafe_b64decode(token[len(PREFIX):])
            return AESGCM(_master_key()).decrypt(blob[:12], blob[12:], None).decode()
        return Fernet(base64.urlsafe_b64encode(_master_key())).decrypt(token.encode()).decode()
    except (InvalidToken, Exception) as e:
        raise ValueError("KEY_DECRYPT_FAILED") from e


def hint(plain: str) -> str:
    return "****" + plain[-4:] if len(plain) > 4 else "****"


PROVIDERS = {
    "llm": [
        {"id": "deepseek", "name": "DeepSeek", "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat"},
        {"id": "hunyuan", "name": "腾讯混元", "base_url": "https://api.hunyuan.cloud.tencent.com/v1", "model": "hunyuan-turbos-latest"},
        {"id": "dashscope", "name": "通义千问", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus"},
        {"id": "moonshot", "name": "Moonshot", "base_url": "https://api.moonshot.cn/v1", "model": "moonshot-v1-8k"},
        {"id": "siliconflow", "name": "硅基流动", "base_url": "https://api.siliconflow.cn/v1", "model": "Qwen/Qwen2.5-7B-Instruct"},
        {"id": "openai", "name": "OpenAI", "base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
        {"id": "custom", "name": "自定义（OpenAI 兼容）", "base_url": "", "model": ""},
    ],
    "asr": [
        {"id": "openai", "name": "OpenAI Whisper", "base_url": "https://api.openai.com/v1", "model": "whisper-1"},
        {"id": "siliconflow", "name": "硅基流动 SenseVoice", "base_url": "https://api.siliconflow.cn/v1", "model": "FunAudioLLM/SenseVoiceSmall"},
        {"id": "volcengine", "name": "火山引擎", "base_url": "https://openspeech.bytedance.com", "model": "volc_auc_common"},
        {"id": "custom", "name": "自定义（OpenAI 兼容）", "base_url": "", "model": ""},
    ],
}

ALLOWED_HOSTS = {
    "api.deepseek.com", "api.hunyuan.cloud.tencent.com", "dashscope.aliyuncs.com",
    "api.moonshot.cn", "api.siliconflow.cn", "api.openai.com",
}


def check_base_url(url: str) -> None:
    p = urlparse(url)
    if p.scheme not in {"https", "http"}:
        raise ValueError("仅支持 http(s)")
    if p.scheme == "http" and os.getenv("BYOK_ALLOW_LOCAL") != "1":
        raise ValueError("必须使用 https")
    host = p.hostname or ""
    if not host:
        raise ValueError("base_url 无效")
    if os.getenv("BYOK_ALLOW_LOCAL") == "1" and host in {"127.0.0.1", "localhost"}:
        return
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise ValueError("域名无法解析") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise ValueError("不允许内网地址")


async def test_key(kind: str, provider: str, base_url: str, model: str, api_key: str) -> dict:
    if kind not in PROVIDERS:
        return {"ok": False, "msg": "未知密钥类型"}
    if not api_key:
        return {"ok": False, "msg": "缺少密钥"}
    if provider == "volcengine":
        parts = api_key.split(":")
        if len(parts) != 3:
            return {"ok": False, "msg": "格式应为 AppID:AccessToken:Cluster"}
        return {"ok": True, "msg": "格式正确，实际转写时验证"}
    if not base_url:
        return {"ok": False, "msg": "缺少 base_url"}
    try:
        check_base_url(base_url)
    except ValueError as e:
        return {"ok": False, "msg": str(e)}

    headers = {"Authorization": f"Bearer {api_key}"}
    url = base_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            if kind == "llm":
                r = await client.post(url + "/chat/completions", headers=headers, json={
                    "model": model or "gpt-4o-mini",
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 1,
                })
            else:
                r = await client.get(url + "/models", headers=headers)
        if r.status_code in (200, 201):
            return {"ok": True, "msg": "连接成功"}
        return {"ok": False, "msg": f"服务商返回 {r.status_code}", "detail": r.text[:160]}
    except httpx.TimeoutException:
        return {"ok": False, "msg": "连接超时"}
    except Exception as e:
        return {"ok": False, "msg": f"连接失败：{type(e).__name__}"}
