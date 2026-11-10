import asyncio
import json
import os
import mimetypes
import shutil
import subprocess
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel

from . import auth, billing, byok, db, exporters, growth, publicfile, rewrite, sec, wechatpay
from .features import FEATURES
from .admin import router as admin_router
from .config import DATA_DIR, FREE_DAILY_QUOTA, FREE_FEATURE_TRIES, MAX_UPLOAD_MB
from .pipeline import run_task
from .platforms import SUPPORTED, detect

UPLOAD_DIR = DATA_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
SESSIONS: dict[str, dict] = {}


class ParseIn(BaseModel):
    text: str
    platform: str | None = None


class WxLoginIn(BaseModel):
    code: str
    platform: str = "mp"


class DevLoginIn(BaseModel):
    user_id: str


class InviteBindIn(BaseModel):
    code: str


class AdFinishIn(BaseModel):
    token: str


class RewriteIn(BaseModel):
    style: str = "oral"
    refresh: bool = False


class TaskPatchIn(BaseModel):
    title: str | None = None
    fav: int | None = None
    tags: list[str] | None = None


class BatchExportIn(BaseModel):
    ids: list[str] = []
    fmt: str = "txt"
    zip: bool = False


AUDIO_EXT = {".mp3", ".m4a", ".wav", ".aac", ".amr", ".silk", ".flac", ".ogg"}


def feature_state(user: str, feature: str) -> dict:
    used = db.feature_used(user, feature)
    plan = db.get_plan(user)
    key = db.get_key(user, "llm" if feature in ("structure", "rewrite") else "asr")
    base = db.feature_limit(feature, FREE_FEATURE_TRIES)
    granted = db.active_grant_tries(user, feature)
    limit = base + granted
    return {
        "feature": feature,
        "name": FEATURES.get(feature, feature),
        "used": used,
        "free": limit,
        "base_free": base,
        "granted": granted,
        "left": max(0, limit - used),
        "plan": plan.get("plan", "free"),
        "credits": plan.get("credits", 0),
        "plan_until": plan.get("plan_until"),
        "key_configured": key is not None,
    }


def require_feature(user: str, feature: str) -> str:
    st = feature_state(user, feature)
    if st["key_configured"]:
        return "byok"
    if st["left"] > 0 and db.consume_feature(user, feature, st["free"]):
        return "free"
    if st["plan"] in ("pro", "team", "enterprise"):
        return "plan"
    if st["credits"] > 0 and db.spend_credit(user):
        return "credit"
    raise HTTPException(402, detail={
        "code": "TRIAL_ENDED",
        "feature": feature,
        "msg": "这个功能的 2 次免费体验用完了。配置自己的 API Key 继续免费，或签到 / 购买托管额度。",
        "options": ["byok", "credits", "signin"],
    })


class KeyIn(BaseModel):
    kind: str
    provider: str
    api_key: str
    base_url: str | None = None
    model: str | None = None
    skip_test: bool = False


def public_key(row: dict) -> dict:
    return {k: row.get(k) for k in ("id", "kind", "provider", "base_url", "model",
                                    "hint", "status", "created_at", "tested_at")}


def current_user(authorization: str | None, x_user_id: str | None) -> str:
    try:
        return auth.resolve_user(authorization, x_user_id)
    except auth.AuthError as e:
        code = str(e)
        msg = "请先登录" if code == "NO_LOGIN" else "登录已过期，请重新登录"
        raise HTTPException(401, detail={"code": code, "msg": msg})


def quota_info(user: str) -> dict:
    used = db.quota_used_today(user)
    limit = FREE_DAILY_QUOTA + db.quota_bonus_today(user)
    return {"used": used, "limit": limit,
            "left": max(0, limit - used),
            "signed": db.has_signed(user)}


