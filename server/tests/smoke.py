import json, sys, time, urllib.request

BASE = "http://127.0.0.1:8788"
USER = "smoke_%d" % int(time.time())
HEAD = {"Content-Type": "application/json", "X-User-Id": USER}

def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers=HEAD, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())

def main():
    code, hp = call("GET", "/api/health")
    print("health:", code, "ytdlp:", hp["ytdlp"])
    code, qu = call("GET", "/api/quota")
    print("quota:", code, qu)
    code, body = call("POST", "/api/parse", {
        "text": "http://127.0.0.1:8791/sample_article.html",
        "platform": "wechat_article",
    })
    print("parse:", code, body)
    if code != 200:
        sys.exit(1)
    tid = body["task_id"]
    for _ in range(40):
        code, t = call("GET", "/api/tasks/" + tid)
        print("task:", t["status"], t["progress"], t.get("stage"))
        if t["status"] in ("done", "failed"):
            break
        time.sleep(0.4)
    code, r = call("GET", "/api/tasks/" + tid + "/result")
    print("result:", code)
    if code != 200:
        sys.exit(1)
    print("title:", r["title"])
    print("segments:", len(r["segments"]))
    print("score:", r["structure"]["score"])
    print("hook:", r["structure"]["sections"][0]["text"][:40])
    print("full_text_chars:", len(r["full_text"]))
    print("PASS")

main()
