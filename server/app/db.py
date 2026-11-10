import hashlib
import json
import sqlite3
import time
import uuid
from datetime import datetime, timedelta
from typing import Any

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks(
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  source_type TEXT NOT NULL,
  platform TEXT NOT NULL,
  source_url TEXT,
  title TEXT,
  cover TEXT,
  duration_sec REAL DEFAULT 0,
  status TEXT NOT NULL,
  stage TEXT,
  progress INTEGER DEFAULT 0,
  error_code TEXT,
  error_msg TEXT,
  cost_cent REAL DEFAULT 0,
  created_at TEXT NOT NULL,
  finished_at TEXT,
  segments_json TEXT,
  structure_json TEXT,
  full_text TEXT,
  rewrite_json TEXT
);
CREATE TABLE IF NOT EXISTS quota_logs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL,
  delta INTEGER NOT NULL,
  reason TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS signins(
  user_id TEXT NOT NULL,
  day TEXT NOT NULL,
  PRIMARY KEY(user_id, day)
);
"""


SCHEMA_BYOK = """
CREATE TABLE IF NOT EXISTS user_keys(
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  provider TEXT NOT NULL,
  base_url TEXT,
  model TEXT,
  cipher TEXT NOT NULL,
  hint TEXT NOT NULL,
  status TEXT DEFAULT 'active',
  created_at TEXT NOT NULL,
  tested_at TEXT,
  UNIQUE(user_id, kind)
);
CREATE TABLE IF NOT EXISTS feature_usage(
  user_id TEXT NOT NULL,
  feature TEXT NOT NULL,
  used INTEGER DEFAULT 0,
  PRIMARY KEY(user_id, feature)
);
CREATE TABLE IF NOT EXISTS users(
  id TEXT PRIMARY KEY,
  plan TEXT DEFAULT 'free',
  credits INTEGER DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS task_charges(
  task_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  feature TEXT NOT NULL,
  source TEXT NOT NULL
);
"""

def conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    return c


SCHEMA_BILLING = """
CREATE TABLE IF NOT EXISTS orders(
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  product_id TEXT NOT NULL,
  amount_cent INTEGER NOT NULL,
  status TEXT NOT NULL,
  channel TEXT,
  channel_txn TEXT,
  created_at TEXT NOT NULL,
  paid_at TEXT
);
CREATE TABLE IF NOT EXISTS credit_logs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL,
  delta INTEGER NOT NULL,
  reason TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS redeem_codes(
  code TEXT PRIMARY KEY,
  product_id TEXT NOT NULL,
  max_uses INTEGER DEFAULT 1,
  used INTEGER DEFAULT 0,
  expires_at TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS redeem_uses(
  code TEXT NOT NULL,
  user_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY(code, user_id)
);
"""


SCHEMA_ADMIN = """
CREATE TABLE IF NOT EXISTS feature_limits(
  feature TEXT PRIMARY KEY,
  free_tries INTEGER NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS feature_grants(
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  feature TEXT NOT NULL,
  extra_tries INTEGER NOT NULL,
  reason TEXT,
  created_by TEXT,
  created_at TEXT NOT NULL,
  expires_at TEXT
);
CREATE TABLE IF NOT EXISTS admin_audit(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  admin TEXT NOT NULL,
  action TEXT NOT NULL,
  target TEXT,
  detail TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS admins(
  user_id TEXT PRIMARY KEY,
  role TEXT NOT NULL DEFAULT 'admin',
  note TEXT,
  created_by TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings(
  key TEXT PRIMARY KEY,
  value TEXT,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sec_checks(
  trace_id TEXT PRIMARY KEY,
  task_id TEXT,
  user_id TEXT,
  media_type INTEGER,
  status TEXT DEFAULT 'pending',
  created_at TEXT NOT NULL,
  updated_at TEXT
);
"""


SCHEMA_GROWTH = """
CREATE TABLE IF NOT EXISTS invites(
  invitee_id TEXT PRIMARY KEY,
  inviter_id TEXT NOT NULL,
  code TEXT NOT NULL,
  status TEXT DEFAULT 'bound',
  reward_days INTEGER DEFAULT 0,
  created_at TEXT NOT NULL,
  rewarded_at TEXT
);
CREATE TABLE IF NOT EXISTS ad_rewards(
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  token_id TEXT NOT NULL,
  status TEXT DEFAULT 'started',
  created_at TEXT NOT NULL,
  finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_invites_inviter ON invites(inviter_id);
CREATE INDEX IF NOT EXISTS idx_ad_rewards_user ON ad_rewards(user_id, created_at);
"""


def init_db() -> None:
    with conn() as c:
        c.executescript(SCHEMA)
        c.executescript(SCHEMA_BYOK)
        c.executescript(SCHEMA_BILLING)
        c.executescript(SCHEMA_ADMIN)
        c.executescript(SCHEMA_GROWTH)
        cols = [r[1] for r in c.execute("PRAGMA table_info(users)").fetchall()]
        if "plan_until" not in cols:
            c.execute("ALTER TABLE users ADD COLUMN plan_until TEXT")
        task_cols = [r[1] for r in c.execute("PRAGMA table_info(tasks)").fetchall()]
        if "rewrite_json" not in task_cols:
            c.execute("ALTER TABLE tasks ADD COLUMN rewrite_json TEXT")
        if "fav" not in task_cols:
            c.execute("ALTER TABLE tasks ADD COLUMN fav INTEGER DEFAULT 0")
        if "tags" not in task_cols:
            c.execute("ALTER TABLE tasks ADD COLUMN tags TEXT DEFAULT ''")
        c.execute("CREATE INDEX IF NOT EXISTS idx_tasks_user_created ON tasks(user_id, created_at)")
        for col, ddl in (("invite_code", "TEXT"), ("invited_by", "TEXT")):
            if col not in cols:
                c.execute("ALTER TABLE users ADD COLUMN %s %s" % (col, ddl))
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_invite_code "
                  "ON users(invite_code) WHERE invite_code IS NOT NULL")


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def create_task(task_id: str, user_id: str, source_type: str, platform: str,
                source_url: str = "", title: str = "") -> dict:
    with conn() as c:
        c.execute(
            "INSERT INTO tasks(id,user_id,source_type,platform,source_url,title,status,stage,progress,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (task_id, user_id, source_type, platform, source_url, title, "queued", "排队中", 0, now()),
        )
    return get_task(task_id)


def update_task(task_id: str, **fields: Any) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    with conn() as c:
        c.execute(f"UPDATE tasks SET {cols} WHERE id=?", (*fields.values(), task_id))


def get_task(task_id: str) -> dict | None:
    with conn() as c:
        row = c.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    return dict(row) if row else None


def _task_filter(user_id: str, q: str = "", platform: str = "", status: str = "",
                 fav: int = 0, tag: str = "") -> tuple[str, list]:
    where = ["user_id=?", "status!='deleted'"]
    args: list = [user_id]
    if q:
        like = "%" + q.replace("%", "").replace("_", "") + "%"
        where.append("(title LIKE ? OR full_text LIKE ?)")
        args += [like, like]
    if platform:
        where.append("platform=?")
        args.append(platform)
    if status:
        where.append("status=?")
        args.append(status)
    if fav:
        where.append("fav=1")
    if tag:
        where.append("tags LIKE ? ESCAPE '\\'")
        safe = tag.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        args.append('%"' + safe + '"%')
    return " AND ".join(where), args


SORT_SQL = {
    "new": "COALESCE(finished_at, created_at) DESC",
    "old": "COALESCE(finished_at, created_at) ASC",
    "duration": "duration_sec DESC, COALESCE(finished_at, created_at) DESC",
    "fav": "fav DESC, COALESCE(finished_at, created_at) DESC",
}


def list_tasks(user_id: str, limit: int = 20, offset: int = 0, q: str = "",
               platform: str = "", status: str = "", fav: int = 0, tag: str = "",
               sort: str = "new") -> list[dict]:
    where, args = _task_filter(user_id, q, platform, status, fav, tag)
    order = SORT_SQL.get(sort, SORT_SQL["new"])
    sql = ("SELECT id,platform,title,status,progress,duration_sec,created_at,fav,tags,error_code,"
           "length(COALESCE(full_text,'')) AS chars, "
           "substr(COALESCE(full_text,''),1,120) AS snippet FROM tasks WHERE " + where +
           " ORDER BY " + order + " LIMIT ? OFFSET ?")
    with conn() as c:
        rows = c.execute(sql, (*args, limit, offset)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["tags"] = json.loads(d.get("tags") or "[]")
        except (json.JSONDecodeError, TypeError):
            d["tags"] = []
        out.append(d)
    return out


def count_tasks(user_id: str, q: str = "", platform: str = "", status: str = "",
                fav: int = 0, tag: str = "") -> int:
    where, args = _task_filter(user_id, q, platform, status, fav, tag)
    with conn() as c:
        row = c.execute("SELECT COUNT(*) AS n FROM tasks WHERE " + where, tuple(args)).fetchone()
    return int(row["n"])


def task_tags(user_id: str) -> list[dict]:
    counts: dict[str, int] = {}
    with conn() as c:
        rows = c.execute(
            "SELECT tags FROM tasks WHERE user_id=? AND tags IS NOT NULL AND tags!=''",
            (user_id,),
        ).fetchall()
    for r in rows:
        try:
            tags = json.loads(r["tags"] or "[]")
        except (json.JSONDecodeError, TypeError):
            continue
        for t in tags:
            t = str(t).strip()
            if t:
                counts[t] = counts.get(t, 0) + 1
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [{"tag": k, "count": v} for k, v in ordered]


def normalize_tags(tags) -> list[str]:
    out: list[str] = []
    for t in tags or []:
        t = str(t).strip().replace(",", " ").replace("，", " ")[:10]
        if t and t not in out:
            out.append(t)
        if len(out) >= 8:
            break
    return out


def update_task_meta(task_id: str, user_id: str, title: str | None = None,
                     fav: int | None = None, tags=None) -> dict | None:
    task = get_task(task_id)
    if not task or task["user_id"] != user_id:
        return None
    fields: dict = {}
    if title is not None:
        clean = str(title).strip()[:80]
        fields["title"] = clean or task.get("title") or ""
    if fav is not None:
        fields["fav"] = 1 if fav else 0
    if tags is not None:
        fields["tags"] = json.dumps(normalize_tags(tags), ensure_ascii=False)
    if fields:
        update_task(task_id, **fields)
    return get_task(task_id)


def save_result(task_id: str, full_text: str, segments: list[dict], structure: dict, cost_cent: float) -> None:
    update_task(
        task_id,
        status="done",
        stage="完成",
        progress=100,
        full_text=full_text,
        segments_json=json.dumps(segments, ensure_ascii=False),
        structure_json=json.dumps(structure, ensure_ascii=False),
        cost_cent=round(cost_cent, 3),
        finished_at=now(),
    )


def quota_used_today(user_id: str) -> int:
    today = datetime.now().strftime("%Y-%m-%d")
    with conn() as c:
        row = c.execute(
            "SELECT COUNT(*) AS n FROM tasks WHERE user_id=? AND created_at LIKE ? AND status!='failed'",
            (user_id, today + "%"),
        ).fetchone()
    return int(row["n"])


def quota_bonus_today(user_id: str) -> int:
    today = datetime.now().strftime("%Y-%m-%d")
    with conn() as c:
        row = c.execute(
            "SELECT COALESCE(SUM(delta),0) AS n FROM quota_logs WHERE user_id=? AND created_at LIKE ?",
            (user_id, today + "%"),
        ).fetchone()
    return max(0, int(row["n"]))


def add_quota(user_id: str, delta: int, reason: str) -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO quota_logs(user_id,delta,reason,created_at) VALUES(?,?,?,?)",
            (user_id, delta, reason, now()),
        )


def signin_streak(user_id: str) -> int:
    today = datetime.now().date()
    start = (today - timedelta(days=400)).strftime("%Y-%m-%d")
    with conn() as c:
        rows = c.execute(
            "SELECT day FROM signins WHERE user_id=? AND day>=?", (user_id, start)).fetchall()
    days = {r["day"] for r in rows}
    streak = 0
    cur = today
    while cur.strftime("%Y-%m-%d") in days:
        streak += 1
        cur -= timedelta(days=1)
    return streak


def has_signed(user_id: str) -> bool:
    today = datetime.now().strftime("%Y-%m-%d")
    with conn() as c:
        row = c.execute("SELECT 1 FROM signins WHERE user_id=? AND day=?", (user_id, today)).fetchone()
    return row is not None


def sign(user_id: str) -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    with conn() as c:
        c.execute("INSERT OR IGNORE INTO signins(user_id,day) VALUES(?,?)", (user_id, today))



def upsert_key(user_id: str, kind: str, provider: str, base_url: str,
               model: str, cipher: str, key_hint: str) -> dict:
    kid = uuid.uuid4().hex[:12]
    with conn() as c:
        c.execute(
            "INSERT INTO user_keys(id,user_id,kind,provider,base_url,model,cipher,hint,status,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(user_id,kind) DO UPDATE SET"
            " provider=excluded.provider, base_url=excluded.base_url, model=excluded.model,"
            " cipher=excluded.cipher, hint=excluded.hint, status='active', created_at=excluded.created_at",
            (kid, user_id, kind, provider, base_url, model, cipher, key_hint, "active", now()),
        )
        row = c.execute("SELECT * FROM user_keys WHERE user_id=? AND kind=?", (user_id, kind)).fetchone()
    return dict(row)


def list_keys(user_id: str) -> list[dict]:
    with conn() as c:
        rows = c.execute("SELECT * FROM user_keys WHERE user_id=? ORDER BY kind", (user_id,)).fetchall()
    return [dict(r) for r in rows]


def get_key(user_id: str, kind: str) -> dict | None:
    with conn() as c:
        row = c.execute("SELECT * FROM user_keys WHERE user_id=? AND kind=? AND status='active'",
                        (user_id, kind)).fetchone()
    return dict(row) if row else None


def delete_key(user_id: str, key_id: str) -> bool:
    with conn() as c:
        cur = c.execute("DELETE FROM user_keys WHERE user_id=? AND id=?", (user_id, key_id))
    return cur.rowcount > 0


def touch_key(key_id: str) -> None:
    with conn() as c:
        c.execute("UPDATE user_keys SET tested_at=? WHERE id=?", (now(), key_id))


def feature_used(user_id: str, feature: str) -> int:
    with conn() as c:
        row = c.execute("SELECT used FROM feature_usage WHERE user_id=? AND feature=?",
                        (user_id, feature)).fetchone()
    return int(row["used"]) if row else 0


def grant_feature(user_id: str, feature: str, n: int = 1,
                  reason: str = "grant", days: int = 0) -> None:
    add_grant(user_id, feature, int(n), int(days), reason, "system")


def consume_feature(user_id: str, feature: str, limit: int) -> bool:
    with conn() as c:
        c.execute("INSERT OR IGNORE INTO feature_usage(user_id,feature,used) VALUES(?,?,0)",
                  (user_id, feature))
        cur = c.execute(
            "UPDATE feature_usage SET used=used+1"
            " WHERE user_id=? AND feature=? AND used<?",
            (user_id, feature, limit),
        )
    return cur.rowcount > 0


def spend_credit(user_id: str) -> bool:
    get_plan(user_id)
    with conn() as c:
        cur = c.execute("UPDATE users SET credits=credits-1 WHERE id=? AND credits>0", (user_id,))
    return cur.rowcount > 0


def refund_credit(user_id: str) -> None:
    with conn() as c:
        c.execute("UPDATE users SET credits=credits+1 WHERE id=?", (user_id,))


def record_charge(task_id: str, user_id: str, feature: str, source: str) -> None:
    with conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO task_charges(task_id,user_id,feature,source) VALUES(?,?,?,?)",
            (task_id, user_id, feature, source),
        )


def refund_charge(task_id: str) -> None:
    with conn() as c:
        row = c.execute("SELECT * FROM task_charges WHERE task_id=?", (task_id,)).fetchone()
        if not row:
            return
        if row["source"] == "free":
            c.execute(
                "UPDATE feature_usage SET used=CASE WHEN used>0 THEN used-1 ELSE 0 END"
                " WHERE user_id=? AND feature=?",
                (row["user_id"], row["feature"]),
            )
        elif row["source"] == "credit":
            c.execute("UPDATE users SET credits=credits+1 WHERE id=?", (row["user_id"],))
        c.execute("DELETE FROM task_charges WHERE task_id=?", (task_id,))


def get_plan(user_id: str) -> dict:
    with conn() as c:
        row = c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if not row:
            c.execute("INSERT INTO users(id,plan,credits,created_at) VALUES(?,?,?,?)",
                      (user_id, "free", 0, now()))
            return {"id": user_id, "plan": "free", "credits": 0, "plan_until": None}
        data = dict(row)
        if data.get("plan_until") and data["plan_until"] < now():
            c.execute("UPDATE users SET plan='free', plan_until=NULL WHERE id=?", (user_id,))
            data["plan"] = "free"
            data["plan_until"] = None
    return data


def add_credits(user_id: str, delta: int, reason: str) -> int:
    get_plan(user_id)
    with conn() as c:
        c.execute("UPDATE users SET credits=credits+? WHERE id=?", (delta, user_id))
        c.execute("INSERT INTO credit_logs(user_id,delta,reason,created_at) VALUES(?,?,?,?)",
                  (user_id, delta, reason, now()))
        row = c.execute("SELECT credits FROM users WHERE id=?", (user_id,)).fetchone()
    return int(row["credits"] if row else 0)


def set_plan_until(user_id: str, plan: str, days: int) -> str:
    data = get_plan(user_id)
    base = datetime.now()
    current = data.get("plan_until")
    if current:
        try:
            parsed = datetime.strptime(current, "%Y-%m-%d %H:%M:%S")
            if parsed > base:
                base = parsed
        except ValueError:
            pass
    until = (base + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    rank = {"free": 0, "pro": 1, "team": 2, "enterprise": 3}
    current_plan = data.get("plan") or "free"
    if rank.get(current_plan, 0) > rank.get(plan, 0):
        plan = current_plan
    with conn() as c:
        c.execute("UPDATE users SET plan=?, plan_until=? WHERE id=?", (plan, until, user_id))
    return until


def create_order(order_id: str, user_id: str, product_id: str, amount_cent: int) -> dict:
    with conn() as c:
        c.execute(
            "INSERT INTO orders(id,user_id,product_id,amount_cent,status,created_at)"
            " VALUES(?,?,?,?,?,?)",
            (order_id, user_id, product_id, amount_cent, "pending", now()),
        )
        row = c.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    return dict(row)


def get_order(order_id: str) -> dict | None:
    with conn() as c:
        row = c.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    return dict(row) if row else None


def list_orders(user_id: str, limit: int = 20) -> list[dict]:
    with conn() as c:
        rows = c.execute("SELECT * FROM orders WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
                         (user_id, limit)).fetchall()
    return [dict(r) for r in rows]


def mark_order_paid(order_id: str, channel: str, txn: str = "") -> bool:
    with conn() as c:
        cur = c.execute(
            "UPDATE orders SET status='paid', channel=?, channel_txn=?, paid_at=?"
            " WHERE id=? AND status='pending'",
            (channel, txn, now(), order_id),
        )
    return cur.rowcount > 0


def create_redeem_code(code: str, product_id: str, max_uses: int = 1,
                       expires_at: str | None = None) -> None:
    with conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO redeem_codes(code,product_id,max_uses,used,expires_at,created_at)"
            " VALUES(?,?,?,0,?,?)",
            (code, product_id, max_uses, expires_at, now()),
        )


def redeem_code(code: str, user_id: str) -> str:
    code = (code or "").strip().upper()
    with conn() as c:
        row = c.execute("SELECT * FROM redeem_codes WHERE code=?", (code,)).fetchone()
        if not row:
            raise ValueError("CODE_NOT_FOUND")
        if row["expires_at"] and row["expires_at"] < now():
            raise ValueError("CODE_EXPIRED")
        used = c.execute("SELECT 1 FROM redeem_uses WHERE code=? AND user_id=?",
                         (code, user_id)).fetchone()
        if used:
            raise ValueError("CODE_USED")
        if int(row["used"]) >= int(row["max_uses"]):
            raise ValueError("CODE_EXHAUSTED")
        c.execute("UPDATE redeem_codes SET used=used+1 WHERE code=?", (code,))
        c.execute("INSERT INTO redeem_uses(code,user_id,created_at) VALUES(?,?,?)",
                  (code, user_id, now()))
    return row["product_id"]


def set_plan(user_id: str, plan: str) -> None:
    get_plan(user_id)
    with conn() as c:
        c.execute("UPDATE users SET plan=? WHERE id=?", (plan, user_id))


def feature_limit(feature: str, default: int) -> int:
    with conn() as c:
        row = c.execute("SELECT free_tries FROM feature_limits WHERE feature=?", (feature,)).fetchone()
    return int(row["free_tries"]) if row else int(default)


def set_feature_limit(feature: str, free_tries: int) -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO feature_limits(feature,free_tries,updated_at) VALUES(?,?,?)"
            " ON CONFLICT(feature) DO UPDATE SET free_tries=excluded.free_tries, updated_at=excluded.updated_at",
            (feature, max(0, int(free_tries)), now()),
        )


def active_grant_tries(user_id: str, feature: str) -> int:
    with conn() as c:
        row = c.execute(
            "SELECT COALESCE(SUM(extra_tries),0) AS n FROM feature_grants"
            " WHERE user_id=? AND feature=? AND (expires_at IS NULL OR expires_at>=?)",
            (user_id, feature, now()),
        ).fetchone()
    return int(row["n"] if row else 0)


def add_grant(user_id: str, feature: str, extra_tries: int, days: int,
              reason: str, created_by: str) -> dict:
    gid = uuid.uuid4().hex[:12]
    expires = None
    if days and days > 0:
        expires = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    with conn() as c:
        c.execute(
            "INSERT INTO feature_grants(id,user_id,feature,extra_tries,reason,created_by,created_at,expires_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (gid, user_id, feature, max(1, int(extra_tries)), reason, created_by, now(), expires),
        )
        row = c.execute("SELECT * FROM feature_grants WHERE id=?", (gid,)).fetchone()
    return dict(row)


def list_grants(user_id: str) -> list[dict]:
    with conn() as c:
        rows = c.execute("SELECT * FROM feature_grants WHERE user_id=? ORDER BY created_at DESC",
                         (user_id,)).fetchall()
    return [dict(r) for r in rows]


def audit(admin: str, action: str, target: str = "", detail: str = "") -> None:
    with conn() as c:
        c.execute("INSERT INTO admin_audit(admin,action,target,detail,created_at) VALUES(?,?,?,?,?)",
                  (admin, action, target, detail[:1000], now()))


def audit_list(limit: int = 50) -> list[dict]:
    with conn() as c:
        rows = c.execute("SELECT * FROM admin_audit ORDER BY id DESC LIMIT ?", (min(limit, 200),)).fetchall()
    return [dict(r) for r in rows]


def admin_overview() -> dict:
    today = datetime.now().strftime("%Y-%m-%d")
    with conn() as c:
        users = c.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
        tasks = c.execute("SELECT COUNT(*) AS n FROM tasks WHERE created_at LIKE ?", (today + "%",)).fetchone()["n"]
        done = c.execute("SELECT COUNT(*) AS n FROM tasks WHERE created_at LIKE ? AND status='done'", (today + "%",)).fetchone()["n"]
        failed = c.execute("SELECT COUNT(*) AS n FROM tasks WHERE created_at LIKE ? AND status='failed'", (today + "%",)).fetchone()["n"]
        paid = c.execute("SELECT COUNT(*) AS n, COALESCE(SUM(amount_cent),0) AS s FROM orders WHERE status='paid'").fetchone()
        credits = c.execute("SELECT COALESCE(SUM(credits),0) AS n FROM users").fetchone()["n"]
        keys = c.execute("SELECT COUNT(*) AS n FROM user_keys").fetchone()["n"]
        blocked = c.execute(
            "SELECT COUNT(*) AS n FROM tasks WHERE created_at LIKE ? "
            "AND error_code IN ('SEC_RISKY','CONTENT_RISKY')", (today + "%",),
        ).fetchone()["n"]
    with conn() as c:
        invited = c.execute("SELECT COUNT(*) AS n FROM invites").fetchone()["n"]
        invite_rewarded = c.execute(
            "SELECT COUNT(*) AS n FROM invites WHERE status='rewarded'").fetchone()["n"]
        ads = c.execute(
            "SELECT COUNT(*) AS n FROM ad_rewards WHERE status='done' "
            "AND created_at LIKE ?", (today + "%",)).fetchone()["n"]
    return {"users": int(users), "tasks_today": int(tasks), "done_today": int(done),
            "sec_blocked_today": int(blocked),
            "invites_total": int(invited), "invites_rewarded": int(invite_rewarded),
            "ad_rewards_today": int(ads),
            "failed_today": int(failed), "success_rate": round(done * 100.0 / tasks, 1) if tasks else 0.0,
            "paid_orders": int(paid["n"]), "revenue_cent": int(paid["s"]),
            "credits_outstanding": int(credits), "keys": int(keys)}


def admin_users(q: str = "", limit: int = 50) -> list[dict]:
    with conn() as c:
        if q:
            rows = c.execute(
                "SELECT * FROM users WHERE id LIKE ? ORDER BY created_at DESC LIMIT ?",
                ("%" + q + "%", min(limit, 200)),
            ).fetchall()
        else:
            rows = c.execute("SELECT * FROM users ORDER BY created_at DESC LIMIT ?",
                             (min(limit, 200),)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        with conn() as c:
            a = c.execute("SELECT used FROM feature_usage WHERE user_id=? AND feature='link_extract'", (d["id"],)).fetchone()
            b = c.execute("SELECT used FROM feature_usage WHERE user_id=? AND feature='audio_extract'", (d["id"],)).fetchone()
            d["used_link"] = int(a["used"]) if a else 0
            d["used_audio"] = int(b["used"]) if b else 0
        out.append(d)
    return out


def admin_user_detail(user_id: str) -> dict:
    plan = get_plan(user_id)
    with conn() as c:
        usage = [dict(r) for r in c.execute("SELECT * FROM feature_usage WHERE user_id=?", (user_id,)).fetchall()]
        orders = [dict(r) for r in c.execute("SELECT * FROM orders WHERE user_id=? ORDER BY created_at DESC LIMIT 20", (user_id,)).fetchall()]
        tasks = [dict(r) for r in c.execute("SELECT id,platform,title,status,created_at FROM tasks WHERE user_id=? ORDER BY created_at DESC LIMIT 20", (user_id,)).fetchall()]
        keys = [dict(r) for r in c.execute("SELECT id,kind,provider,hint,status,created_at,tested_at FROM user_keys WHERE user_id=?", (user_id,)).fetchall()]
    return {"plan": plan, "usage": usage, "orders": orders, "tasks": tasks,
            "keys": keys, "grants": list_grants(user_id)}


def admin_orders(limit: int = 50) -> list[dict]:
    with conn() as c:
        rows = c.execute("SELECT * FROM orders ORDER BY created_at DESC LIMIT ?", (min(limit, 200),)).fetchall()
    return [dict(r) for r in rows]


def admin_redeem_list(limit: int = 100) -> list[dict]:
    with conn() as c:
        rows = c.execute("SELECT * FROM redeem_codes ORDER BY created_at DESC LIMIT ?", (min(limit, 200),)).fetchall()
    return [dict(r) for r in rows]


def admin_user_role(user_id: str) -> str | None:
    if not user_id:
        return None
    with conn() as c:
        row = c.execute("SELECT role FROM admins WHERE user_id=?", (user_id,)).fetchone()
    return row["role"] if row else None


def admin_rows() -> list[dict]:
    with conn() as c:
        rows = c.execute("SELECT * FROM admins ORDER BY created_at ASC").fetchall()
    return [dict(r) for r in rows]


def add_admin(user_id: str, role: str = "admin", note: str = "",
              created_by: str = "") -> dict:
    user_id = (user_id or "").strip()
    if not user_id:
        raise ValueError("EMPTY_USER_ID")
    with conn() as c:
        c.execute(
            "INSERT INTO admins(user_id, role, note, created_by, created_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET role=excluded.role, note=excluded.note",
            (user_id, role, note, created_by, now()),
        )
        row = c.execute("SELECT * FROM admins WHERE user_id=?", (user_id,)).fetchone()
    return dict(row)


def remove_admin(user_id: str) -> bool:
    with conn() as c:
        cur = c.execute("DELETE FROM admins WHERE user_id=?", (user_id,))
        return cur.rowcount > 0


def admin_table_count() -> int:
    with conn() as c:
        return int(c.execute("SELECT COUNT(*) AS n FROM admins").fetchone()["n"])


def admin_recent_tasks(limit: int = 15) -> list[dict]:
    with conn() as c:
        rows = c.execute(
            "SELECT id, user_id, source_type, platform, title, status, error_code, "
            "created_at, finished_at FROM tasks ORDER BY created_at DESC LIMIT ?",
            (min(limit, 100),),
        ).fetchall()
    return [dict(r) for r in rows]


def admin_feature_stats() -> list[dict]:
    today = datetime.now().strftime("%Y-%m-%d")
    with conn() as c:
        rows = c.execute(
            "SELECT tc.feature AS feature, COUNT(*) AS n FROM task_charges tc "
            "JOIN tasks t ON t.id = tc.task_id WHERE t.created_at LIKE ? "
            "GROUP BY tc.feature", (today + "%",),
        ).fetchall()
    return [dict(r) for r in rows]


def admin_mobile() -> dict:
    return {
        "overview": admin_overview(),
        "recent_tasks": admin_recent_tasks(),
        "feature_today": admin_feature_stats(),
        "server_time": now(),
    }


def kv_get(key: str) -> str | None:
    with conn() as c:
        row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def kv_set(key: str, value: str) -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO settings(key,value,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, value, now()),
        )


def add_sec_check(trace_id: str, task_id: str, user_id: str, media_type: int) -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO sec_checks(trace_id,task_id,user_id,media_type,status,created_at) "
            "VALUES(?,?,?,?,'pending',?) ON CONFLICT(trace_id) DO NOTHING",
            (trace_id, task_id, user_id, media_type, now()),
        )


def get_sec_check(trace_id: str) -> dict | None:
    with conn() as c:
        row = c.execute("SELECT * FROM sec_checks WHERE trace_id=?", (trace_id,)).fetchone()
    return dict(row) if row else None


def block_task(task_id: str, code: str = "SEC_RISKY",
               msg: str = "内容未通过安全检测") -> bool:
    with conn() as c:
        row = c.execute("SELECT id FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            return False
        c.execute(
            "UPDATE tasks SET status='failed', error_code=?, error_msg=?, progress=100, "
            "finished_at=?, full_text=NULL, segments_json=NULL, structure_json=NULL WHERE id=?",
            (code, msg, now(), task_id),
        )
    refund_charge(task_id)
    return True


def finish_sec_check(trace_id: str, status: str) -> None:
    with conn() as c:
        c.execute("UPDATE sec_checks SET status=?, updated_at=? WHERE trace_id=?",
                  (status, now(), trace_id))


# ---------------- 增长：邀请 / 激励视频 ----------------

INVITE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def _make_invite_code(user_id: str) -> str:
    digest = hashlib.sha256(("invite:" + user_id).encode()).digest()
    return "".join(INVITE_ALPHABET[b % 32] for b in digest[:8])


def ensure_invite_code(user_id: str) -> str:
    get_plan(user_id)
    with conn() as c:
        row = c.execute("SELECT invite_code FROM users WHERE id=?", (user_id,)).fetchone()
        if row and row["invite_code"]:
            return row["invite_code"]
        code = _make_invite_code(user_id)
        try:
            c.execute(
                "UPDATE users SET invite_code=? WHERE id=? "
                "AND (invite_code IS NULL OR invite_code='')", (code, user_id))
        except sqlite3.IntegrityError:
            code = _make_invite_code(user_id + ":" + uuid.uuid4().hex[:6])
            c.execute(
                "UPDATE users SET invite_code=? WHERE id=? "
                "AND (invite_code IS NULL OR invite_code='')", (code, user_id))
        row = c.execute("SELECT invite_code FROM users WHERE id=?", (user_id,)).fetchone()
    return (row["invite_code"] if row else "") or code


def invite_stats(user_id: str) -> dict:
    code = ensure_invite_code(user_id)
    with conn() as c:
        invited = c.execute(
            "SELECT COUNT(*) AS n FROM invites WHERE inviter_id=?", (user_id,)).fetchone()["n"]
        rewarded = c.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(reward_days),0) AS d FROM invites "
            "WHERE inviter_id=? AND status='rewarded'", (user_id,)).fetchone()
    return {"code": code, "invited": int(invited),
            "rewarded": int(rewarded["n"]), "reward_days": int(rewarded["d"])}


def bind_invite(invitee_id: str, code: str) -> dict:
    code = (code or "").strip().upper()
    if not code:
        return {"ok": False, "code": "INVALID_CODE"}
    inviter = None
    with conn() as c:
        row = c.execute("SELECT id FROM users WHERE invite_code=?", (code,)).fetchone()
        inviter = row["id"] if row else None
    if not inviter:
        return {"ok": False, "code": "INVALID_CODE"}
    if inviter == invitee_id:
        return {"ok": False, "code": "SELF_INVITE"}
    data = get_plan(invitee_id)
    with conn() as c:
        exists = c.execute("SELECT inviter_id FROM invites WHERE invitee_id=?",
                           (invitee_id,)).fetchone()
        if exists:
            return {"ok": True, "already": True, "inviter_id": exists["inviter_id"]}
        try:
            created = datetime.strptime(data.get("created_at") or "", "%Y-%m-%d %H:%M:%S")
        except ValueError:
            created = datetime.now()
        if datetime.now() - created > timedelta(days=3):
            return {"ok": False, "code": "TOO_LATE"}
        cur = c.execute(
            "INSERT OR IGNORE INTO invites(invitee_id,inviter_id,code,status,created_at) "
            "VALUES(?,?,?,?,?)", (invitee_id, inviter, code, "bound", now()))
        if cur.rowcount <= 0:
            return {"ok": True, "already": True, "inviter_id": inviter}
        c.execute("UPDATE users SET invited_by=? WHERE id=?", (inviter, invitee_id))
    grant_feature(inviter, "link_extract", 3, reason="invite:" + invitee_id[:12])
    grant_feature(invitee_id, "link_extract", 3, reason="invited_by:" + inviter[:12])
    return {"ok": True, "already": False, "inviter_id": inviter, "reward_tries": 3}


def reward_inviter(invitee_id: str, days: int = 7) -> dict | None:
    """好友首次真实付费后，邀请人得会员天数；只发一次。"""
    with conn() as c:
        row = c.execute("SELECT * FROM invites WHERE invitee_id=?", (invitee_id,)).fetchone()
        if not row or row["status"] != "bound":
            return None
        cur = c.execute(
            "UPDATE invites SET status='rewarded', reward_days=?, rewarded_at=? "
            "WHERE invitee_id=? AND status='bound'", (int(days), now(), invitee_id))
        if cur.rowcount <= 0:
            return None
    until = set_plan_until(row["inviter_id"], "pro", int(days))
    return {"inviter_id": row["inviter_id"], "days": int(days), "plan_until": until}


def ad_reward_start(reward_id: str, user_id: str, token_id: str) -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO ad_rewards(id,user_id,token_id,status,created_at) "
            "VALUES(?,?,?,?,?)", (reward_id, user_id, token_id, "started", now()))


def ad_reward_get(reward_id: str, user_id: str) -> dict | None:
    with conn() as c:
        row = c.execute("SELECT * FROM ad_rewards WHERE id=? AND user_id=?",
                        (reward_id, user_id)).fetchone()
    return dict(row) if row else None


def ad_reward_finish(reward_id: str, user_id: str) -> bool:
    with conn() as c:
        cur = c.execute(
            "UPDATE ad_rewards SET status='done', finished_at=? "
            "WHERE id=? AND user_id=? AND status='started'", (now(), reward_id, user_id))
    return cur.rowcount > 0


def ad_reward_used_today(user_id: str) -> int:
    today = datetime.now().strftime("%Y-%m-%d")
    with conn() as c:
        row = c.execute(
            "SELECT COUNT(*) AS n FROM ad_rewards WHERE user_id=? AND status='done' "
            "AND created_at LIKE ?", (user_id, today + "%")).fetchone()
    return int(row["n"])


def admin_growth_overview() -> dict:
    today = datetime.now().strftime("%Y-%m-%d")
    with conn() as c:
        invited = c.execute("SELECT COUNT(*) AS n FROM invites").fetchone()["n"]
        rewarded = c.execute(
            "SELECT COUNT(*) AS n FROM invites WHERE status='rewarded'").fetchone()["n"]
        ads = c.execute(
            "SELECT COUNT(*) AS n FROM ad_rewards WHERE status='done' "
            "AND created_at LIKE ?", (today + "%",)).fetchone()["n"]
    return {"invites_total": int(invited), "invites_rewarded": int(rewarded),
            "ad_rewards_today": int(ads)}