app = FastAPI(title="Script Studio API", version="1.0.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)
app.include_router(admin_router)


@app.on_event("startup")
def _startup():
    db.init_db()


@app.get("/admin", response_class=HTMLResponse)
@app.get("/admin/", response_class=HTMLResponse)
def admin_page():
    return (Path(__file__).with_name("admin.html")).read_text(encoding="utf-8")


@app.get("/api/health")
def health():
    try:
        v = subprocess.run(["yt-dlp", "--version"], capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        v = "missing"
    return {"ok": True, "ytdlp": v, "free_quota": FREE_DAILY_QUOTA,
            "platforms": SUPPORTED,
            "wx_login": auth.configured("mp"),
            "wx_login_app": auth.configured("app"),
            "sec_check": sec.mode(),
            "ad_enabled": bool(growth.ad_unit_id())}


@app.post("/api/auth/wechat")
def auth_wechat(body: WxLoginIn):
    platform = "app" if body.platform == "app" else "mp"
    try:
        info = auth.wx_login(body.code, platform)
    except auth.AuthError as e:
        code = str(e).split(":")[0]
        status = 503 if code == "WX_NOT_CONFIGURED" else 401
        msgs = {
            "WX_NOT_CONFIGURED": "服务端还没配微信 AppID/AppSecret",
            "WX_NO_CODE": "缺少微信登录 code",
            "WX_NETWORK": "连不上微信登录服务，请稍后再试",
            "WX_NO_OPENID": "微信没有返回 openid",
        }
        raise HTTPException(status, detail={"code": code,
                                            "msg": msgs.get(code, "微信登录失败")})
    db.get_plan(info["user_id"])
    return {"ok": True, "user_id": info["user_id"], **auth.issue(info["user_id"], platform)}


@app.post("/api/dev/login")
def auth_dev_login(body: DevLoginIn):
    if os.getenv("DEV_MODE", "0") != "1":
        raise HTTPException(404, detail={"code": "NOT_FOUND"})
    user = (body.user_id or "").strip()
    if not user:
        raise HTTPException(400, detail={"code": "EMPTY_USER_ID", "msg": "缺少 user_id"})
    db.get_plan(user)
    return {"ok": True, "user_id": user, **auth.issue(user, "dev")}


@app.get("/api/auth/me")
def auth_me(authorization: str | None = Header(default=None),
            x_user_id: str | None = Header(default=None)):
    user = current_user(authorization, x_user_id)
    return {"ok": True, "user_id": user, "logged_in": True,
            "dev": not bool(auth.bearer(authorization))}


@app.get("/api/quota")
def quota(authorization: str | None = Header(default=None),
          x_user_id: str | None = Header(default=None)):
    return quota_info(current_user(authorization, x_user_id))


@app.post("/api/signin")
def signin(authorization: str | None = Header(default=None),
           x_user_id: str | None = Header(default=None)):
    user = current_user(authorization, x_user_id)
    if db.has_signed(user):
        raise HTTPException(409, detail={"code": "ALREADY_SIGNED", "msg": "今天已经签过了"})
    db.sign(user)
    db.add_quota(user, 1, "signin")
    db.grant_feature(user, "link_extract", 1, reason="signin")
    streak = db.signin_streak(user)
    bonus = 5 if streak > 0 and streak % 7 == 0 else 0
    if bonus:
        db.grant_feature(user, "link_extract", bonus, reason="signin_streak:%d" % streak)
    msg = "签到成功，获得 1 次链接提取"
    if bonus:
        msg = "连续签到 %d 天，额外 +%d 次" % (streak, bonus)
    return {"ok": True, "msg": msg, "streak": streak, "bonus": bonus, **quota_info(user)}


@app.post("/api/parse")
async def parse(body: ParseIn, authorization: str | None = Header(default=None),
                x_user_id: str | None = Header(default=None)):
    user = current_user(authorization, x_user_id)
    info = quota_info(user)
    if info["left"] <= 0:
        raise HTTPException(429, detail={"code": "QUOTA_EXCEEDED",
                                         "msg": "今日次数用完了，签到或看视频可再加 1 次"})
    try:
        verdict = await asyncio.to_thread(sec.check_text, body.text, user)
    except sec.SecError as e:
        raise HTTPException(503, detail={"code": str(e), "msg": "内容安全服务未配置或暂不可用"})
    if verdict.get("suggest") in ("risky", "review"):
        raise HTTPException(400, detail={"code": "CONTENT_RISKY",
                                         "msg": "这段内容未通过安全检测，换一段再试"})
    target = detect(body.text)
    if body.platform:
        target.platform = body.platform
    if target.platform in {"unknown", ""}:
        raise HTTPException(400, detail={"code": "LINK_INVALID",
                                         "msg": "没识别到链接。可以粘贴整段分享文案，或改用上传。"})
    if target.platform == "wechat_channels":
        raise HTTPException(400, detail={"code": "NEED_UPLOAD",
                                         "msg": "视频号不支持链接解析。保存视频后上传，效果一样。"})

    feature = "article_extract" if target.platform == "wechat_article" else "link_extract"
    source = require_feature(user, feature)
    task_id = uuid.uuid4().hex[:16]
    db.create_task(task_id, user, "link", target.platform, target.url)
    db.record_charge(task_id, user, feature, source)
    asyncio.create_task(run_task(task_id))
    return {"task_id": task_id, "platform": target.platform, "status": "queued", **info}


@app.get("/api/invite")
def invite_info(authorization: str | None = Header(default=None),
                x_user_id: str | None = Header(default=None)):
    user = current_user(authorization, x_user_id)
    return db.invite_stats(user)


@app.post("/api/invite/bind")
def invite_bind(body: InviteBindIn, authorization: str | None = Header(default=None),
                x_user_id: str | None = Header(default=None)):
    user = current_user(authorization, x_user_id)
    result = db.bind_invite(user, body.code)
    if not result.get("ok"):
        msg = {"INVALID_CODE": "邀请码无效", "SELF_INVITE": "不能填自己的邀请码",
               "TOO_LATE": "这个账号注册超过 3 天，不能再绑定邀请"}.get(
                   result.get("code"), "绑定失败")
        raise HTTPException(400, detail={"code": result.get("code"), "msg": msg})
    return result


@app.get("/api/rewards")
def rewards(authorization: str | None = Header(default=None),
            x_user_id: str | None = Header(default=None)):
    user = current_user(authorization, x_user_id)
    return growth.ad_status(user)


@app.post("/api/rewards/ad/start")
def ad_start(authorization: str | None = Header(default=None),
             x_user_id: str | None = Header(default=None)):
    user = current_user(authorization, x_user_id)
    try:
        return growth.start_ad(user)
    except growth.GrowthError as e:
        code = str(e)
        if code == "AD_LIMIT":
            raise HTTPException(429, detail={"code": code, "msg": "今天的视频奖励领完了"})
        raise HTTPException(503, detail={"code": code, "msg": "激励视频还没开通"})


@app.post("/api/rewards/ad/finish")
def ad_finish(body: AdFinishIn, authorization: str | None = Header(default=None),
              x_user_id: str | None = Header(default=None)):
    user = current_user(authorization, x_user_id)
    try:
        return growth.finish_ad(user, body.token)
    except growth.GrowthError as e:
        code = str(e)
        detail = {
            "AD_LIMIT": (429, "今天的视频奖励领完了"),
            "AD_TOO_SHORT": (400, "观看时间太短，没有奖励"),
            "REWARD_USED": (409, "这次奖励已经领过了"),
            "TOKEN_EXPIRED": (400, "奖励已过期，请重新观看"),
            "BAD_TOKEN": (400, "奖励凭证无效"),
        }.get(code, (400, "领取失败"))
        raise HTTPException(detail[0], detail={"code": code, "msg": detail[1]})


@app.get("/api/tasks")
def tasks(limit: int = 20, offset: int = 0, q: str = "", platform: str = "",
          status: str = "", fav: int = 0, tag: str = "", sort: str = "new",
          authorization: str | None = Header(default=None),
          x_user_id: str | None = Header(default=None)):
    user = current_user(authorization, x_user_id)
    q, platform, status, tag = q.strip()[:60], platform.strip()[:30], status.strip()[:20], tag.strip()[:10]
    page = min(max(limit, 1), 100)
    skip = max(offset, 0)
    items = db.list_tasks(user, limit=page, offset=skip, q=q, platform=platform,
                          status=status, fav=fav, tag=tag, sort=sort)
    total = db.count_tasks(user, q=q, platform=platform, status=status, fav=fav, tag=tag)
    return {"items": items, "total": total, "has_more": skip + len(items) < total}


@app.get("/api/task-tags")
def task_tags(authorization: str | None = Header(default=None),
              x_user_id: str | None = Header(default=None)):
    return {"items": db.task_tags(current_user(authorization, x_user_id))}


def _owned_task(task_id: str, user: str) -> dict:
    t = db.get_task(task_id)
    if not t or t["user_id"] != user:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "msg": "任务不存在"})
    return t


