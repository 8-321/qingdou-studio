import json
import re
import shutil
import subprocess
from pathlib import Path

from ..config import COOKIES_DIR, HTTP_PROXY, SUBTITLE_LANGS

YTDLP = shutil.which("yt-dlp") or "yt-dlp"
FFPROBE = shutil.which("ffprobe") or "ffprobe"


class ResolveError(RuntimeError):
    pass


def _cmd(args: list[str], cwd: Path | None = None, timeout: int = 300) -> str:
    cmd = [YTDLP, "--no-warnings", "--no-playlist", "--retries", "2", "--socket-timeout", "20"]
    if HTTP_PROXY:
        cmd += ["--proxy", HTTP_PROXY]
    from ..platforms import detect
    for a in args:
        if a.startswith("http"):
            platform = detect(a).platform
            cookie = COOKIES_DIR / f"{platform}.txt"
            if cookie.exists():
                cmd += ["--cookies", str(cookie)]
            break
    cmd += args
    try:
        proc = subprocess.run(
            cmd, cwd=str(cwd) if cwd else None, capture_output=True,
            timeout=timeout, encoding="utf-8", errors="replace",
        )
    except subprocess.TimeoutExpired as e:
        raise ResolveError("TIMEOUT") from e
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-1:] or ["UNKNOWN"]
        raise ResolveError(f"YTDLP_FAILED: {tail[0][:180]}")
    return proc.stdout


def probe(url: str) -> dict:
    raw = _cmd(["-J", "--skip-download", url], timeout=90)
    try:
        info = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ResolveError("BAD_METADATA") from e
    subs = list((info.get("subtitles") or {}).keys())
    autos = list((info.get("automatic_captions") or {}).keys())
    return {
        "id": info.get("id", ""),
        "title": info.get("title") or "未命名",
        "uploader": info.get("uploader") or "",
        "thumbnail": info.get("thumbnail") or "",
        "duration_sec": float(info.get("duration") or 0),
        "subtitles": subs,
        "automatic_captions": autos,
    }


def pick_lang(meta: dict) -> str:
    pool = meta["subtitles"] + meta["automatic_captions"]
    for want in SUBTITLE_LANGS:
        for lang in pool:
            if lang == want or lang.startswith(want + "-"):
                return lang
    return pool[0] if pool else ""


def download_subtitles(url: str, meta: dict, workdir: Path) -> tuple[list[dict], str]:
    lang = pick_lang(meta)
    if not lang:
        return [], ""
    _cmd([
        "--skip-download", "--write-subs", "--write-auto-subs",
        "--sub-langs", lang, "--sub-format", "vtt", "--convert-subs", "vtt",
        "-o", "sub.%(ext)s", url,
    ], cwd=workdir, timeout=180)
    files = sorted(workdir.glob("sub*.vtt"))
    if not files:
        return [], lang
    return parse_vtt(files[0]), lang


def parse_vtt(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8", errors="replace")
    stamp = re.compile(r"(\d{2}):(\d{2}):(\d{2})[.,](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[.,](\d{3})")
    out: list[dict] = []
    cursor = None
    buf: list[str] = []

    def ms(h, m, s, f):
        return ((int(h) * 60 + int(m)) * 60 + int(s)) * 1000 + int(f)

    for line in text.splitlines():
        m = stamp.search(line)
        if m:
            if cursor and buf:
                out.append({"start": cursor[0] / 1000, "end": cursor[1] / 1000,
                            "text": re.sub(r"<[^>]+>", "", " ".join(buf)).strip()})
            cursor = (ms(*m.groups()[:4]), ms(*m.groups()[4:]))
            buf = []
        elif line.strip() and not line.startswith(("WEBVTT", "NOTE", "Kind:", "Language:")):
            if not re.fullmatch(r"\d+", line.strip()):
                buf.append(line.strip())
    if cursor and buf:
        out.append({"start": cursor[0] / 1000, "end": cursor[1] / 1000,
                    "text": re.sub(r"<[^>]+>", "", " ".join(buf)).strip()})
    return dedupe(out)


def dedupe(segs: list[dict]) -> list[dict]:
    out: list[dict] = []
    for s in segs:
        s["text"] = re.sub(r"\s+", " ", s["text"]).strip()
        if not s["text"]:
            continue
        if out and (s["text"] == out[-1]["text"] or s["text"] in out[-1]["text"]):
            out[-1]["end"] = s["end"]
            continue
        out.append(s)
    return out


def download_audio(url: str, workdir: Path) -> Path:
    _cmd([
        "-f", "bestaudio/best", "-x", "--audio-format", "mp3", "--audio-quality", "7",
        "-o", "audio.%(ext)s", url,
    ], cwd=workdir, timeout=600)
    files = [p for p in workdir.glob("audio.*") if p.suffix in {".mp3", ".m4a", ".wav", ".opus"}]
    if not files:
        raise ResolveError("NO_AUDIO")
    return files[0]


def duration_of(path: Path) -> float:
    try:
        out = subprocess.run(
            [FFPROBE, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, timeout=30,
        ).stdout.strip()
        return float(out or 0)
    except Exception:
        return 0.0
