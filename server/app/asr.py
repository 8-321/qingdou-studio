import os
import shutil
import subprocess
import time
from pathlib import Path

import httpx

from .config import MOCK_ASR


class ASRError(RuntimeError):
    pass


def transcribe(path: Path, duration: float, lang: str = "zh", key: dict | None = None) -> list[dict]:
    if key:
        return _cloud(path, key)
    if MOCK_ASR:
        return _mock(duration)
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise ASRError("ASR_NOT_INSTALLED") from e
    model = WhisperModel("small", device="auto", compute_type="int8")
    segments, _ = model.transcribe(str(path), language=lang, vad_filter=True)
    return [{"start": s.start, "end": s.end, "text": s.text.strip()} for s in segments if s.text.strip()]


def _cloud(path: Path, key: dict) -> list[dict]:
    provider = key.get("provider")
    if provider == "volcengine":
        return _volcengine(path, key)
    base = (key.get("base_url") or "").rstrip("/")
    if not base:
        raise ASRError("ASR_BASE_URL_MISSING")
    headers = {"Authorization": "Bearer " + _decrypt(key)}
    try:
        with httpx.Client(timeout=180) as client, open(path, "rb") as f:
            r = client.post(
                base + "/audio/transcriptions",
                headers=headers,
                data={"model": key.get("model") or "whisper-1", "response_format": "json"},
                files={"file": (path.name, f, "application/octet-stream")},
            )
        if r.status_code >= 300:
            raise ASRError(f"ASR_HTTP_{r.status_code}")
        text = (r.json().get("text") or "").strip()
    except httpx.TimeoutException as e:
        raise ASRError("ASR_TIMEOUT") from e
    if not text:
        raise ASRError("NO_SPEECH")
    return _split(text)


def _decrypt(key: dict) -> str:
    from .byok import decrypt
    return decrypt(key["cipher"])


def _split(text: str, per: int = 28) -> list[dict]:
    import re
    pieces = [p for p in re.split(r"(?<=[。！？!?；;])", text) if p.strip()]
    out, t = [], 0.0
    for p in pieces:
        dur = max(1.5, len(p) / 5.5)
        out.append({"start": round(t, 2), "end": round(t + dur, 2), "text": p.strip()})
        t += dur
    return out


def _mock(duration: float) -> list[dict]:
    lines = [
        "[演示转写] 当前未安装 faster-whisper，返回占位文本。",
        "[演示转写] 生产环境请配置 ASR_PROVIDER=volcengine 或安装 faster-whisper。",
        "[演示转写] 这条占位文本用于验证上传、分片、任务队列与导出链路。",
    ]
    total = max(duration, len(lines) * 4.0)
    step = total / len(lines)
    return [{"start": i * step, "end": (i + 1) * step, "text": t} for i, t in enumerate(lines)]


def _volcengine(path: Path, key: dict) -> list[dict]:
    from . import publicfile

    parts = _decrypt(key).split(":")
    if len(parts) != 3:
        raise ASRError("VOLC_KEY_FORMAT")
    appid, token, cluster = parts
    cluster = cluster or key.get("model") or "volc_auc_common"
    base = os.getenv("VOLC_ASR_BASE", "https://openspeech.bytedance.com").rstrip("/")
    wav = path.with_suffix(".asr.wav")
    upload = path
    fmt = path.suffix.lstrip(".").lower() or "mp3"
    try:
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            proc = subprocess.run(
                [ffmpeg, "-y", "-v", "error", "-i", str(path), "-ac", "1",
                 "-ar", "16000", "-f", "wav", str(wav)],
                capture_output=True, timeout=180,
            )
            if proc.returncode == 0 and wav.exists():
                upload, fmt = wav, "wav"
    except Exception:
        upload, fmt = path, path.suffix.lstrip(".").lower() or "mp3"

    try:
        audio_url = publicfile.public_url(upload)
    except ValueError as e:
        raise ASRError(str(e)) from e

    headers = {"Authorization": f"Bearer; {token}", "Content-Type": "application/json"}
    app = {"appid": appid, "token": token, "cluster": cluster}
    body = {
        "app": app,
        "user": {"uid": "script-studio"},
        "audio": {"url": audio_url, "format": fmt, "codec": "raw",
                  "rate": 16000, "bits": 16, "channel": 1},
        "request": {"show_utterances": True},
    }
    try:
        with httpx.Client(timeout=30) as client:
            r = client.post(base + "/api/v1/auc/submit", headers=headers, json=body)
            if r.status_code >= 300:
                raise ASRError(f"VOLC_SUBMIT_{r.status_code}")
            data = r.json()
            resp = data.get("resp") or data
            task_id = resp.get("task_id") or data.get("task_id")
            if not task_id:
                raise ASRError(f"VOLC_SUBMIT_{resp.get('code', 'NO_TASK')}")

            deadline = time.time() + 300
            while time.time() < deadline:
                q = client.post(base + "/api/v1/auc/query", headers=headers,
                                json={"app": app, "task_id": task_id})
                if q.status_code >= 300:
                    raise ASRError(f"VOLC_QUERY_{q.status_code}")
                qd = q.json()
                qr = qd.get("resp") or qd
                code = int(qr.get("code") or 0)
                if code == 2000:
                    time.sleep(2)
                    continue
                if code == 3000:
                    raise ASRError("VOLC_TASK_FAILED")
                if code != 1000:
                    raise ASRError(f"VOLC_QUERY_{code}")
                return _volc_segments(qr)
            raise ASRError("VOLC_TIMEOUT")
    except httpx.TimeoutException as e:
        raise ASRError("VOLC_TIMEOUT") from e
    finally:
        try:
            wav.unlink(missing_ok=True)
        except OSError:
            pass


def _volc_segments(resp: dict) -> list[dict]:
    out = []
    for u in resp.get("utterances") or []:
        text = (u.get("text") or "").strip()
        if not text:
            continue
        out.append({
            "start": round(float(u.get("start_time") or 0) / 1000.0, 2),
            "end": round(float(u.get("end_time") or 0) / 1000.0, 2),
            "text": text,
        })
    if out:
        return out
    text = (resp.get("text") or "").strip()
    if not text:
        raise ASRError("NO_SPEECH")
    return _split(text)
