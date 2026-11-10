"""时长上限：免费 10 分钟；会员 / BYOK ASR 放宽到 MAX_DURATION_SEC（默认 180 分钟）。"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

BASE = "http://127.0.0.1:8788"
os.chdir(Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(Path.cwd()))
from app import db

results = []
STAMP = int(time.time())


def call(method, path, body=None, user=None, raw=None, ctype=None):
    head = {}
    if user:
        head["X-User-Id"] = user
    data = raw
    if body is not None:
        data = json.dumps(body).encode()
        head["Content-Type"] = "application/json"
    if ctype:
        head["Content-Type"] = ctype
    req = urllib.request.Request(BASE + path, data=data, headers=head, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {"raw": e.read().decode(errors="ignore")}


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (" | " + detail if detail else ""))


def upload(user, path):
    raw = Path(path).read_bytes()
    b = "----lim" + uuid.uuid4().hex
    payload = (("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"%s\"\r\n"
                "Content-Type: audio/mpeg\r\n\r\n") % (b, Path(path).name)).encode() + raw + ("\r\n--%s--\r\n" % b).encode()
    return call("POST", "/api/upload/simple", user=user, raw=payload,
                ctype="multipart/form-data; boundary=" + b)


def poll(user, tid, limit=200):
    t = {}
    for _ in range(limit):
        code, t = call("GET", "/api/tasks/" + tid, user=user)
        if t.get("status") in ("done", "failed"):
            return t
        time.sleep(0.3)
    return t


def feature(user, name):
    code, body = call("GET", "/api/features", user=user)
    for it in body.get("items", []):
        if it["feature"] == name:
            return it
    return {}


def main():
    long_path = "tests/fixtures/long11.mp3"
    if not Path(long_path).exists():
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=660",
                        "-ar", "16000", "-ac", "1", "-b:a", "16k", "-y", long_path], check=False)

    free = "limfree_%d" % STAMP
    code, up = upload(free, long_path)
    check("L1 上传 11 分钟录音", code == 200, str(code))
    t = poll(free, up["task_id"])
    check("L2 免费用户被时长拦住", t.get("status") == "failed" and t.get("error_code") == "TOO_LONG",
          "%s %s" % (t.get("status"), t.get("error_code")))
    check("L3 超时自动退次数", feature(free, "audio_extract").get("used") == 0,
          "used=%s" % feature(free, "audio_extract").get("used"))
    check("L4 错误提示可读", "10 分钟" in (t.get("error_msg") or "") and "180 分钟" in (t.get("error_msg") or ""),
          t.get("error_msg") or "")

    paid = "limpaid_%d" % STAMP
    db.set_plan_until(paid, "pro", 30)
    code, up = upload(paid, long_path)
    check("L5 会员可传长音频", code == 200, str(code))
    t = poll(paid, up["task_id"])
    check("L6 会员任务出稿", t.get("status") == "done", "%s %s" % (t.get("status"), t.get("error_code")))
    check("L7 句数与时长匹配", (t.get("duration_sec") or 0) > 600, "duration=%s" % t.get("duration_sec"))

    bad = [r for r in results if not r[1]]
    print("-" * 48)
    print("LIMITS_PASS" if not bad else "LIMITS_FAIL %d/%d" % (len(bad), len(results)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
