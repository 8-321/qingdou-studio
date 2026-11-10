import os

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from . import admin_auth, billing, db, growth
from .config import FREE_FEATURE_TRIES
from .features import FEATURES

router = APIRouter(prefix="/api/admin")


class LoginIn(BaseModel):
    password: str


class ClaimIn(BaseModel):
    user_id: str | None = None


class AdminIn(BaseModel):
    user_id: str
    role: str = "admin"
    note: str = ""


class LimitIn(BaseModel):
    feature: str
    free_tries: int


class GrantIn(BaseModel):
    user_id: str
    feature: str
    extra_tries: int = 3
    days: int = 0
    reason: str = ""


class CreditIn(BaseModel):
    user_id: str
    amount: int
    reason: str = ""


class PlanIn(BaseModel):
    user_id: str
    plan: str = "pro"
    days: int = 30


class RedeemIn(BaseModel):
    code: str
    product_id: str
    max_uses: int = 1
    days: int = 0


def guard(authorization: str | None, user_id: str | None = None) -> str:
    try:
        return admin_auth.require(authorization, user_id)
    except admin_auth.AdminError as e:
        raise HTTPException(401, detail={"code": str(e), "msg": "没有管理员权限"})
    except Exception:
        raise HTTPException(401, detail={"code": "BAD_TOKEN", "msg": "管理员验证失败"})


def _uid(x_user_id: str | None, fallback: str | None = None) -> str:
    return (x_user_id or fallback or "").strip()


def _token_uid(authorization: str | None) -> str:
    from . import auth as user_auth
    raw = user_auth.bearer(authorization)
    if not raw:
        return ""
    try:
        return user_auth.verify(raw)["sub"]
    except Exception:
        return ""


@router.post("/login")
def login(body: LoginIn):
    try:
        return admin_auth.login(body.password)
    except admin_auth.AdminError as e:
        status = 404 if str(e) == "ADMIN_DISABLED" else 401
        raise HTTPException(status, detail={"code": str(e), "msg": "密码错误" if str(e) == "BAD_PASSWORD" else "管理后台未开启"})


@router.get("/me")
def me(authorization: str | None = Header(default=None),
       x_user_id: str | None = Header(default=None, alias="X-User-Id")):
    """给小程序 / APP 用：服务端判断当前登录用户是不是管理员，前端不出现密码框。"""
    uid = _uid(x_user_id) or _token_uid(authorization)
    role = admin_auth.identity_role(uid)
    token_ok = False
    raw = (authorization or "").strip()
    if raw.lower().startswith("bearer "):
        try:
            admin_auth.verify(raw[7:].strip())
            token_ok = True
        except admin_auth.AdminError:
            token_ok = False
    return {
        "user_id": uid,
        "is_admin": bool(role or token_ok),
        "role": role or ("web" if token_ok else None),
        "can_claim": not admin_auth.has_any_admin(),
        "password_enabled": admin_auth.enabled(),
        "identity_enabled": bool(admin_auth.env_admin_ids()) or db.admin_table_count() > 0,
    }


@router.post("/claim")
def claim(body: ClaimIn,
          x_user_id: str | None = Header(default=None, alias="X-User-Id")):
    """首次认领管理员：只有系统里一个管理员都没有时可用，避免被人抢先。"""
    uid = _uid(x_user_id) or _token_uid(authorization)
    if not uid and os.getenv("DEV_MODE", "0") == "1":
        uid = (body.user_id or "").strip()
    if not uid:
        raise HTTPException(400, detail={"code": "NO_IDENTITY", "msg": "无法识别当前用户"})
    if admin_auth.has_any_admin():
        raise HTTPException(409, detail={"code": "ALREADY_CLAIMED", "msg": "管理员已设置，请联系现有管理员添加你"})
    row = db.add_admin(uid, "owner", "首次认领", "claim")
    db.audit("user:" + uid, "claim_admin", uid, "first owner")
    return {"ok": True, "is_admin": True, "role": "owner", "admin": row}


@router.get("/admins")
def admins(authorization: str | None = Header(default=None),
           x_user_id: str | None = Header(default=None, alias="X-User-Id")):
    guard(authorization, x_user_id)
    items = [{"user_id": u, "role": "owner", "source": "env", "note": "环境变量 ADMIN_USER_IDS",
              "created_at": None} for u in sorted(admin_auth.env_admin_ids())]
    items += [{**row, "source": "db"} for row in db.admin_rows()]
    return {"items": items}


