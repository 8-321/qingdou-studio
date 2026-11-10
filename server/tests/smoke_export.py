"""导出 + 素材库搜索/收藏/标签 端到端冒烟。"""
import io
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

BASE = "http://127.0.0.1:8788"
STAMP = int(time.time())
USER = "ex_%d" % STAMP
OTHER = "ex_other_%d" % STAMP
HEAD = {"Content-Type": "application/json", "X-User-Id": USER}

ok_count = 0
fail_count = 0


def check(name, ok, detail=""):
    global ok_count, fail_count
    if ok:
        ok_count += 1
        print("PASS " + name + (" | " + detail if detail else ""))
    else:
        fail_count += 1
        print("FAIL " + name + (" | " + detail if detail else ""))


def raw(method, path, body=None, user=USER):
    head = dict(HEAD)
    head["X-User-Id"] = user
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers=head, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def js(method, path, body=None, user=USER):
    code, head, data = raw(method, path, body, user)
    try:
        return code, json.loads(data.decode("utf-8"))
    except Exception:
        return code, {"raw": data[:300].decode("utf-8", "ignore")}


SEGS = [
    {"start": 0.0, "end": 3.4, "text": "如果你发了三十条视频还是没流量，问题不在运气。"},
    {"start": 3.4, "end": 8.1, "text": "我用三个账号实测了七天，只有一条做对了开头。"},
    {"start": 8.1, "end": 13.0, "text": "但真正的问题不是封面，是你没有前3秒钩子。"},
    {"start": 13.0, "end": 17.5, "text": "把这句话发在评论区，我挑三个人帮你看。"},
]
TEXT = "\n".join(s["text"] for s in SEGS)
STRUCT = {
    "score": 86,
    "summary": "钩子强",
    "sections": [
        {"key": "hook", "label": "钩子", "slot": "0:00", "text": SEGS[0]["text"],
         "strength": 88, "why": "制造代入", "template": "如果你也【场景】"},
        {"key": "cta", "label": "CTA", "slot": "0:13", "text": SEGS[3]["text"],
         "strength": 75, "why": "低成本动作", "template": "把【动作】发评论区"},
    ],
}


def make_task(user, title, tid, duration=0):
    from app import db
    db.create_task(tid, user, "link", "douyin", "https://v.douyin.com/test%s" % tid, title)
    db.update_task(tid, duration_sec=duration)
    db.save_result(tid, TEXT, SEGS, STRUCT, 0.12)
    return tid


