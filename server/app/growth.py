"""增长：邀请码、激励视频领次数。

服务端只做规则与防刷下限；微信激励视频没有可用的服务端回调，
所以用「开始 → 至少 N 秒 → 完成」的一次性 token 兜底，挡掉直接刷接口。
"""
import base64
import hashlib
import hmac
import json
import os
import time
import uuid

from . import auth, db

TOKEN_TTL = 15 * 60


class GrowthError(Exception):
    pass


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(raw: bytes) -> str:
    return hmac.new(auth._secret(), raw, hashlib.sha256).hexdigest()[:32]


def ad_unit_id() -> str:
    return (os.getenv("AD_UNIT_ID", "") or "").strip()


def ad_daily_limit() -> int:
    raw = db.kv_get("ad_reward_daily") or os.getenv("AD_REWARD_DAILY", "5")
    try:
        return max(0, min(20, int(raw)))
    except (TypeError, ValueError):
        return 5


def ad_min_seconds() -> int:
    try:
        return max(1, int(os.getenv("AD_MIN_SECONDS", "15")))
    except ValueError:
        return 15


def set_ad_daily_limit(value: int) -> int:
    value = max(0, min(20, int(value)))
    db.kv_set("ad_reward_daily", str(value))
    return value


def ad_status(user_id: str) -> dict:
    limit = ad_daily_limit()
    used = db.ad_reward_used_today(user_id)
    return {"enabled": bool(ad_unit_id()), "ad_unit_id": ad_unit_id(),
            "daily_limit": limit, "used_today": used,
            "left_today": max(0, limit - used), "min_seconds": ad_min_seconds(),
            "reward_tries": 1}


def start_ad(user_id: str) -> dict:
    status = ad_status(user_id)
    if not status["enabled"]:
        raise GrowthError("AD_NOT_CONFIGURED")
    if status["left_today"] <= 0:
        raise GrowthError("AD_LIMIT")
    reward_id = uuid.uuid4().hex[:16]
    payload = {"kind": "ad", "sub": user_id, "rid": reward_id,
               "iat": int(time.time()), "exp": int(time.time()) + TOKEN_TTL}
    raw = json.dumps(payload, separators=(",", ":")).encode()
    token = _b64(raw) + "." + _sign(raw)
    db.ad_reward_start(reward_id, user_id, reward_id)
    return {"token": token, "reward_id": reward_id, "expires_in": TOKEN_TTL,
            "min_seconds": status["min_seconds"], "left_today": status["left_today"],
            "reward_tries": 1}


def finish_ad(user_id: str, token: str) -> dict:
    try:
        body, sig = (token or "").split(".", 1)
        raw = _unb64(body)
        if not hmac.compare_digest(_sign(raw), sig):
            raise GrowthError("BAD_TOKEN")
        data = json.loads(raw.decode())
    except GrowthError:
        raise
    except Exception as e:
        raise GrowthError("BAD_TOKEN") from e
    if data.get("kind") != "ad" or data.get("sub") != user_id:
        raise GrowthError("BAD_TOKEN")
    if int(data.get("exp") or 0) < int(time.time()):
        raise GrowthError("TOKEN_EXPIRED")
    row = db.ad_reward_get(data["rid"], user_id)
    if not row:
        raise GrowthError("REWARD_NOT_FOUND")
    if row["status"] == "done":
        raise GrowthError("REWARD_USED")
    elapsed = time.time() - time.mktime(time.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S"))
    if elapsed < ad_min_seconds():
        raise GrowthError("AD_TOO_SHORT")
    if ad_daily_limit() - db.ad_reward_used_today(user_id) <= 0:
        raise GrowthError("AD_LIMIT")
    if not db.ad_reward_finish(data["rid"], user_id):
        raise GrowthError("REWARD_USED")
    db.grant_feature(user_id, "link_extract", 1, reason="ad_reward")
    status = ad_status(user_id)
    return {"ok": True, "added": 1, **status}