@app.patch("/api/tasks/{task_id}")
def task_patch(task_id: str, body: TaskPatchIn,
               authorization: str | None = Header(default=None),
               x_user_id: str | None = Header(default=None)):
    user = current_user(authorization, x_user_id)
    updated = db.update_task_meta(task_id, user, title=body.title,
                                  fav=body.fav, tags=body.tags)
    if updated is None:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "msg": "任务不存在"})
    try:
        tags = json.loads(updated.get("tags") or "[]")
    except (json.JSONDecodeError, TypeError):
        tags = []
    return {"id": task_id, "title": updated.get("title") or "",
            "fav": int(updated.get("fav") or 0), "tags": tags}


@app.get("/api/tasks/{task_id}")
def task_detail(task_id: str, authorization: str | None = Header(default=None),
                x_user_id: str | None = Header(default=None)):
    t = _owned_task(task_id, current_user(authorization, x_user_id))
    if isinstance(t.get("tags"), str):
        try:
            t = dict(t, tags=json.loads(t["tags"] or "[]"))
        except (json.JSONDecodeError, TypeError):
            t = dict(t, tags=[])
    return {k: t[k] for k in ("id", "platform", "title", "cover", "duration_sec", "status",
                              "stage", "progress", "error_code", "error_msg", "cost_cent",
                              "created_at", "finished_at", "fav", "tags")}


