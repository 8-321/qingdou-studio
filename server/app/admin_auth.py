import base64
import hashlib
import hmac
import json
import os
import time

TOKEN_TTL = 12 * 3600


class AdminError(Exception):
    pass


def _secret() -> bytes:
    env = os.getenv("ADMIN_SECRET", "").strip()
    if env:
        return hashlib.sha256(env.encode()).digest()
    from .byok import _master_key
    return _master_key()


def enabled() -> bool:
    return bool(os.getenv("ADMIN_PASSWORD", "").strip())


def env_admin_ids() -> set[str]:
    raw = os.getenv("ADMIN_USER_IDS", "")
    return {x.strip() for x in raw.replace(";", ",").split(",") if x.strip()}


def identity_role(user_id: str) -> str | None:
    """移动端身份：环境变量里的创始管理员优先，其次看 admins 表。"""
    user_id = (user_id or "").strip()
    if not user_id:
        return None
    if user_id in env_admin_ids():
        return "owner"
    from . import db
    return db.admin_user_role(user_id)


def has_any_admin() -> bool:
    from . import db
    return bool(env_admin_ids()) or db.admin_table_count() > 0


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def issue(subject: str = "admin") -> dict:
    payload = {"role": "admin", "sub": subject, "exp": int(time.time()) + TOKEN_TTL}
    raw = json.dumps(payload, separators=(",", ":")).encode()
    sig = hmac.new(_secret(), raw, hashlib.sha256).hexdigest()[:32]
    return {"token": _b64(raw) + "." + sig, "expires_in": TOKEN_TTL}


def login(password: str) -> dict:
    if not enabled():
        raise AdminError("ADMIN_DISABLED")
    if not hmac.compare_digest(password or "", os.getenv("ADMIN_PASSWORD", "")):
        raise AdminError("BAD_PASSWORD")
    return issue("password")


def verify(token: str) -> dict:
    if not enabled():
        raise AdminError("ADMIN_DISABLED")
    try:
        body, sig = (token or "").split(".", 1)
        raw = _unb64(body)
        want = hmac.new(_secret(), raw, hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(want, sig):
            raise AdminError("BAD_TOKEN")
        data = json.loads(raw.decode())
        if int(data.get("exp") or 0) < int(time.time()):
            raise AdminError("TOKEN_EXPIRED")
        return data
    except AdminError:
        raise
    except Exception as e:
        raise AdminError("BAD_TOKEN") from e


def require(authorization: str | None, user_id: str | None = None) -> str:
    """两种凭证都接受：网页 Bearer token，或已登录用户命中管理员名单。

    返回审计用的管理员标识。
    """
    token = (authorization or "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if token:
        if enabled():
            try:
                verify(token)
                return "admin"
            except AdminError as e:
                if str(e) not in ("BAD_TOKEN", "TOKEN_EXPIRED"):
                    raise
        from . import auth as user_auth
        try:
            sub = user_auth.verify(token)["sub"]
        except Exception:
            raise AdminError("BAD_TOKEN")
        if identity_role(sub):
            return "user:" + sub
        raise AdminError("NOT_ADMIN")
    role = identity_role(user_id or "")
    if role:
        return "user:" + (user_id or "").strip()
    raise AdminError("NOT_ADMIN")