@router.post("/admins")
def admin_add(body: AdminIn,
              authorization: str | None = Header(default=None),
              x_user_id: str | None = Header(default=None, alias="X-User-Id")):
    actor = guard(authorization, x_user_id)
    uid = body.user_id.strip()
    if not uid:
        raise HTTPException(400, detail={"code": "EMPTY_USER_ID", "msg": "请填写用户 ID"})
    role = body.role if body.role in ("admin", "viewer") else "admin"
    row = db.add_admin(uid, role, body.note, actor)
    db.audit(actor, "add_admin", uid, role)
    return {"ok": True, "admin": row}


@router.delete("/admins/{user_id}")
def admin_remove(user_id: str,
                 authorization: str | None = Header(default=None),
                 x_user_id: str | None = Header(default=None, alias="X-User-Id")):
    actor = guard(authorization, x_user_id)
    if user_id in admin_auth.env_admin_ids():
        raise HTTPException(400, detail={"code": "ENV_OWNER", "msg": "创始管理员写在环境变量里，请直接改服务器配置"})
    if user_id in (_uid(x_user_id), _token_uid(authorization)) or actor == "user:" + user_id:
        raise HTTPException(400, detail={"code": "CANNOT_REMOVE_SELF", "msg": "不能移除自己"})
    if not db.remove_admin(user_id):
        raise HTTPException(404, detail={"code": "NOT_FOUND", "msg": "该用户不是管理员"})
    db.audit(actor, "remove_admin", user_id, "")
    return {"ok": True}


@router.post("/app-token")
def app_token(authorization: str | None = Header(default=None),
              x_user_id: str | None = Header(default=None, alias="X-User-Id")):
    """APP 内嵌 H5 后台用：已登录的管理员换一个短期 token，放进 URL 的 # 片段。"""
    actor = guard(authorization, x_user_id)
    data = admin_auth.issue(actor)
    return {"ok": True, **data}


@router.get("/mobile")
def mobile(authorization: str | None = Header(default=None),
           x_user_id: str | None = Header(default=None, alias="X-User-Id")):
    """小程序 / APP 一次拿到概览 + 功能额度 + 最近任务，少发请求。"""
    guard(authorization, x_user_id)
    data = db.admin_mobile()
    data["overview"]["revenue_yuan"] = "%.2f" % (data["overview"].get("revenue_cent", 0) / 100.0)
    data["features"] = [
        {"feature": f, "name": n, "free_tries": db.feature_limit(f, FREE_FEATURE_TRIES)}
        for f, n in FEATURES.items()
    ]
    data["default_free"] = FREE_FEATURE_TRIES
    return data


@router.get("/overview")
def overview(authorization: str | None = Header(default=None),
             x_user_id: str | None = Header(default=None, alias="X-User-Id")):
    guard(authorization, x_user_id)
    return db.admin_overview()


@router.get("/config")
def config(authorization: str | None = Header(default=None),
           x_user_id: str | None = Header(default=None, alias="X-User-Id")):
    guard(authorization, x_user_id)
    items = [{"feature": f, "name": n,
              "free_tries": db.feature_limit(f, FREE_FEATURE_TRIES)}
             for f, n in FEATURES.items()]
    return {"default": FREE_FEATURE_TRIES, "items": items}


@router.post("/config")
def set_config(body: LimitIn,
               authorization: str | None = Header(default=None),
               x_user_id: str | None = Header(default=None, alias="X-User-Id")):
    admin = guard(authorization, x_user_id)
    if body.feature not in FEATURES:
        raise HTTPException(400, detail={"code": "BAD_FEATURE"})
    if body.free_tries < 0 or body.free_tries > 100:
        raise HTTPException(400, detail={"code": "BAD_LIMIT", "msg": "0-100 之间"})
    db.set_feature_limit(body.feature, body.free_tries)
    db.audit(admin, "set_limit", body.feature, str(body.free_tries))
    return {"ok": True, "feature": body.feature, "free_tries": body.free_tries}


class GrowthIn(BaseModel):
    ad_reward_daily: int


@router.get("/growth")
def growth_config(authorization: str | None = Header(default=None),
                  x_user_id: str | None = Header(default=None, alias="X-User-Id")):
    guard(authorization, x_user_id)
    return {"ad_enabled": bool(growth.ad_unit_id()),
            "ad_reward_daily": growth.ad_daily_limit(),
            "invites_total": db.admin_growth_overview()["invites_total"],
            "invites_rewarded": db.admin_growth_overview()["invites_rewarded"]}