@app.post("/api/tasks/{task_id}/rewrite")
def task_rewrite(task_id: str, body: RewriteIn,
                 authorization: str | None = Header(default=None),
                 x_user_id: str | None = Header(default=None)):
    user = current_user(authorization, x_user_id)
    t = _owned_task(task_id, user)
    if t["status"] != "done":
        raise HTTPException(409, detail={"code": "NOT_READY", "status": t["status"],
                                         "msg": "出稿后才能二创"})
    style = body.style if body.style in rewrite.STYLES else "oral"
    try:
        cache = json.loads(t["rewrite_json"] or "{}")
    except Exception:
        cache = {}
    if not body.refresh and style in cache:
        return {"task_id": task_id, "cached": True, **cache[style]}
    structure = json.loads(t["structure_json"] or "{}")
    key = db.get_key(user, "llm")
    result = rewrite.generate(t, structure, style, key)
    cache[style] = result
    db.update_task(task_id, rewrite_json=json.dumps(cache, ensure_ascii=False))
    return {"task_id": task_id, "style": style, "cached": False, **result}


@app.get("/api/tasks/{task_id}/result")
def task_result(task_id: str, authorization: str | None = Header(default=None),
                x_user_id: str | None = Header(default=None)):
    t = _owned_task(task_id, current_user(authorization, x_user_id))
    if t["status"] != "done":
        failed = t["status"] in ("failed", "deleted")
        raise HTTPException(409, detail={
            "code": "TASK_FAILED" if failed else "NOT_READY",
            "status": t["status"], "progress": t["progress"],
            "error_code": t.get("error_code"),
            "msg": (t.get("error_msg") or "任务未完成") if failed else "还在处理中",
        })
    return {
        "id": t["id"], "title": t["title"], "platform": t["platform"],
        "duration_sec": t["duration_sec"], "full_text": t["full_text"],
        "segments": json.loads(t["segments_json"] or "[]"),
        "structure": json.loads(t["structure_json"] or "{}"),
    }


@app.get("/api/tasks/{task_id}/export")
def task_export(task_id: str, fmt: str = "txt",
                authorization: str | None = Header(default=None),
                x_user_id: str | None = Header(default=None)):
    user = current_user(authorization, x_user_id)
    t = _owned_task(task_id, user)
    if t["status"] != "done":
        raise HTTPException(409, detail={"code": "NOT_READY", "status": t["status"],
                                         "msg": "出稿后才能导出"})
    try:
        data, mime, ext = exporters.build(fmt, [t])
    except ValueError as e:
        raise HTTPException(400, detail={"code": str(e), "msg": "不支持的导出格式"})
    filename = exporters.safe_name(t.get("title") or "文案") + "." + ext
    return Response(content=data, media_type=mime, headers={
        "Content-Disposition": exporters.content_disposition(filename),
        "Cache-Control": "no-store",
        "X-Export-Bytes": str(len(data)),
    })


