"""二创接口冒烟：模板版 / 缓存 / 风格差异 / BYOK LLM / LLM 失败回退。"""
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = "http://127.0.0.1:8788"
LLM_BASE = "http://127.0.0.1:8796"
ARTICLE = "http://127.0.0.1:8791/sample_article.html"
results = []
STAMP = int(time.time())

LLM_PAYLOAD = {"versions": [
    {"title": "版本一 · 反常识开场", "text": "如果你拍了100条还是在300播放，先别改封面。问题不在内容，在开头三秒。\\n我用20条样本测过，完播率的差距全在前三句。"},
    {"title": "版本二 · 失败复盘", "text": "我以前也以为是自己不够努力，直到把每条视频的前三秒逐字拆开。\\n真正决定播放的，是第一句话有没有圈住人。"},
    {"title": "版本三 · 清单体", "text": "三件事，立刻改：一，第一句说结果；二，第二句说代价；三，第三句才解释。\\n照这个顺序拍三条，再看数据。"},
]}


class Handler(BaseHTTPRequestHandler):
    fail = False

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(n)
        if Handler.fail:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b'{"error":"boom"}')
            return
        body = json.dumps({"choices": [{"message": {"content": json.dumps(LLM_PAYLOAD, ensure_ascii=False)}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def call(method, path, body=None, base=BASE, user=None):
    head = {"Content-Type": "application/json"}
    if user:
        head["X-User-Id"] = user
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


def make_task(base, user):
    code, b = call("POST", "/api/parse", {"text": ARTICLE, "platform": "wechat_article"}, base=base, user=user)
    if code != 200:
        return None
    for _ in range(80):
        code, t = call("GET", "/api/tasks/" + b["task_id"], base=base, user=user)
        if t.get("status") in ("done", "failed"):
            return t
        time.sleep(0.3)
    return None


def main():
    wait_health(BASE)
    user = "rw_%d" % STAMP
    task = make_task(BASE, user)
    check("R1 任务出稿", bool(task) and task.get("status") == "done", str(task and task.get("status")))
    tid = task["id"]

    code, r = call("POST", "/api/tasks/%s/rewrite" % tid, {"style": "oral"}, user=user)
    vs = r.get("versions") or []
    check("R2 无 Key 走模板版", code == 200 and r.get("engine") == "template" and len(vs) == 3,
          "%s %s" % (r.get("engine"), len(vs)))
    check("R3 三个风格标题不同", len({v.get("title") for v in vs}) == 3)
    check("R4 稿件带填空与参考", len(vs) == 3 and all("【" in v.get("text", "") and "参考原句" in v.get("text", "") for v in vs))

    code, r2 = call("POST", "/api/tasks/%s/rewrite" % tid, {"style": "oral"}, user=user)
    check("R5 同风格命中缓存", r2.get("cached") is True)

    code, r3 = call("POST", "/api/tasks/%s/rewrite" % tid, {"style": "sales"}, user=user)
    check("R6 换风格内容不同", code == 200 and r3.get("versions", [{}])[0].get("text") != vs[0].get("text"))

    # ---------- BYOK LLM ----------
    srv = ThreadingHTTPServer(("127.0.0.1", 8795), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    env = os.environ.copy()
    env.update({"DEV_MODE": "1", "MOCK_ASR": "1", "BYOK_ALLOW_LOCAL": "1",
                "ADMIN_PASSWORD": "admin123", "ADMIN_SECRET": "local-admin-secret",
                "ADMIN_USER_IDS": "demo", "PUBLIC_BASE_URL": LLM_BASE})
    proc = subprocess.Popen([sys.executable, "-c",
                             "import uvicorn; uvicorn.run('app.main:app', host='127.0.0.1', port=8796, log_level='warning')"],
                            cwd=str(Path.cwd()), env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_health(LLM_BASE)
        u2 = "rwllm_%d" % STAMP
        task2 = make_task(LLM_BASE, u2)
        tid2 = task2["id"]
        code, k = call("POST", "/api/keys", {
            "kind": "llm", "provider": "custom", "api_key": "sk-local-test-1234",
            "base_url": "http://127.0.0.1:8795/v1", "model": "mock-llm", "skip_test": True,
        }, base=LLM_BASE, user=u2)
        check("L1 保存本地测试 Key", code == 200, str(code))
        code, r = call("POST", "/api/tasks/%s/rewrite" % tid2, {"style": "oral"}, base=LLM_BASE, user=u2)
        llm_vs = r.get("versions") or []
        check("L2 用 BYOK 生成成稿", code == 200 and r.get("engine") == "llm" and len(llm_vs) == 3,
              "%s %s" % (r.get("engine"), len(llm_vs)))
        check("L3 真实成稿无填空占位", all("【" not in v.get("text", "") for v in llm_vs))

        Handler.fail = True
        code, r = call("POST", "/api/tasks/%s/rewrite" % tid2,
                       {"style": "knowledge", "refresh": True}, base=LLM_BASE, user=u2)
        check("L4 LLM 失败自动回退模板", code == 200 and r.get("engine") == "template"
              and str(r.get("fallback", "")).startswith("LLM_"), str(r.get("fallback")))
        Handler.fail = False
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        srv.shutdown()

    bad = [r for r in results if not r[1]]
    print("-" * 48)
    print("REWRITE_PASS" if not bad else "REWRITE_FAIL %d/%d" % (len(bad), len(results)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
