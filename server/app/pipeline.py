import asyncio
import re
import shutil
import time
import uuid
from pathlib import Path

from . import asr, db, sec, structure
from .config import FREE_MAX_SECONDS, MAX_DURATION_SEC, WORK_DIR
from .resolvers import article, media
from .text import clean_text


def _article_segments(text: str) -> list[dict]:
    from .text import split_sentences
    sentences = [s for s in split_sentences(text) if len(s) > 1]
    segs, cursor = [], 0.0
    for s in sentences:
        dur = max(1.5, len(s) / 5.5)
        segs.append({"start": round(cursor, 2), "end": round(cursor + dur, 2), "text": s})
        cursor += dur
    return segs


def _merge_cues(cues: list[dict]) -> list[dict]:
    out: list[dict] = []
    buf, start, end = [], 0.0, 0.0
    for c in cues:
        if not buf:
            start = c["start"]
        buf.append(c["text"])
        end = c["end"]
        joined = "".join(buf)
        if len(joined) >= 24 or re.search(r"[。！？!?]$", joined) or (end - start) >= 7:
            out.append({"start": round(start, 2), "end": round(end, 2), "text": joined})
            buf = []
    if buf:
        out.append({"start": round(start, 2), "end": round(end, 2), "text": "".join(buf)})
    return out


def _max_seconds(user_id: str) -> int:
    plan = db.get_plan(user_id)
    if plan.get("plan") in ("pro", "team", "enterprise"):
        return MAX_DURATION_SEC
    if db.get_key(user_id, "asr"):
        return MAX_DURATION_SEC
    return FREE_MAX_SECONDS


def _check_duration(user_id: str, seconds: float) -> None:
    if not seconds or seconds <= 0:
        return
    limit = _max_seconds(user_id)
    if seconds > limit:
        raise ValueError("TOO_LONG:这条 %d 分钟，当前上限 %d 分钟。升级会员或用自己 Key 可提到 %d 分钟" % (
            round(seconds / 60), round(limit / 60), round(MAX_DURATION_SEC / 60)))


async def run_task(task_id: str) -> None:
    task = db.get_task(task_id)
    if not task:
        return
    workdir = WORK_DIR / task_id
    workdir.mkdir(parents=True, exist_ok=True)
    started = time.time()

    try:
        platform = task["platform"]
        if platform == "wechat_article":
            db.update_task(task_id, status="resolving", stage="抓取文章", progress=12)
            data = await article.resolve(task["source_url"])
            db.update_task(task_id, title=data["title"], cover=data["cover"],
                           duration_sec=data["duration_sec"], progress=55, stage="分段")
            text = clean_text(data["text"])
            segs = _article_segments(text)
            cost = 0.0
        elif platform == "upload":
            path = Path(task["source_url"])
            db.update_task(task_id, status="transcribing", stage="语音转写", progress=35)
            duration = media.duration_of(path) or 0
            _check_duration(task["user_id"], duration)
            db.update_task(task_id, duration_sec=duration, progress=45)
            key = db.get_key(task["user_id"], "asr")
            segs = await asyncio.to_thread(asr.transcribe, path, duration, "zh", key)
            text = clean_text("".join(s["text"] for s in segs))
            cost = duration / 3600 * 80
        else:
            db.update_task(task_id, status="resolving", stage="解析链接", progress=8)
            meta = await asyncio.to_thread(media.probe, task["source_url"])
            if meta["duration_sec"] > 0:
                _check_duration(task["user_id"], meta["duration_sec"])
                db.update_task(task_id, title=meta["title"], cover=meta["thumbnail"],
                               duration_sec=meta["duration_sec"], progress=22)
            if meta["subtitles"] or meta["automatic_captions"]:
                db.update_task(task_id, stage="读取字幕", progress=35)
                cues, lang = await asyncio.to_thread(media.download_subtitles, task["source_url"], meta, workdir)
                cost = 0.0
            else:
                db.update_task(task_id, stage="下载音频", progress=30)
                audio = await asyncio.to_thread(media.download_audio, task["source_url"], workdir)
                db.update_task(task_id, stage="语音转写", progress=55)
                key = db.get_key(task["user_id"], "asr")
                cues = await asyncio.to_thread(asr.transcribe, audio, meta["duration_sec"], "zh", key)
                cost = meta["duration_sec"] / 3600 * 80
            segs = _merge_cues(cues)

        if not segs:
            raise media.ResolveError("NO_SPEECH")

        segs = [s for s in segs if s["text"].strip()]
        text = clean_text("\n".join(s["text"] for s in segs))
        db.update_task(task_id, stage="内容检测", progress=78)
        verdict = await asyncio.to_thread(sec.check_text, text, task["user_id"])
        if verdict.get("suggest") in ("risky", "review"):
            raise sec.SecBlocked()
        db.update_task(task_id, stage="拆解结构", progress=82)
        card = structure.build(segs)
        db.save_result(task_id, text, segs, card, cost)
        (workdir / "result.txt").write_text(text, encoding="utf-8")
        db.update_task(task_id, progress=100, stage="完成")
    except Exception as e:
        code = str(e).split(":")[0][:40] or "UNKNOWN"
        db.update_task(task_id, status="failed", error_code=code,
                       error_msg=str(e)[:300], finished_at=db.now())
        db.refund_charge(task_id)
    finally:
        for f in workdir.glob("audio.*"):
            try:
                f.unlink(missing_ok=True)
            except OSError:
                pass