@app.post("/api/export/batch")
def export_batch(body: BatchExportIn,
                 authorization: str | None = Header(default=None),
                 x_user_id: str | None = Header(default=None)):
    user = current_user(authorization, x_user_id)
    ids = list(dict.fromkeys([str(i).strip() for i in body.ids if str(i).strip()]))[:100]
    if not ids:
        raise HTTPException(400, detail={"code": "NO_TASKS", "msg": "请选择要导出的稿子"})
    picked: list[dict] = []
    for tid in ids:
        t = db.get_task(tid)
        if not t or t["user_id"] != user:
            raise HTTPException(404, detail={"code": "NOT_FOUND", "msg": "任务不存在", "id": tid})
        if t["status"] != "done":
            raise HTTPException(409, detail={"code": "NOT_READY", "msg": "有稿子还没生成完", "id": tid})
        picked.append(t)
    fmt = (body.fmt or "txt").lower()
    if fmt not in exporters.FORMATS:
        raise HTTPException(400, detail={"code": "BAD_FORMAT", "msg": "不支持的导出格式"})
    try:
        if body.zip:
            data = exporters.build_zip(fmt, picked)
            filename = "文案合集-%s-%d条.zip" % (db.now()[:10].replace("-", ""), len(picked))
            mime = "application/zip"
        else:
            data, mime, ext = exporters.build(fmt, picked)
            base = exporters.safe_name(picked[0].get("title") or "文案") if len(picked) == 1 \
                else "文案合集-%d条" % len(picked)
            filename = base + "." + ext
    except ValueError as e:
        raise HTTPException(400, detail={"code": str(e), "msg": "导出失败"})
    return Response(content=data, media_type=mime, headers={
        "Content-Disposition": exporters.content_disposition(filename),
        "Cache-Control": "no-store",
        "X-Export-Count": str(len(picked)),
        "X-Export-Bytes": str(len(data)),
    })


@app.get("/api/public/audio/{token}")
def public_audio(token: str):
    try:
        path = publicfile.resolve_token(token)
    except ValueError:
        raise HTTPException(404, detail={"code": "NOT_FOUND"})
    return FileResponse(path)


def _media_check_guard(path: Path, feature: str, user: str) -> str:
    """音频先送异步机审；视频等转写完再查文本。未配置时自动跳过。"""
    if feature != "audio_extract":
        return ""
    try:
        url = publicfile.public_url(path)
        result = sec.submit_media(url, 1, user)
        return result.get("trace_id") or ""
    except (ValueError, sec.SecError) as e:
        if sec.mode() == "enforce":
            raise HTTPException(503, detail={"code": str(e),
                                             "msg": "内容安全服务未配置或上传地址不是 HTTPS"})
        return ""


@app.post("/api/upload/init")
async def upload_init(request: Request, authorization: str | None = Header(default=None),
                      x_user_id: str | None = Header(default=None)):
    user = current_user(authorization, x_user_id)
    body = await request.json()
    name = str(body.get("filename") or "upload.bin")
    size = int(body.get("size") or 0)
    if size > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, detail={"code": "TOO_LARGE",
                                         "msg": f"单文件上限 {MAX_UPLOAD_MB} MB"})
    upload_id = uuid.uuid4().hex[:16]
    ext = Path(name).suffix.lower() or ".bin"
    path = UPLOAD_DIR / f"{upload_id}{ext}"
    path.touch()
    SESSIONS[upload_id] = {"path": path, "name": name, "size": size, "user": user}
    return {"upload_id": upload_id, "offset": 0, "chunk_size": 5 * 1024 * 1024}


