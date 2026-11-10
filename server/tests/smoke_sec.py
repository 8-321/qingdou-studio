"""内容安全（msgSecCheck）端到端冒烟：文本拦截不扣次数 / 转写后拦截退次数 / 回调拦截 / 回调鉴权。"""
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = "http://127.0.0.1:8788"
FIX_PORT = 8791
os.chdir(Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(Path.cwd()))

ARTICLE = "http://127.0.0.1:%d/sample_article.html" % FIX_PORT
PY = sys.executable
results = []


def call(method, path, body=None, base=BASE, user=None):
    head = {"Content-Type": "application/json", "X-User-Id": user or "sec_probe"}
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, headers=head, method=method)
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {"raw": e.read().decode(errors="ignore")}


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (" | " + detail if detail else ""))


def wait_health(base, timeout=45):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            code, body = call("GET", "/api/health", base=base)
            if code == 200:
                return body
        except Exception:
            pass
        time.sleep(0.5)
    return {}


def start_instance(port, extra_env):
    env = os.environ.copy()
    env.update({
        "DEV_MODE": "1", "MOCK_ASR": "1", "FREE_DAILY_QUOTA": "50",
        "ADMIN_PASSWORD": "admin123", "ADMIN_SECRET": "local-admin-secret",
        "ADMIN_USER_IDS": "demo", "PUBLIC_BASE_URL": "http://127.0.0.1:%d" % port,
    })
    env.update(extra_env)
    code = ("import uvicorn; uvicorn.run('app.main:app', host='127.0.0.1', port=%d, "
            "log_level='warning')" % port)
    p = subprocess.Popen([PY, "-c", code], cwd=str(Path.cwd()), env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    wait_health("http://127.0.0.1:%d" % port)
    return p


def stop(p):
    try:
        p.terminate()
        p.wait(timeout=10)
    except Exception:
        try:
            p.kill()
        except Exception:
            pass


def feature_used(base, user, feature):
    code, body = call("GET", "/api/features", base=base, user=user)
    for item in body.get("items", []):
        if item["feature"] == feature:
            return item["used"], item["left"]
    return None, None


def poll(base, user, tid, limit=120):
    last = {}
    for _ in range(limit):
        code, last = call("GET", "/api/tasks/" + tid, base=base, user=user)
        if last.get("status") in ("done", "failed", "deleted"):
            return last
        time.sleep(0.3)
    return last


def main():
    handler = partial(SimpleHTTPRequestHandler, directory=str(Path.cwd() / "tests" / "fixtures"))
    fix = ThreadingHTTPServer(("127.0.0.1", FIX_PORT), handler)
    threading.Thread(target=fix.serve_forever, daemon=True).start()

    # ---------- A. 未配置：off ----------
    wait_health(BASE)
    code, hp = call("GET", "/api/health")
    check("A1 未配置时 sec_check=off", code == 200 and hp.get("sec_check") == "off", str(hp.get("sec_check")))
    user_off = "sec_off_%d" % int(time.time())
    code, body = call("POST", "/api/parse", {"text": ARTICLE, "platform": "wechat_article"}, user=user_off)
    check("A2 off 模式正常解析", code == 200, "%s %s" % (code, body.get("task_id")))
    if code == 200:
        task = poll(BASE, user_off, body["task_id"])
        check("A3 off 模式任务完成", task.get("status") == "done", str(task.get("status")))

    # ---------- B. enforce + SEC_MOCK=risky ----------
    p2 = start_instance(8792, {"SEC_CHECK": "enforce", "SEC_MOCK": "risky",
                               "SEC_CALLBACK_TOKEN": "test-sec-key"})
    b2 = "http://127.0.0.1:8792"
    try:
        code, hp = call("GET", "/api/health", base=b2)
        check("B1 enforce 生效", hp.get("sec_check") == "enforce", str(hp.get("sec_check")))

        user = "sec_risky_%d" % int(time.time())
        before, left_before = feature_used(b2, user, "article_extract")
        code, body = call("POST", "/api/parse", {"text": ARTICLE, "platform": "wechat_article"}, base=b2, user=user)
        d = body.get("detail") or {}
        check("B2 解析入口拦截", code == 400 and d.get("code") == "CONTENT_RISKY", "%s %s" % (code, d.get("code")))
        after, left_after = feature_used(b2, user, "article_extract")
        check("B3 拦截不扣次数", before == after == 0 and left_after == 2,
              "used %s->%s left %s" % (before, after, left_after))

        # 上传音频：机审 mock 跳过 -> 转写 -> 文本拦截 -> 失败并退次数
        demo = Path("tests/fixtures/demo.mp3")
        if not demo.exists():
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                            "sine=frequency=440:duration=3", "-q:a", "9", "-y", str(demo)], check=False)
        raw = demo.read_bytes()
        boundary = "----sec" + uuid.uuid4().hex
        payload = (("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"demo.mp3\"\r\n"
                    "Content-Type: audio/mpeg\r\n\r\n") % boundary).encode() + raw + ("\r\n--%s--\r\n" % boundary).encode()
        req = urllib.request.Request(b2 + "/api/upload/simple", data=payload, method="POST",
                                     headers={"Content-Type": "multipart/form-data; boundary=" + boundary,
                                              "X-User-Id": user})
        with urllib.request.urlopen(req, timeout=60) as r:
            up = json.loads(r.read().decode())
        task = poll(b2, user, up["task_id"])
        check("B4 转写后文本拦截", task.get("status") == "failed" and task.get("error_code") == "CONTENT_RISKY",
              "%s %s" % (task.get("status"), task.get("error_code")))
        used, left = feature_used(b2, user, "audio_extract")
        check("B5 失败自动退次数", used == 0 and left == 2, "used=%s left=%s" % (used, left))
        code, res = call("GET", "/api/tasks/%s/result" % up["task_id"], base=b2, user=user)
        check("B6 拦截任务无全文", code == 409 and res.get("detail", {}).get("code") == "TASK_FAILED",
              "%s %s" % (code, res.get("detail", {}).get("code")))

        # ---------- C. 媒体机审回调拦截 ----------
        from app import db
        cb_user = "sec_cb_%d" % int(time.time())
        db.consume_feature(cb_user, "audio_extract", 2)
        check("C1 模拟已扣 1 次", feature_used(b2, cb_user, "audio_extract")[0] == 1)
        tid = "seccb" + uuid.uuid4().hex[:10]
        db.create_task(tid, cb_user, "upload", "upload", "tests/fixtures/demo.mp3", "demo.mp3")
        db.record_charge(tid, cb_user, "audio_extract", "free")
        code, cb = call("POST", "/api/dev/sec-callback", {"task_id": tid, "suggest": "risky"}, base=b2)
        row = db.get_task(tid)
        check("C2 回调 risky 置失败", code == 200 and cb.get("suggest") == "risky"
              and row["status"] == "failed" and row["error_code"] == "SEC_RISKY",
              "%s %s" % (row["status"], row["error_code"]))
        used, _ = feature_used(b2, cb_user, "audio_extract")
        check("C3 回调拦截退次数", used == 0, "used=%s" % used)
        check("C4 回调清空全文", not row.get("full_text") and not row.get("segments_json"))

        code, cb = call("POST", "/api/dev/sec-callback", {"task_id": tid, "suggest": "pass"}, base=b2)
        row = db.get_task(tid)
        check("C5 重复回调不二次退款", feature_used(b2, cb_user, "audio_extract")[0] == 0)

        # ---------- D. 正式回调鉴权 ----------
        code, body = call("POST", "/api/sec/callback?k=wrong-key",
                          {"trace_id": "whatever", "result": {"suggest": "pass"}}, base=b2)
        check("D1 错误 key 401", code == 401, str(code))
        code, body = call("POST", "/api/sec/callback?k=test-sec-key",
                          {"trace_id": "no-such-trace", "result": {"suggest": "pass"}}, base=b2)
        check("D2 正确 key 可进入（未知 trace 返回 false）", code == 200 and body.get("ok") is False, str(body))
    finally:
        stop(p2)

    # ---------- E. enforce + SEC_MOCK=pass ----------
    p3 = start_instance(8793, {"SEC_CHECK": "enforce", "SEC_MOCK": "pass",
                               "SEC_CALLBACK_TOKEN": "test-sec-key"})
    b3 = "http://127.0.0.1:8793"
    try:
        user = "sec_pass_%d" % int(time.time())
        code, body = call("POST", "/api/parse", {"text": ARTICLE, "platform": "wechat_article"}, base=b3, user=user)
        check("E1 pass 模式放行", code == 200, str(code))
        if code == 200:
            task = poll(b3, user, body["task_id"])
            check("E2 pass 模式任务完成", task.get("status") == "done", str(task.get("status")))
            used, left = feature_used(b3, user, "article_extract")
            check("E3 pass 模式正常计次", used == 1 and left == 1, "used=%s left=%s" % (used, left))
    finally:
        stop(p3)
        fix.shutdown()

    bad = [r for r in results if not r[1]]
    print("-" * 48)
    print("SEC_PASS" if not bad else "SEC_FAIL %d/%d" % (len(bad), len(results)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
