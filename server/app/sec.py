import json
import os
import time
import urllib.parse
import urllib.request

from . import db
from .config import HTTP_PROXY


class SecError(Exception):
    pass


class SecBlocked(Exception):
    def __str__(self) -> str:
        return "CONTENT_RISKY:内容未通过安全检测"


def mode() -> str:
    raw = (os.getenv("SEC_CHECK", "auto") or "auto").strip().lower()
    if raw in ("off", "enforce"):
        return raw
    return "enforce" if _credentials()[0] and _credentials()[1] else "off"


def _credentials() -> tuple[str, str]:
    return (os.getenv("WX_MP_APPID", "").strip(),
            os.getenv("WX_MP_SECRET", "").strip())


def _opener():
    handlers = []
    if HTTP_PROXY:
        handlers.append(urllib.request.ProxyHandler({"http": HTTP_PROXY, "https": HTTP_PROXY}))
    return urllib.request.build_opener(*handlers)


def _get_json(url: str) -> dict:
    with _opener().open(url, timeout=12) as r:
        return json.loads(r.read().decode())


def _post_json(url: str, payload: dict) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with _opener().open(req, timeout=12) as r:
        return json.loads(r.read().decode())


def access_token() -> str:
    cached = db.kv_get("wx_access_token")
    if cached:
        try:
            data = json.loads(cached)
            if float(data.get("exp") or 0) > time.time() + 60:
                return data["token"]
        except Exception:
            pass
    appid, secret = _credentials()
    if not appid or not secret:
        raise SecError("SEC_NOT_CONFIGURED")
    qs = urllib.parse.urlencode({
        "grant_type": "client_credential", "appid": appid, "secret": secret,
    })
    try:
        data = _get_json("https://api.weixin.qq.com/cgi-bin/token?" + qs)
    except Exception as e:
        raise SecError("WX_TOKEN_NETWORK") from e
    if data.get("errcode"):
        raise SecError("WX_TOKEN_%s" % data.get("errcode"))
    token = data.get("access_token") or ""
    if not token:
        raise SecError("WX_TOKEN_EMPTY")
    exp = time.time() + int(data.get("expires_in") or 7200) - 120
    db.kv_set("wx_access_token", json.dumps({"token": token, "exp": exp}))
    return token


def check_text(content: str, openid: str = "") -> dict:
    m = mode()
    if m == "off":
        return {"suggest": "pass", "skipped": True, "reason": "SEC_OFF"}
    mock = (os.getenv("SEC_MOCK", "") or "").strip().lower()
    if mock in ("pass", "risky", "review"):
        return {"suggest": mock, "mock": True, "skipped": False}
    if not _credentials()[0] or not _credentials()[1]:
        raise SecError("SEC_NOT_CONFIGURED")

    text = (content or "").strip()
    if not text:
        return {"suggest": "pass", "checked": 0}
    token = access_token()
    url = "https://api.weixin.qq.com/wxa/msg_sec_check?access_token=" + urllib.parse.quote(token)
    chunks = [text[i:i + 2000] for i in range(0, len(text), 2000)][:40]
    worst = "pass"
    label = 100
    for chunk in chunks:
        try:
            data = _post_json(url, {
                "content": chunk, "version": 2, "scene": 2, "openid": openid,
            })
        except Exception as e:
            raise SecError("WX_SEC_NETWORK") from e
        code = int(data.get("errcode") or 0)
        if code == 87014:
            return {"suggest": "risky", "label": 20001, "checked": len(chunks)}
        if code:
            raise SecError("WX_SEC_%s" % code)
        result = data.get("result") or {}
        suggest = result.get("suggest") or "pass"
        if suggest == "risky":
            return {"suggest": "risky", "label": result.get("label"), "checked": len(chunks)}
        if suggest == "review":
            worst = "review"
            label = result.get("label") or label
    return {"suggest": worst, "label": label, "checked": len(chunks)}


def callback_url() -> str:
    base = (os.getenv("PUBLIC_BASE_URL", "") or "").strip().rstrip("/")
    token = (os.getenv("SEC_CALLBACK_TOKEN", "") or "").strip()
    if not base.startswith("https://") or not token:
        return ""
    return base + "/api/sec/callback?k=" + urllib.parse.quote(token)


def submit_media(media_url: str, media_type: int, openid: str = "") -> dict:
    m = mode()
    if m == "off":
        return {"skipped": True, "reason": "SEC_OFF"}
    mock = (os.getenv("SEC_MOCK", "") or "").strip().lower()
    if mock:
        return {"skipped": True, "reason": "SEC_MOCK"}
    cb = callback_url()
    if not media_url.startswith("https://") or not cb:
        if m == "enforce":
            raise SecError("SEC_NEED_HTTPS_CALLBACK")
        return {"skipped": True, "reason": "NEED_HTTPS"}
    token = access_token()
    url = "https://api.weixin.qq.com/wxa/media_check_async?access_token=" + urllib.parse.quote(token)
    try:
        data = _post_json(url, {
            "media_url": media_url, "media_type": int(media_type),
            "version": 2, "scene": 2, "openid": openid, "url": cb,
        })
    except Exception as e:
        raise SecError("WX_MEDIA_NETWORK") from e
    if data.get("errcode"):
        raise SecError("WX_MEDIA_%s" % data.get("errcode"))
    trace = data.get("trace_id") or ""
    if not trace:
        raise SecError("WX_MEDIA_NO_TRACE")
    return {"trace_id": trace, "skipped": False}


def process_callback(body: dict) -> dict:
    trace = (body.get("trace_id") or "").strip()
    row = db.get_sec_check(trace) if trace else None
    if not row:
        return {"ok": False, "code": "TRACE_NOT_FOUND"}
    result = body.get("result") or {}
    suggest = (result.get("suggest") or "").strip().lower()
    if not suggest:
        suggest = "risky" if body.get("isrisky") else "pass"
    if suggest not in ("pass", "risky", "review"):
        suggest = "review"
    db.finish_sec_check(trace, suggest)
    if suggest in ("risky", "review"):
        db.block_task(row["task_id"], "SEC_RISKY", "内容未通过安全检测")
    return {"ok": True, "task_id": row["task_id"], "suggest": suggest}


def verify_callback(key: str) -> bool:
    want = (os.getenv("SEC_CALLBACK_TOKEN", "") or "").strip()
    if not want:
        return os.getenv("DEV_MODE", "0") == "1"
    return (key or "") == want