@app.put("/api/upload/{upload_id}/chunk")
async def upload_chunk(upload_id: str, request: Request, offset: int = 0,
                       authorization: str | None = Header(default=None),
                       x_user_id: str | None = Header(default=None)):
    user = current_user(authorization, x_user_id)
    s = SESSIONS.get(upload_id)
    if not s or s.get("user") != user:
        raise HTTPException(404, detail={"code": "NO_SESSION", "msg": "上传会话不存在"})
    data = await request.body()
    if offset != s["path"].stat().st_size:
        raise HTTPException(409, detail={"code": "OFFSET_MISMATCH",
                                         "msg": "偏移不一致，请从服务端返回的 offset 续传",
                                         "offset": s["path"].stat().st_size})
    with open(s["path"], "ab") as f:
        f.write(data)
    return {"ok": True, "offset": s["path"].stat().st_size}


@app.post("/api/upload/{upload_id}/complete")
async def upload_complete(upload_id: str, authorization: str | None = Header(default=None),
                          x_user_id: str | None = Header(default=None)):
    user = current_user(authorization, x_user_id)
    s = SESSIONS.get(upload_id)
    if not s or s.get("user") != user:
        raise HTTPException(404, detail={"code": "NO_SESSION", "msg": "上传会话不存在"})
    info = quota_info(user)
    if info["left"] <= 0:
        raise HTTPException(429, detail={"code": "QUOTA_EXCEEDED", "msg": "今日次数用完了"})
    feature = "audio_extract" if Path(s["name"]).suffix.lower() in AUDIO_EXT else "video_extract"
    trace = _media_check_guard(s["path"], feature, user)
    source = require_feature(user, feature)
    task_id = uuid.uuid4().hex[:16]
    db.create_task(task_id, user, "upload", "upload", str(s["path"]), s["name"])
    db.record_charge(task_id, user, feature, source)
    if trace:
        db.add_sec_check(trace, task_id, user, 1)
    asyncio.create_task(run_task(task_id))
    SESSIONS.pop(upload_id, None)
    return {"task_id": task_id, "status": "queued", **info}


@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: str, authorization: str | None = Header(default=None),
                x_user_id: str | None = Header(default=None)):
    _owned_task(task_id, current_user(authorization, x_user_id))
    db.update_task(task_id, status="deleted")
    return {"ok": True}


@app.post("/api/upload/simple")
async def upload_simple(file: UploadFile = File(...),
                        authorization: str | None = Header(default=None),
                        x_user_id: str | None = Header(default=None)):
    user = current_user(authorization, x_user_id)
    info = quota_info(user)
    if info["left"] <= 0:
        raise HTTPException(429, detail={"code": "QUOTA_EXCEEDED", "msg": "今日次数用完了"})
    name = file.filename or "upload.bin"
    feature = "audio_extract" if Path(name).suffix.lower() in AUDIO_EXT else "video_extract"
    task_id = uuid.uuid4().hex[:16]
    ext = Path(name).suffix.lower() or ".bin"
    path = UPLOAD_DIR / f"{task_id}{ext}"
    with open(path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    try:
        trace = _media_check_guard(path, feature, user)
    except HTTPException:
        path.unlink(missing_ok=True)
        raise
    source = require_feature(user, feature)
    db.create_task(task_id, user, "upload", "upload", str(path), name)
    db.record_charge(task_id, user, feature, source)
    if trace:
        db.add_sec_check(trace, task_id, user, 1)
    asyncio.create_task(run_task(task_id))
    return {"task_id": task_id, "status": "queued", **info}


@app.get("/api/features")
def features(authorization: str | None = Header(default=None),
             x_user_id: str | None = Header(default=None)):
    user = current_user(authorization, x_user_id)
    return {"items": [feature_state(user, f) for f in FEATURES]}


@app.get("/api/keys")
def keys(authorization: str | None = Header(default=None),
         x_user_id: str | None = Header(default=None)):
    user = current_user(authorization, x_user_id)
    rows = [public_key(r) for r in db.list_keys(user)]
    return {"items": rows, "providers": byok.PROVIDERS}


@app.post("/api/keys")
async def save_key(body: KeyIn, authorization: str | None = Header(default=None),
                   x_user_id: str | None = Header(default=None)):
    user = current_user(authorization, x_user_id)
    presets = {p["id"]: p for p in byok.PROVIDERS.get(body.kind, [])}
    if body.provider not in presets:
        raise HTTPException(400, detail={"code": "BAD_PROVIDER", "msg": "不支持的服务商"})
    preset = presets[body.provider]
    base_url = (body.base_url or preset["base_url"]).strip()
    model = (body.model or preset["model"]).strip()
    tested = False
    if not body.skip_test:
        result = await byok.test_key(body.kind, body.provider, base_url, model, body.api_key)
        if not result.get("ok"):
            raise HTTPException(400, detail={"code": "KEY_TEST_FAILED", "msg": result.get("msg", "连接失败")})
        tested = True
    row = db.upsert_key(user, body.kind, body.provider, base_url, model,
                        byok.encrypt(body.api_key), byok.hint(body.api_key))
    if tested:
        db.touch_key(row["id"])
    return {"ok": True, "key": public_key(row), "tested": tested}


@app.post("/api/keys/{key_id}/test")
async def test_saved_key(key_id: str, authorization: str | None = Header(default=None),
                         x_user_id: str | None = Header(default=None)):
    user = current_user(authorization, x_user_id)
    row = next((r for r in db.list_keys(user) if r["id"] == key_id), None)
    if not row:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "msg": "密钥不存在"})
    result = await byok.test_key(row["kind"], row["provider"], row["base_url"], row["model"],
                                 byok.decrypt(row["cipher"]))
    if result.get("ok"):
        db.touch_key(key_id)
    return result


