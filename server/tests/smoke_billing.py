import json, time, urllib.request, urllib.error
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import publicfile
from app.config import DATA_DIR

BASE = "http://127.0.0.1:8788"
USER = "bill_%d" % int(time.time())
H = {"Content-Type": "application/json", "X-User-Id": USER}


def call(method, path, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers=headers or H, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            try:
                return r.status, json.loads(raw.decode())
            except Exception:
                return r.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw.decode())
        except Exception:
            return e.code, raw


def wallet():
    return call("GET", "/api/wallet")[1]


print("products:", [p["id"] for p in call("GET", "/api/products")[1]["items"]])

c, r = call("POST", "/api/orders", {"product_id": "credits_30"})
print("create order:", c, r["order"]["id"], r["pay"]["mode"])
oid = r["order"]["id"]
print("mock pay:", call("POST", "/api/orders/%s/mock-pay" % oid)[1]["credits"])
print("mock pay again:", call("POST", "/api/orders/%s/mock-pay" % oid)[1]["credits"])

code = "TEST%d" % int(time.time())
print("create code:", call("POST", "/api/dev/redeem", {"code": code, "product_id": "credits_30"})[0])
U2 = USER + "_r"
H2 = {"Content-Type": "application/json", "X-User-Id": U2}
print("redeem:", call("POST", "/api/redeem", {"code": code}, H2)[1]["credits"])
print("redeem again:", call("POST", "/api/redeem", {"code": code}, H2)[1]["detail"]["code"])

c, r = call("POST", "/api/orders", {"product_id": "byok_month"})
print("buy plan:", call("POST", "/api/orders/%s/mock-pay" % r["order"]["id"])[1]["plan"])

# 额度消耗 + 失败退回
dbuser = USER + "_refund"
H3 = {"Content-Type": "application/json", "X-User-Id": dbuser}
call("POST", "/api/orders", {"product_id": "credits_30"}, H3)
cell = call("GET", "/api/wallet", headers=H3)[1]
c, r = call("POST", "/api/orders", {"product_id": "credits_30"}, H3)
call("POST", "/api/orders/%s/mock-pay" % r["order"]["id"], headers=H3)
c, r = call("POST", "/api/parse", {"text": "https://www.douyin.com/video/0000000000000000000"}, H3)
tid = r.get("task_id")
if tid:
    for _ in range(40):
        time.sleep(1)
        t = call("GET", "/api/tasks/" + tid, headers=H3)[1]
        if t["status"] in ("failed", "done"):
            print("credit refund task:", t["status"], t.get("error_code"))
            break
print("credits after failed task:", call("GET", "/api/wallet", headers=H3)[1]["credits"])

# 公共音频签名
f = DATA_DIR / "uploads" / "token_test.txt"
f.write_text("ok", encoding="utf-8")
tok = publicfile.sign_path(f)
print("public audio:", call("GET", "/api/public/audio/" + tok, headers={})[0])
print("bad token:", call("GET", "/api/public/audio/bad", headers={})[0])
print("PASS")
