import io
import json
import struct
import time
import urllib.request
import urllib.error
import wave

BASE = "http://127.0.0.1:8788"
A = "auth_a_%d" % int(time.time())
B = "auth_b_%d" % int(time.time())


def call(method, path, body=None, token="", user=None, raw=None, ctype=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    headers = {}
    if ctype:
        headers["Content-Type"] = ctype
    elif body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    if user:
        headers["X-User-Id"] = user
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            payload = r.read()
            try:
                return r.status, json.loads(payload.decode())
            except Exception:
                return r.status, payload.decode(errors="replace")
    except urllib.error.HTTPError as e:
        payload = e.read()
        try:
            return e.code, json.loads(payload.decode())
        except Exception:
            return e.code, payload.decode(errors="replace")


def login(uid):
    c, r = call("POST", "/api/dev/login", {"user_id": uid})
    assert c == 200, (c, r)
    return r["token"]


ta = login(A)
tb = login(B)
print("dev login A/B ok, token len:", len(ta), len(tb))

c, q = call("GET", "/api/quota", token=ta)
print("quota with token:", c, q["left"])
assert c == 200

c, _ = call("GET", "/api/quota")
print("quota without token:", c)
assert c == 401

c, _ = call("GET", "/api/quota", token="bad.token")
print("quota bad token:", c)
assert c == 401

c, me = call("GET", "/api/auth/me", token=ta)
print("auth/me:", c, me["user_id"] == A, "dev:", me["dev"])
assert c == 200 and me["user_id"] == A

ta_demo = login("demo")
c, _ = call("GET", "/api/admin/mobile", token=ta_demo)
print("admin mobile with user token(demo):", c)
assert c == 200
c, _ = call("GET", "/api/admin/mobile", token=ta)
print("admin mobile with stranger token:", c)
assert c == 401

buf = io.BytesIO()
with wave.open(buf, "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(16000)
    w.writeframes(b"\x00\x00" * 3200)
wav = buf.getvalue()
boundary = "----lqd%d" % int(time.time())
parts = (
    "--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a.wav\"\r\n"
    "Content-Type: audio/wav\r\n\r\n" % boundary
).encode() + wav + ("\r\n--%s--\r\n" % boundary).encode()

c, up = call("POST", "/api/upload/simple", raw=parts, token=ta,
             ctype="multipart/form-data; boundary=" + boundary)
print("upload as A:", c, up.get("task_id"))
assert c == 200
tid = up["task_id"]

c, _ = call("GET", "/api/tasks/" + tid, token=tb)
print("read A task as B:", c)
assert c == 404
c, t = call("GET", "/api/tasks/" + tid, token=ta)
print("read A task as A:", c, t.get("status"))
assert c == 200

c, me_admin = call("GET", "/api/admin/me", token=ta_demo)
print("admin/me demo token:", c, me_admin.get("is_admin"))
assert c == 200 and me_admin["is_admin"] is True
c, me_a = call("GET", "/api/admin/me", token=ta)
print("admin/me stranger token:", c, me_a.get("is_admin"))
assert c == 200 and me_a["is_admin"] is False
c, at = call("POST", "/api/admin/app-token", token=ta_demo)
print("app-token with demo user token:", c, len(at.get("token", "")))
assert c == 200
c, _ = call("POST", "/api/admin/app-token", token=ta)
print("app-token with stranger token:", c)
assert c == 401

c, r = call("POST", "/api/auth/wechat", {"code": "fake", "platform": "mp"})
print("wechat login without config:", c, r.get("detail", {}).get("code"))
assert c == 503

print("AUTH_PASS")