def main():
    sys.path.insert(0, str(Path.cwd()))
    t1 = make_task(USER, "抖音爆款拆解", "exa%d" % STAMP, 178)
    t2 = make_task(USER, "小红书口播 复盘", "exb%d" % STAMP, 42)
    t3 = make_task(OTHER, "别人的稿子", "exc%d" % STAMP, 90)

    from app import db
    db.create_task("exq%d" % STAMP, USER, "link", "bilibili", "https://b23.tv/x", "排队中的任务")

    # --- 单条导出
    code, head, data = raw("GET", "/api/tasks/%s/export?fmt=txt" % t1)
    check("txt 200", code == 200, str(code))
    check("txt 内容一致", data.decode("utf-8").strip() == TEXT, "%d bytes" % len(data))
    cd = head.get("content-disposition", "")
    check("文件名带 UTF-8", "filename*=UTF-8''" in cd, cd[:80])
    check("X-Export-Bytes", head.get("x-export-bytes") == str(len(data)), head.get("x-export-bytes", ""))

    code, _, data = raw("GET", "/api/tasks/%s/export?fmt=srt" % t1)
    srt = data.decode("utf-8")
    check("srt 200", code == 200, str(code))
    check("srt 时间轴", "00:00:00,000 --> 00:00:03,400" in srt, srt.splitlines()[1][:40] if len(srt.splitlines()) > 1 else "")
    check("srt 句数", srt.count(" --> ") == 4, str(srt.count(" --> ")))

    code, _, data = raw("GET", "/api/tasks/%s/export?fmt=md" % t1)
    md = data.decode("utf-8")
    check("md 200", code == 200, str(code))
    check("md 标题", md.startswith("# 抖音爆款拆解"), md[:20])
    check("md 结构卡", "## 结构卡（86 分）" in md, "")
    check("md 逐句表", "| 1 | 00:00 |" in md, "")

    code, _, data = raw("GET", "/api/tasks/%s/export?fmt=docx" % t1)
    check("docx 200", code == 200, "%d bytes" % len(data))
    z = zipfile.ZipFile(io.BytesIO(data))
    names = z.namelist()
    need = ["[Content_Types].xml", "word/document.xml", "word/styles.xml", "_rels/.rels"]
    check("docx 包结构", all(n in names for n in need), ",".join(names))
    doc = z.read("word/document.xml").decode("utf-8")
    ET.fromstring(doc)
    check("docx XML 合法", True, "%d chars" % len(doc))
    check("docx 含正文", SEGS[1]["text"] in doc, "")
    check("docx 含结构卡", "结构卡（86 分）" in doc, "")

    code, _, data = raw("GET", "/api/tasks/%s/export?fmt=xlsx" % t1)
    check("xlsx 200", code == 200, "%d bytes" % len(data))
    z = zipfile.ZipFile(io.BytesIO(data))
    sheet = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
    ET.fromstring(sheet)
    check("xlsx sheet 合法", True, "%d chars" % len(sheet))
    check("xlsx 表头", "任务" in sheet and "文案" in sheet, "")
    check("xlsx 5 行", sheet.count("<row ") == 5, str(sheet.count("<row ")))

    code, _, data = raw("GET", "/api/tasks/%s/export?fmt=json" % t1)
    obj = json.loads(data.decode("utf-8"))
    check("json 200", code == 200, "")
    check("json 全字段", obj["full_text"] == TEXT and len(obj["segments"]) == 4
          and obj["structure"]["score"] == 86, "")

    code, _, _ = raw("GET", "/api/tasks/%s/export?fmt=pdf" % t1)
    check("非法格式 400", code == 400, str(code))
    code, _, _ = raw("GET", "/api/tasks/%s/export?fmt=txt" % ("exq%d" % STAMP))
    check("未完成 409", code == 409, str(code))
    code, _, _ = raw("GET", "/api/tasks/%s/export?fmt=txt" % t3)
    check("越权 404", code == 404, str(code))

    # --- 批量
    code, head, data = raw("POST", "/api/export/batch", {"ids": [t1, t2], "fmt": "docx"})
    check("批量 docx 200", code == 200, "%d bytes" % len(data))
    doc = zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml").decode("utf-8")
    check("批量含两条标题", "抖音爆款拆解" in doc and "小红书口播 复盘" in doc, "")
    check("批量分页", doc.count('w:type="page"') == 1, str(doc.count('w:type="page"')))
    check("批量计数头", head.get("x-export-count") == "2", head.get("x-export-count", ""))

    code, _, data = raw("POST", "/api/export/batch", {"ids": [t1, t2], "fmt": "xlsx"})
    sheet = zipfile.ZipFile(io.BytesIO(data)).read("xl/worksheets/sheet1.xml").decode("utf-8")
    check("批量 xlsx 行数", sheet.count("<row ") == 1 + 8, str(sheet.count("<row ")))
    check("批量 xlsx 双任务", "抖音爆款拆解" in sheet and "小红书口播 复盘" in sheet, "")

    code, _, data = raw("POST", "/api/export/batch", {"ids": [t1, t2], "fmt": "md", "zip": True})
    z = zipfile.ZipFile(io.BytesIO(data))
    files = [n for n in z.namelist() if n.endswith(".md")]
    check("zip 200", code == 200, "%d bytes" % len(data))
    check("zip 两个 md + 目录", len(files) == 2 and "_目录.txt" in z.namelist(), ",".join(z.namelist()))
    check("zip 目录含标题", "小红书口播 复盘" in z.read("_目录.txt").decode("utf-8"), "")

    code, _, _ = raw("POST", "/api/export/batch", {"ids": [], "fmt": "txt"})
    check("空批量 400", code == 400, str(code))
    code, _, _ = raw("POST", "/api/export/batch", {"ids": [t1, t3], "fmt": "txt"})
    check("批量越权 404", code == 404, str(code))

    # --- 素材库
    code, body = js("GET", "/api/tasks?limit=50")
    check("列表 total", code == 200 and body["total"] == 3, str(body.get("total")))
    check("列表含 snippet", bool(body["items"][0].get("snippet")), body["items"][0].get("snippet", "")[:20])

    code, body = js("GET", "/api/tasks?q=" + urllib.parse.quote("三十条"))
    check("搜正文命中", body["total"] == 2, str(body.get("total")))
    code, body = js("GET", "/api/tasks?q=" + urllib.parse.quote("小红书口播"))
    check("搜标题命中 1", body["total"] == 1 and body["items"][0]["id"] == t2, str(body.get("total")))
    code, body = js("GET", "/api/tasks?platform=bilibili")
    check("平台筛选", body["total"] == 1 and body["items"][0]["status"] == "queued", str(body.get("total")))
    code, body = js("GET", "/api/tasks?status=done")
    check("状态筛选", body["total"] == 2, str(body.get("total")))
    code, body = js("GET", "/api/tasks?limit=1&offset=1")
    check("分页 has_more", len(body["items"]) == 1 and body["has_more"] is True, str(body.get("has_more")))

    code, body = js("PATCH", "/api/tasks/" + t1, {"fav": 1, "tags": ["爆款", "口播", "爆款"]})
    check("收藏+标签", code == 200 and body["fav"] == 1 and body["tags"] == ["爆款", "口播"], json.dumps(body, ensure_ascii=False))
    code, body = js("PATCH", "/api/tasks/" + t2, {"tags": ["复盘", "爆款"]})
    check("第二条标签", code == 200 and body["tags"] == ["复盘", "爆款"], json.dumps(body, ensure_ascii=False))
    code, body = js("PATCH", "/api/tasks/" + t1, {"title": "改过的标题"})
    check("改标题", code == 200 and body["title"] == "改过的标题", body.get("title", ""))
    code, _ = js("PATCH", "/api/tasks/" + t3, {"fav": 1})
    check("改别人 404", code == 404, str(code))

    code, body = js("GET", "/api/tasks?fav=1")
    check("收藏筛选", body["total"] == 1 and body["items"][0]["id"] == t1, str(body.get("total")))
    code, body = js("GET", "/api/tasks?tag=" + urllib.parse.quote("爆款"))
    check("标签筛选", body["total"] == 2, str(body.get("total")))
    code, body = js("GET", "/api/task-tags")
    tags = {i["tag"]: i["count"] for i in body.get("items", [])}
    check("标签云", tags.get("爆款") == 2 and tags.get("口播") == 1, json.dumps(tags, ensure_ascii=False))

    code, body = js("GET", "/api/tasks?limit=50")
    first = [i for i in body["items"] if i["id"] == t1][0]
    check("列表带字数", first.get("chars") == len(TEXT), str(first.get("chars")))

    code, body = js("GET", "/api/tasks?sort=duration")
    check("按最长排序", body["items"][0]["id"] == t1, str(body["items"][0].get("duration_sec", "")))

    code, body = js("GET", "/api/tasks?sort=fav")
    check("收藏优先", body["items"][0]["id"] == t1, str(body["items"][0].get("fav", "")))

    code, body = js("DELETE", "/api/tasks/" + t2)
    check("删除任务 200", code == 200 and body.get("ok") is True, str(code))
    code, body = js("GET", "/api/tasks?limit=50")
    check("删除后列表减一", body["total"] == 2 and all(i["id"] != t2 for i in body["items"]), str(body.get("total")))
    code, body = js("GET", "/api/tasks?q=" + urllib.parse.quote("小红书口播"))
    check("删除后搜不到", body["total"] == 0, str(body.get("total")))
    code, body = js("GET", "/api/tasks?status=deleted")
    check("回收站不外露", body["total"] == 0, str(body.get("total")))

    print()
    print("EXPORT_PASS" if fail_count == 0 else "EXPORT_FAIL")
    print("pass=%d fail=%d" % (ok_count, fail_count))
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())