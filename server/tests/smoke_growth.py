"""邀请 + 激励视频端到端冒烟。"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8788"
AD_BASE = "http://127.0.0.1:8794"
os.chdir(Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(Path.cwd()))
from app import db

results = []
STAMP = int(time.time())


def call(method, path, body=None, base=BASE, user=None, token=None):
    head = {"Content-Type": "application/json"}
    if token:
        head["Authorization"] = "Bearer " + token
    elif user:
        head["X-User-Id"] = user
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, headers=head, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {"raw": e.read().decode(errors="ignore")}


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (" | " + detail if detail else ""))


def feature(base, user, name):
    code, body = call("GET", "/api/features", base=base, user=user)
    for it in body.get("items", []):
        if it["feature"] == name:
            return it
    return {}


def wait_health(base, timeout=40):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if call("GET", "/api/health", base=base)[0] == 200:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def main():
    wait_health(BASE)
    inviter = "inviter_%d" % STAMP
    invitee = "invitee_%d" % STAMP

    code, info = call("GET", "/api/invite", user=inviter)
    check("G1 拿到邀请码", code == 200 and len(info.get("code", "")) == 8, str(info.get("code")))
    inv_code = info["code"]

    code, r = call("POST", "/api/invite/bind", {"code": inv_code}, user=invitee)
    check("G2 好友绑定成功", code == 200 and r.get("reward_tries") == 3, str(r))
    f1 = feature(BASE, inviter, "link_extract")
    f2 = feature(BASE, invitee, "link_extract")
    check("G3 双方各 +3 次", f1.get("free") == 5 and f2.get("free") == 5,
          "inviter free=%s invitee free=%s" % (f1.get("free"), f2.get("free")))

    code, r = call("POST", "/api/invite/bind", {"code": inv_code}, user=invitee)
    check("G4 重复绑定幂等", code == 200 and r.get("already") is True, str(r))
    check("G5 不重复发奖", feature(BASE, invitee, "link_extract").get("free") == 5)

    code, r = call("POST", "/api/invite/bind", {"code": inv_code}, user=inviter)
    check("G6 不能绑自己", code == 400 and (r.get("detail") or {}).get("code") == "SELF_INVITE",
          "%s %s" % (code, (r.get("detail") or {}).get("code")))
    code, r = call("POST", "/api/invite/bind", {"code": "ZZZZZZZZ"}, user="nobody_%d" % STAMP)
    check("G7 无效码拒绝", code == 400 and (r.get("detail") or {}).get("code") == "INVALID_CODE")

    # 好友首次付费 -> 邀请人 +7 天会员
    code, order = call("POST", "/api/orders", {"product_id": "credits_30"}, user=invitee)
    check("G8 好友下单", code == 200, str(code))
    code, paid = call("POST", "/api/orders/%s/mock-pay" % order["order"]["id"], {}, user=invitee)
    check("G9 模拟支付", code == 200, str(code))
    code, wallet = call("GET", "/api/wallet", user=inviter)
    check("G10 邀请人得 7 天会员", wallet.get("plan") == "pro" and wallet.get("plan_until"),
          "%s %s" % (wallet.get("plan"), wallet.get("plan_until")))
    code, inv = call("GET", "/api/invite", user=inviter)
    check("G11 邀请统计更新", inv.get("invited") == 1 and inv.get("rewarded") == 1
          and inv.get("reward_days") == 7, str(inv))

    # ---------- 签到连续 7 天 ----------
    signer = "signer_%d" % STAMP
    with db.conn() as c:
        for i in range(1, 7):
            day = time.strftime("%Y-%m-%d", time.localtime(time.time() - i * 86400))
            c.execute("INSERT OR IGNORE INTO signins(user_id,day) VALUES(?,?)", (signer, day))
    code, r = call("POST", "/api/signin", {}, user=signer)
    check("S1 连续 7 天签到", code == 200 and r.get("streak") == 7 and r.get("bonus") == 5, str(r))
    check("S2 第 7 天共得 6 次", feature(BASE, signer, "link_extract").get("free") == 8,
          "free=%s" % feature(BASE, signer, "link_extract").get("free"))
    code, r = call("POST", "/api/signin", {}, user=signer)
    check("S3 当天不能重复签", code == 409, str(code))

    # ---------- 激励视频（独立实例，开广告位） ----------
    env = os.environ.copy()
    env.update({"DEV_MODE": "1", "MOCK_ASR": "1", "AD_UNIT_ID": "adunit-test",
                "AD_MIN_SECONDS": "15", "ADMIN_PASSWORD": "admin123",
                "ADMIN_SECRET": "local-admin-secret", "ADMIN_USER_IDS": "demo",
                "PUBLIC_BASE_URL": AD_BASE})
    proc = subprocess.Popen([sys.executable, "-c",
                             "import uvicorn; uvicorn.run('app.main:app', host='127.0.0.1', port=8794, log_level='warning')"],
                            cwd=str(Path.cwd()), env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_health(AD_BASE)
        viewer = "adviewer_%d" % STAMP
        code, st = call("GET", "/api/rewards", base=AD_BASE, user=viewer)
        check("A1 奖励状态", code == 200 and st.get("enabled") is True and st.get("left_today") == 5, str(st))

        code, start = call("POST", "/api/rewards/ad/start", {}, base=AD_BASE, user=viewer)
        check("A2 开始观看签发 token", code == 200 and start.get("token"), str(code))
        code, r = call("POST", "/api/rewards/ad/finish", {"token": start["token"]}, base=AD_BASE, user=viewer)
        check("A3 秒领被拒", code == 400 and (r.get("detail") or {}).get("code") == "AD_TOO_SHORT",
              "%s %s" % (code, (r.get("detail") or {}).get("code")))

        rid = start["reward_id"]
        with db.conn() as c:
            c.execute("UPDATE ad_rewards SET created_at=? WHERE id=?",
                      (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - 30)), rid))
        code, r = call("POST", "/api/rewards/ad/finish", {"token": start["token"]}, base=AD_BASE, user=viewer)
        check("A4 看完领到 1 次", code == 200 and r.get("added") == 1 and r.get("left_today") == 4, str(r))
        check("A5 次数进入额度", feature(AD_BASE, viewer, "link_extract").get("free") == 3,
              "free=%s" % feature(AD_BASE, viewer, "link_extract").get("free"))
        code, r = call("POST", "/api/rewards/ad/finish", {"token": start["token"]}, base=AD_BASE, user=viewer)
        check("A6 同一 token 不能重复领", code == 409, str(code))

        for i in range(4):
            code, s2 = call("POST", "/api/rewards/ad/start", {}, base=AD_BASE, user=viewer)
            with db.conn() as c:
                c.execute("UPDATE ad_rewards SET created_at=? WHERE id=?",
                          (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - 30)), s2["reward_id"]))
            call("POST", "/api/rewards/ad/finish", {"token": s2["token"]}, base=AD_BASE, user=viewer)
        code, st = call("GET", "/api/rewards", base=AD_BASE, user=viewer)
        check("A7 每日上限 5 次", st.get("used_today") == 5 and st.get("left_today") == 0, str(st))
        code, r = call("POST", "/api/rewards/ad/start", {}, base=AD_BASE, user=viewer)
        check("A8 超上限 429", code == 429, str(code))

        code, tok = call("POST", "/api/admin/login", {"password": "admin123"}, base=AD_BASE)
        admin_token = tok.get("token")
        code, over = call("GET", "/api/admin/overview", base=AD_BASE, token=admin_token)
        check("A9 后台可见邀请/视频数", over.get("invites_total", 0) >= 1 and over.get("ad_rewards_today", 0) >= 5,
              "invites=%s ads=%s" % (over.get("invites_total"), over.get("ad_rewards_today")))
        code, g = call("POST", "/api/admin/growth", {"ad_reward_daily": 7}, base=AD_BASE, token=admin_token)
        check("A10 后台改每日上限", code == 200 and g.get("ad_reward_daily") == 7, str(g))
        code, st = call("GET", "/api/rewards", base=AD_BASE, user=viewer)
        check("A11 改完立即生效", st.get("daily_limit") == 7 and st.get("left_today") == 2, str(st))
        call("POST", "/api/admin/growth", {"ad_reward_daily": 5}, base=AD_BASE, token=admin_token)
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:
            proc.kill()

    bad = [r for r in results if not r[1]]
    print("-" * 48)
    print("GROWTH_PASS" if not bad else "GROWTH_FAIL %d/%d" % (len(bad), len(results)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
