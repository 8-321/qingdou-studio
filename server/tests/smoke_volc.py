import json
import os
import sys
import threading
import wave
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["PUBLIC_BASE_URL"] = "http://127.0.0.1:8792"
os.environ["VOLC_ASR_BASE"] = "http://127.0.0.1:8792"

from app import asr, byok
from app.config import WORK_DIR

calls = {"submit": 0, "query": 0}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n).decode())
        if self.path.endswith("/submit"):
            calls["submit"] += 1
            assert "api/public/audio/" in body["audio"]["url"], body
            out = {"resp": {"code": 1000, "message": "Success", "task_id": "fake-task"}}
        else:
            calls["query"] += 1
            if calls["query"] == 1:
                out = {"resp": {"code": 2000, "message": "Running"}}
            else:
                out = {"resp": {"code": 1000, "message": "Success", "utterances": [
                    {"start_time": 0, "end_time": 1200, "text": "第一句话。"},
                    {"start_time": 1200, "end_time": 2600, "text": "第二句话。"},
                ]}}
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def make_wav(path: Path):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\0\0" * 16000)


srv = HTTPServer(("127.0.0.1", 8792), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()

wav = WORK_DIR / "volc_test.wav"
make_wav(wav)
key = {"provider": "volcengine", "model": "volc_auc_common",
       "cipher": byok.encrypt("app123:token456:volc_auc_common")}
segs = asr.transcribe(wav, 1.0, "zh", key)
print("submit calls:", calls["submit"], "query calls:", calls["query"])
print("segments:", segs)
assert calls["submit"] == 1 and calls["query"] >= 2
assert [s["text"] for s in segs] == ["第一句话。", "第二句话。"]
assert segs[0]["start"] == 0.0 and segs[1]["end"] == 2.6
print("VOLC_PASS")
srv.shutdown()