@router.post("/growth")
def set_growth(body: GrowthIn,
               authorization: str | None = Header(default=None),
               x_user_id: str | None = Header(default=None, alias="X-User-Id")):
    admin = guard(authorization, x_user_id)
    value = growth.set_ad_daily_limit(body.ad_reward_daily)
    db.audit(admin, "set_growth", "ad_reward_daily", str(value))
    return {"ok": True, "ad_reward_daily": value}


@router.get("/users")
def users(q: str = "", limit: int = 50,
          authorization: str | None = Header(default=None),
          x_user_id: str | None = Header(default=None, alias="X-User-Id")):
    guard(authorization, x_user_id)
    return {"items": db.admin_users(q, limit)}


@router.get("/users/{user_id}")
def user_detail(user_id: str,
                authorization: str | None = Header(default=None),
                x_user_id: str | None = Header(default=None, alias="X-User-Id")):
    guard(authorization, x_user_id)
    return db.admin_user_detail(user_id)


@router.post("/grants")
def grant(body: GrantIn,
          authorization: str | None = Header(default=None),
          x_user_id: str | None = Header(default=None, alias="X-User-Id")):
    admin = guard(authorization, x_user_id)
    if body.feature not in FEATURES:
        raise HTTPException(400, detail={"code": "BAD_FEATURE"})
    if body.extra_tries < 1 or body.extra_tries > 1000:
        raise HTTPException(400, detail={"code": "BAD_TRIES"})
    row = db.add_grant(body.user_id, body.feature, body.extra_tries, body.days,
                       body.reason, admin)
    db.audit(admin, "grant", body.user_id,
             "%s +%d %s" % (body.feature, body.extra_tries, body.reason))
    return {"ok": True, "grant": row}


@router.post("/credits")
def credits(body: CreditIn,
            authorization: str | None = Header(default=None),
            x_user_id: str | None = Header(default=None, alias="X-User-Id")):
    admin = guard(authorization, x_user_id)
    if body.amount == 0 or abs(body.amount) > 100000:
        raise HTTPException(400, detail={"code": "BAD_AMOUNT"})
    total = db.add_credits(body.user_id, body.amount, "admin:" + (body.reason or admin))
    db.audit(admin, "credits", body.user_id, "%+d %s" % (body.amount, body.reason))
    return {"ok": True, "credits": total}


@router.post("/plan")
def plan(body: PlanIn,
         authorization: str | None = Header(default=None),
         x_user_id: str | None = Header(default=None, alias="X-User-Id")):
    admin = guard(authorization, x_user_id)
    if body.plan not in ("free", "pro", "team", "enterprise"):
        raise HTTPException(400, detail={"code": "BAD_PLAN"})
    if body.plan == "free":
        db.set_plan(body.user_id, "free")
        until = None
    else:
        until = db.set_plan_until(body.user_id, body.plan, max(1, body.days))
    db.audit(admin, "plan", body.user_id, "%s %d days" % (body.plan, body.days))
    return {"ok": True, "plan": body.plan, "plan_until": until}


@router.get("/orders")
def orders(limit: int = 50,
           authorization: str | None = Header(default=None),
           x_user_id: str | None = Header(default=None, alias="X-User-Id")):
    guard(authorization, x_user_id)
    return {"items": db.admin_orders(limit)}


@router.get("/redeem")
def redeem_list(limit: int = 100,
                authorization: str | None = Header(default=None),
                x_user_id: str | None = Header(default=None, alias="X-User-Id")):
    guard(authorization, x_user_id)
    return {"items": db.admin_redeem_list(limit)}


@router.post("/redeem")
def redeem_create(body: RedeemIn,
                  authorization: str | None = Header(default=None),
                  x_user_id: str | None = Header(default=None, alias="X-User-Id")):
    admin = guard(authorization, x_user_id)
    if body.product_id not in billing.PRODUCTS:
        raise HTTPException(400, detail={"code": "PRODUCT_NOT_FOUND"})
    code = body.code.strip().upper()
    if len(code) < 4:
        raise HTTPException(400, detail={"code": "CODE_TOO_SHORT"})
    expires = None
    if body.days and body.days > 0:
        from datetime import datetime, timedelta
        expires = (datetime.now() + timedelta(days=body.days)).strftime("%Y-%m-%d %H:%M:%S")
    db.create_redeem_code(code, body.product_id, max(1, body.max_uses), expires)
    db.audit(admin, "redeem_create", code, body.product_id)
    return {"ok": True, "code": code, "product_id": body.product_id, "expires_at": expires}


@router.get("/audit")
def audit(limit: int = 50,
          authorization: str | None = Header(default=None),
          x_user_id: str | None = Header(default=None, alias="X-User-Id")):
    guard(authorization, x_user_id)
    return {"items": db.audit_list(limit)}
