import base64
import hashlib
import hmac
import json
import os
import time
import urllib.parse
import urllib.request

from .config import HTTP_PROXY

TOKEN_TTL = 30 * 24 * 3600


class AuthError(Exception):
    pass


def _secret() -> bytes:
    env = (os.getenv("AUTH_SECRET") or os.getenv("ADMIN_SECRET") or "").strip()
    if env:
        return hashlib.sha256(("user:" + env).encode()).digest()
    from .byok import _master_key
    return hashlib.sha256(b"user:" + _master_key()).digest()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def issue(user_id: str, channel: str = "mp") -> dict:
    payload = {"role": "user", "sub": user_id, "ch": channel,
               "exp": int(time.time()) + TOKEN_TTL}
    raw = json.dumps(payload, separators=(",", ":")).encode()
    sig = hmac.new(_secret(), raw, hashlib.sha256).hexdigest()[:32]
    return {"token": _b64(raw) + "." + sig, "expires_in": TOKEN_TTL}


def verify(token: str) -> dict:
    try:
        body, sig = (token or "").split(".", 1)
        raw = _unb64(body)
        want = hmac.new(_secret(), raw, hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(want, sig):
            raise AuthError("BAD_TOKEN")
        data = json.loads(raw.decode())
        if data.get("role") != "user":
            raise AuthError("BAD_TOKEN")
        if int(data.get("exp") or 0) < int(time.time()):
            raise AuthError("TOKEN_EXPIRED")
        if not data.get("sub"):
            raise AuthError("BAD_TOKEN")
        return data
    except AuthError:
        raise
    except Exception as e:
        raise AuthError("BAD_TOKEN") from e


def bearer(authorization: str | None) -> str:
    token = (authorization or "").strip()
    if token.lower().startswith("bearer "):
        return token[7:].strip()
    return ""


def resolve_user(authorization: str | None, x_user_id: str | None = None) -> str:
    """正式身份只认服务端签发的 token。

    X-User-Id 仅在 DEV_MODE=1 时接受，用于本地脚本和演示；生产环境关闭。
    """
    token = bearer(authorization)
    if token:
        return verify(token)["sub"]
    if os.getenv("DEV_MODE", "0") == "1":
        dev = (x_user_id or "").strip()
        if dev:
            return dev
    raise AuthError("NO_LOGIN")


def configured(platform: str = "mp") -> bool:
    appid, secret = _wx_credentials(platform)
    return bool(appid and secret)


def _wx_credentials(platform: str) -> tuple[str, str]:
    if platform == "app":
        return (os.getenv("WX_APP_APPID", "").strip(),
                os.getenv("WX_APP_SECRET", "").strip())
    return (os.getenv("WX_MP_APPID", "").strip(),
            os.getenv("WX_MP_SECRET", "").strip())


def wx_login(code: str, platform: str = "mp") -> dict:
    appid, secret = _wx_credentials(platform)
    if not appid or not secret:
        raise AuthError("WX_NOT_CONFIGURED")
    if not (code or "").strip():
        raise AuthError("WX_NO_CODE")
    qs = urllib.parse.urlencode({
        "appid": appid, "secret": secret,
        "js_code": code.strip(), "grant_type": "authorization_code",
    })
    url = "https://api.weixin.qq.com/sns/jscode2session?" + qs
    handlers = []
    if HTTP_PROXY:
        handlers.append(urllib.request.ProxyHandler({"http": HTTP_PROXY, "https": HTTP_PROXY}))
    opener = urllib.request.build_opener(*handlers)
    try:
        with opener.open(url, timeout=12) as r:
            data = json.loads(r.read().decode())
    except Exception as e:
        raise AuthError("WX_NETWORK") from e
    if data.get("errcode"):
        raise AuthError("WX_%s:%s" % (data.get("errcode"), data.get("errmsg", "")))
    openid = (data.get("openid") or "").strip()
    if not openid:
        raise AuthError("WX_NO_OPENID")
    return {"user_id": openid, "unionid": data.get("unionid") or "",
            "session_key": data.get("session_key") or ""}