@app.delete("/api/keys/{key_id}")
def remove_key(key_id: str, authorization: str | None = Header(default=None),
               x_user_id: str | None = Header(default=None)):
    user = current_user(authorization, x_user_id)
    if not db.delete_key(user, key_id):
        raise HTTPException(404, detail={"code": "NOT_FOUND", "msg": "密钥不存在"})
    return {"ok": True}


class PlanIn(BaseModel):
    plan: str


class OrderIn(BaseModel):
    product_id: str
    openid: str | None = None


class RedeemIn(BaseModel):
    code: str


class DevRedeemIn(BaseModel):
    code: str
    product_id: str
    max_uses: int = 1
    expires_at: str | None = None


def public_order(o: dict) -> dict:
    return {k: o.get(k) for k in ("id", "product_id", "amount_cent", "status",
                                  "channel", "created_at", "paid_at")}


@app.post("/api/dev/plan")
def dev_plan(body: PlanIn, authorization: str | None = Header(default=None),
             x_user_id: str | None = Header(default=None)):
    if os.getenv("DEV_MODE", "0") != "1":
        raise HTTPException(404, detail={"code": "NOT_FOUND"})
    user = current_user(authorization, x_user_id)
    db.set_plan(user, body.plan)
    return {"ok": True, "plan": body.plan}


@app.get("/api/products")
def products():
    return {"items": billing.product_list()}


@app.get("/api/wallet")
def wallet(authorization: str | None = Header(default=None),
           x_user_id: str | None = Header(default=None)):
    user = current_user(authorization, x_user_id)
    plan = db.get_plan(user)
    return {"credits": int(plan.get("credits") or 0), "plan": plan.get("plan", "free"),
            "plan_until": plan.get("plan_until"),
            "orders": [public_order(o) for o in db.list_orders(user)]}


@app.post("/api/orders")
def create_order(body: OrderIn, authorization: str | None = Header(default=None),
                 x_user_id: str | None = Header(default=None)):
    user = current_user(authorization, x_user_id)
    try:
        order = billing.create_order(user, body.product_id)
    except billing.BillingError:
        raise HTTPException(400, detail={"code": "PRODUCT_NOT_FOUND", "msg": "商品不存在"})
    product = order["product"]
    pay = {"mode": "manual", "msg": "支付通道未配置，请用兑换码或联系客服"}
    if os.getenv("DEV_MODE", "0") == "1":
        pay = {"mode": "mock", "msg": "开发模式：可直接模拟支付"}
    elif wechatpay.configured():
        buyer = body.openid or (user if user.startswith("o") and len(user) == 28 else None)
        try:
            if buyer:
                pay = wechatpay.create_jsapi(order, product["name"], buyer)
            else:
                pay = wechatpay.create_native(order, product["name"])
        except wechatpay.PayError as e:
            pay = {"mode": "error", "msg": str(e)[:160]}
    return {"order": public_order(order), "product": {**product, "price_yuan": "%.2f" % (product["price_cent"] / 100)}, "pay": pay}


