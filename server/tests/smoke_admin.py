import json, time, urllib.request, urllib.error

BASE = "http://127.0.0.1:8788"
USER = "adm_%d" % int(time.time())


def call(method, path, body=None, token=""):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            try:
                return r.status, json.loads(raw.decode())
            except Exception:
                return r.status, raw.decode(errors="replace")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw.decode())
        except Exception:
            return e.code, raw.decode(errors="replace")


print("page:", call("GET", "/admin")[0])
print("wrong pwd:", call("POST", "/api/admin/login", {"password": "bad"})[0])
c, r = call("POST", "/api/admin/login", {"password": "admin123"})
print("login:", c)
token = r["token"]
print("overview:", call("GET", "/api/admin/overview", token=token)[0])
c, cfg = call("GET", "/api/admin/config", token=token)
print("config items:", len(cfg["items"]))

call("POST", "/api/admin/config", {"feature": "audio_extract", "free_tries": 1}, token)
H = {"Content-Type": "application/json", "X-User-Id": USER}
def user_call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers=H, method=method)
    with urllib.request.urlopen(req, timeout=20) as x:
        return json.loads(x.read().decode())
audio = [i for i in user_call("GET", "/api/features")["items"] if i["feature"] == "audio_extract"][0]
print("audio free after config:", audio["free"])

call("POST", "/api/admin/grants", {"user_id": USER, "feature": "audio_extract", "extra_tries": 3, "days": 7, "reason": "test"}, token)
audio = [i for i in user_call("GET", "/api/features")["items"] if i["feature"] == "audio_extract"][0]
print("audio free after grant:", audio["free"], "granted:", audio["granted"])

print("add credits:", call("POST", "/api/admin/credits", {"user_id": USER, "amount": 30, "reason": "test"}, token)[1]["credits"])
print("plan:", call("POST", "/api/admin/plan", {"user_id": USER, "plan": "pro", "days": 30}, token)[1]["plan"])

code = "ADM%d" % int(time.time())
print("create redeem:", call("POST", "/api/admin/redeem", {"code": code, "product_id": "credits_30", "max_uses": 1, "days": 7}, token)[0])
print("redeem:", user_call("POST", "/api/redeem", {"code": code})["credits"])

c, audit = call("GET", "/api/admin/audit", token=token)
actions = [x["action"] for x in audit["items"]]
print("audit actions:", sorted(set(actions)))
assert "set_limit" in actions and "grant" in actions and "credits" in actions and "plan" in actions and "redeem_create" in actions

call("POST", "/api/admin/config", {"feature": "audio_extract", "free_tries": 2}, token)
print("ADMIN_PASS")
