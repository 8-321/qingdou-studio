import json, os, sys, time, urllib.request

BASE = "http://127.0.0.1:8788"
HEAD = {"X-User-Id": "smokemedia_%d" % int(time.time())}

def call(method, path, body=None, ctype="application/json", raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    h = dict(HEAD)
    if data is not None:
        h["Content-Type"] = ctype
    req = urllib.request.Request(BASE + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())

def poll(tid, limit=300):
    for _ in range(limit):
        code, t = call("GET", "/api/tasks/" + tid)
        if t["status"] in ("done", "failed"):
            return t
        time.sleep(0.5)
    return t

def upload_test():
    path = "tests/fixtures/demo.mp3"
    if not os.path.exists(path):
        os.system("ffmpeg -v error -f lavfi -i sine=frequency=440:duration=3 -q:a 9 -y " + path)
    size = os.path.getsize(path)
    code, s = call("POST", "/api/upload/init", {"filename": "demo.mp3", "size": size})
    print("init:", code, s)
    if code != 200:
        return False
    uid = s["upload_id"]
    offset = 0
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 32)
            if not chunk:
                break
            code, r = call("PUT", "/api/upload/%s/chunk?offset=%d" % (uid, offset),
                           raw=chunk, ctype="application/octet-stream")
            if code != 200:
                print("chunk fail:", code, r); return False
            offset = r["offset"]
    print("uploaded bytes:", offset)
    code, c = call("POST", "/api/upload/%s/complete" % uid)
    print("complete:", code, c)
    if code != 200:
        return False
    t = poll(c["task_id"])
    print("upload task:", t["status"], t["progress"], t.get("error_code"))
    return t["status"] == "done"

def link_test(url):
    code, b = call("POST", "/api/parse", {"text": url})
    print("parse:", code, b)
    if code != 200:
        return False
    t = poll(b["task_id"])
    print("link task:", t["status"], t["progress"], t.get("title"), t.get("error_code"))
    if t["status"] != "done":
        return False
    code, r = call("GET", "/api/tasks/" + b["task_id"] + "/result")
    print("result:", code, "segments:", len(r.get("segments", [])), "chars:", len(r.get("full_text", "")))
    return code == 200

ok1 = upload_test()
ok2 = link_test(sys.argv[1]) if len(sys.argv) > 1 else True
print("UPLOAD_PASS" if ok1 else "UPLOAD_FAIL")
print("LINK_PASS" if ok2 else "LINK_FAIL")