@app.post("/api/orders/{order_id}/mock-pay")
def mock_pay(order_id: str, authorization: str | None = Header(default=None),
             x_user_id: str | None = Header(default=None)):
    if os.getenv("DEV_MODE", "0") != "1":
        raise HTTPException(404, detail={"code": "NOT_FOUND"})
    user = current_user(authorization, x_user_id)
    order = db.get_order(order_id)
    if not order or order["user_id"] != user:
        raise HTTPException(404, detail={"code": "ORDER_NOT_FOUND", "msg": "订单不存在"})
    billing.fulfill_order(order_id, "mock", "dev-" + order_id)
    plan = db.get_plan(user)
    return {"ok": True, "order": public_order(db.get_order(order_id)),
            "credits": int(plan.get("credits") or 0), "plan": plan.get("plan", "free"),
            "plan_until": plan.get("plan_until")}


@app.post("/api/redeem")
def redeem(body: RedeemIn, authorization: str | None = Header(default=None),
           x_user_id: str | None = Header(default=None)):
    user = current_user(authorization, x_user_id)
    try:
        result = billing.redeem(user, body.code)
    except ValueError as e:
        codes = {"CODE_NOT_FOUND": "兑换码不存在", "CODE_EXPIRED": "兑换码已过期",
                 "CODE_USED": "你已经用过这个码", "CODE_EXHAUSTED": "兑换码已用完",
                 "PRODUCT_NOT_FOUND": "商品不存在"}
        raise HTTPException(400, detail={"code": str(e), "msg": codes.get(str(e), "兑换失败")})
    plan = db.get_plan(user)
    return {"ok": True, "product": result["product"], "order": public_order(result["order"]),
            "credits": int(plan.get("credits") or 0), "plan": plan.get("plan", "free"),
            "plan_until": plan.get("plan_until")}


@app.post("/api/dev/redeem")
def dev_redeem(body: DevRedeemIn):
    if os.getenv("DEV_MODE", "0") != "1":
        raise HTTPException(404, detail={"code": "NOT_FOUND"})
    if body.product_id not in billing.PRODUCTS:
        raise HTTPException(400, detail={"code": "PRODUCT_NOT_FOUND"})
    code = body.code.strip().upper()
    db.create_redeem_code(code, body.product_id, max(1, body.max_uses), body.expires_at)
    return {"ok": True, "code": code, "product_id": body.product_id}


@app.post("/api/sec/callback")
async def sec_callback(request: Request, k: str = ""):
    if not sec.verify_callback(k):
        raise HTTPException(401, detail={"code": "BAD_CALLBACK"})
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, detail={"code": "BAD_JSON"})
    result = sec.process_callback(body)
    return result


class DevSecIn(BaseModel):
    task_id: str
    suggest: str = "risky"


@app.post("/api/dev/sec-callback")
def dev_sec_callback(body: DevSecIn):
    if os.getenv("DEV_MODE", "0") != "1":
        raise HTTPException(404, detail={"code": "NOT_FOUND"})
    suggest = body.suggest if body.suggest in ("pass", "risky", "review") else "risky"
    trace = "dev_" + uuid.uuid4().hex[:12]
    db.add_sec_check(trace, body.task_id, "dev", 1)
    return sec.process_callback({"trace_id": trace, "result": {"suggest": suggest}})


@app.post("/api/pay/notify/wechat")
async def wechat_notify(request: Request):
    body = await request.body()
    try:
        data = wechatpay.parse_notify(dict(request.headers), body)
    except wechatpay.PayError as e:
        raise HTTPException(400, detail={"code": str(e)})
    if data.get("trade_state") == "SUCCESS":
        order = db.get_order(data.get("out_trade_no", ""))
        if not order:
            raise HTTPException(404, detail={"code": "ORDER_NOT_FOUND"})
        paid = int((data.get("amount") or {}).get("total") or 0)
        if paid != int(order["amount_cent"]):
            raise HTTPException(400, detail={"code": "AMOUNT_MISMATCH"})
        billing.fulfill_order(order["id"], "wechat", data.get("transaction_id", ""))
    return {"code": "SUCCESS", "message": "成功"}
