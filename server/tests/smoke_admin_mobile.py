import json, time, urllib.request, urllib.error

BASE = "http://127.0.0.1:8788"
OWNER = "demo"
CO = "co_%d" % int(time.time())


def call(method, path, body=None, user=None, token=""):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if user:
        headers["X-User-Id"] = user
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw.decode())
        except Exception:
            return e.code, raw.decode(errors="replace")


c, me = call("GET", "/api/admin/me", user=OWNER)
print("owner me:", c, me["is_admin"], me["role"])
assert c == 200 and me["is_admin"] and me["role"] == "owner"

c, _ = call("GET", "/api/admin/mobile")
print("mobile no identity:", c)
assert c == 401

c, _ = call("GET", "/api/admin/mobile", user="nobody_%d" % int(time.time()))
print("mobile stranger:", c)
assert c == 401

c, mob = call("GET", "/api/admin/mobile", user=OWNER)
print("mobile owner:", c, "features:", len(mob["features"]), "today:", mob["overview"]["tasks_today"])
assert c == 200 and len(mob["features"]) == 4
assert all("free_tries" in f for f in mob["features"])

c, r = call("POST", "/api/admin/config", {"feature": "video_extract", "free_tries": 3}, user=OWNER)
print("config via identity:", c, r.get("free_tries"))
assert c == 200 and r["free_tries"] == 3
call("POST", "/api/admin/config", {"feature": "video_extract", "free_tries": 2}, user=OWNER)

c, r = call("POST", "/api/admin/admins", {"user_id": CO, "note": "test"}, user=OWNER)
print("add co-admin:", c)
assert c == 200
c, me2 = call("GET", "/api/admin/me", user=CO)
print("co-admin me:", c, me2["is_admin"], me2["role"])
assert c == 200 and me2["is_admin"] and me2["role"] == "admin"
c, _ = call("GET", "/api/admin/mobile", user=CO)
print("co-admin mobile:", c)
assert c == 200

c, r = call("DELETE", "/api/admin/admins/" + CO, user=OWNER)
print("remove co-admin:", c)
assert c == 200
c, me3 = call("GET", "/api/admin/me", user=CO)
print("after remove:", c, me3["is_admin"])
assert me3["is_admin"] is False

c, r = call("POST", "/api/admin/app-token", user=OWNER)
print("app token:", c, "len:", len(r.get("token", "")))
assert c == 200 and len(r["token"]) > 20
c, me4 = call("GET", "/api/admin/me", token=r["token"])
print("bearer me:", c, me4["is_admin"])
assert c == 200 and me4["is_admin"]

c, audit = call("GET", "/api/admin/audit", user=OWNER)
actions = [x["action"] for x in audit["items"]]
print("audit has:", "add_admin" in actions, "remove_admin" in actions)
assert "add_admin" in actions and "remove_admin" in actions

c, admins = call("GET", "/api/admin/admins", user=OWNER)
envs = [a for a in admins["items"] if a["source"] == "env"]
print("env owners:", [a["user_id"] for a in envs])
assert any(a["user_id"] == OWNER for a in envs)

print("ADMIN_MOBILE_PASS")
