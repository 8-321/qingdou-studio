"""文案导出：TXT / Markdown / SRT / Word(.docx) / Excel(.xlsx) / JSON。

Word 与 Excel 直接写 OOXML（zip + xml），不引入额外依赖，
保证在最小部署环境里也能导出。
"""
from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import datetime
from xml.sax.saxutils import escape, quoteattr

FORMATS = {
    "txt": ("纯文本", "text/plain; charset=utf-8", "txt"),
    "md": ("Markdown", "text/markdown; charset=utf-8", "md"),
    "srt": ("字幕 SRT", "application/x-subrip; charset=utf-8", "srt"),
    "docx": ("Word", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"),
    "xlsx": ("Excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
    "json": ("结构化 JSON", "application/json; charset=utf-8", "json"),
}

PLATFORM_LABEL = {
    "douyin": "抖音", "kuaishou": "快手", "xiaohongshu": "小红书", "bilibili": "B站",
    "wechat_article": "公众号", "wechat_channels": "视频号", "weibo": "微博",
    "ixigua": "西瓜视频", "youtube": "YouTube", "tiktok": "TikTok",
    "instagram": "Instagram", "twitter": "X", "upload": "本地上传", "unknown": "其他",
}

_BAD_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def platform_label(value: str) -> str:
    return PLATFORM_LABEL.get(value or "", value or "其他")


def safe_name(title: str, fallback: str = "文案") -> str:
    name = _BAD_CHARS.sub(" ", (title or "").strip())
    name = re.sub(r"\s+", " ", name).strip(" .")
    if not name:
        name = fallback
    return name[:60]


def clock(seconds: float, with_ms: bool = False) -> str:
    seconds = max(0.0, float(seconds or 0))
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if with_ms:
        ms = int(round((seconds - total) * 1000))
        if ms >= 1000:
            ms = 999
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _clean(value) -> str:
    text = "" if value is None else str(value)
    return "".join(ch for ch in text if ch in "\t\n\r" or ord(ch) >= 0x20)


def _x(value) -> str:
    return escape(_clean(value))


def _segments(task: dict) -> list[dict]:
    raw = task.get("segments_json")
    if isinstance(raw, str):
        try:
            data = json.loads(raw or "[]")
        except json.JSONDecodeError:
            data = []
    else:
        data = raw or []
    out = []
    for seg in data:
        text = str(seg.get("text") or "").strip()
        if text:
            out.append({"start": float(seg.get("start") or 0),
                        "end": float(seg.get("end") or 0), "text": text})
    return out


def _structure(task: dict) -> dict:
    raw = task.get("structure_json")
    if isinstance(raw, str):
        try:
            return json.loads(raw or "{}")
        except json.JSONDecodeError:
            return {}
    return raw or {}


def _rewrites(task: dict) -> dict:
    raw = task.get("rewrite_json")
    if isinstance(raw, str):
        try:
            return json.loads(raw or "{}")
        except json.JSONDecodeError:
            return {}
    return raw or {}


def _meta(task: dict) -> list[str]:
    bits = [platform_label(task.get("platform", ""))]
    if task.get("duration_sec"):
        bits.append(clock(task["duration_sec"]))
    if task.get("created_at"):
        bits.append(str(task["created_at"]))
    return bits


def _title(task: dict) -> str:
    return (task.get("title") or "").strip() or "未命名文案"


def to_txt(task: dict) -> str:
    return (task.get("full_text") or "").strip() + "\n"


def to_srt(task: dict) -> str:
    lines = []
    for i, seg in enumerate(_segments(task), 1):
        start = clock(seg["start"], True)
        end = clock(seg["end"] or seg["start"] + 2, True)
        lines.append(f"{i}\n{start} --> {end}\n{seg['text']}\n")
    return "\n".join(lines)


def to_md(task: dict) -> str:
    segs = _segments(task)
    card = _structure(task)
    parts = [f"# {_title(task)}", "", "> " + " · ".join(_meta(task)), ""]
    if task.get("source_url"):
        parts += [f"- 来源：{task['source_url']}", ""]
    parts += ["## 全文", "", (task.get("full_text") or "").strip(), ""]
    if segs:
        parts += ["## 逐句稿", "", "| # | 时间 | 文案 |", "| --- | --- | --- |"]
        for i, seg in enumerate(segs, 1):
            cell = seg["text"].replace("|", "\\|")
            parts.append(f"| {i} | {clock(seg['start'])} | {cell} |")
        parts.append("")
    sections = card.get("sections") or []
    if sections:
        parts += [f"## 结构卡（{card.get('score', 0)} 分）", ""]
        for sec in sections:
            parts.append(f"### {sec.get('label', '')} · {sec.get('slot', '')} · {sec.get('strength', 0)}")
            parts.append("")
            parts.append(f"- 原句：{sec.get('text', '')}")
            if sec.get("why"):
                parts.append(f"- 为什么有效：{sec['why']}")
            if sec.get("template"):
                parts.append(f"- 可套用：{sec['template']}")
            parts.append("")
    rewrites = _rewrites(task)
    if rewrites:
        parts += ["## 二创版本", ""]
        for style, block in rewrites.items():
            parts.append(f"### {block.get('style_label') or style}")
            parts.append("")
            for idx, ver in enumerate(block.get("versions") or [], 1):
                parts.append(f"**版本 {idx}** {ver.get('title', '')}")
                parts.append("")
                parts.append(ver.get("text", ""))
                parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def to_json(task: dict) -> str:
    payload = {
        "id": task.get("id"),
        "title": _title(task),
        "platform": task.get("platform"),
        "platform_label": platform_label(task.get("platform", "")),
        "source_url": task.get("source_url"),
        "duration_sec": task.get("duration_sec"),
        "created_at": task.get("created_at"),
        "full_text": task.get("full_text") or "",
        "segments": _segments(task),
        "structure": _structure(task),
        "rewrites": _rewrites(task),
        "exported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- Word

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _para(text: str, style: str = "", bold: bool = False) -> str:
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    rpr = "<w:rPr><w:b/></w:rPr>" if bold else ""
    return (f'<w:p>{ppr}<w:r>{rpr}<w:t xml:space="preserve">{_x(text)}</w:t></w:r></w:p>')


def _docx_document(tasks: list[dict]) -> str:
    body: list[str] = []
    for ti, task in enumerate(tasks):
        if ti:
            body.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')
        body.append(_para(_title(task), "Heading1"))
        body.append(_para(" · ".join(_meta(task)), "Quote"))
        if task.get("source_url"):
            body.append(_para("来源：" + str(task["source_url"]), "Quote"))
        body.append(_para("全文", "Heading2"))
        for line in (task.get("full_text") or "").splitlines():
            if line.strip():
                body.append(_para(line.strip()))
        segs = _segments(task)
        if segs:
            body.append(_para("逐句稿", "Heading2"))
            for i, seg in enumerate(segs, 1):
                body.append(_para(f"{i:02d}  {clock(seg['start'])}  {seg['text']}"))
        card = _structure(task)
        if card.get("sections"):
            body.append(_para(f"结构卡（{card.get('score', 0)} 分）", "Heading2"))
            for sec in card["sections"]:
                body.append(_para(f"{sec.get('label', '')} · {sec.get('slot', '')} · {sec.get('strength', 0)}", bold=True))
                body.append(_para("原句：" + str(sec.get("text", ""))))
                if sec.get("why"):
                    body.append(_para("为什么有效：" + str(sec["why"]), "Quote"))
                if sec.get("template"):
                    body.append(_para("可套用：" + str(sec["template"]), "Quote"))
        rewrites = _rewrites(task)
        if rewrites:
            body.append(_para("二创版本", "Heading2"))
            for style, block in rewrites.items():
                body.append(_para(str(block.get("style_label") or style), bold=True))
                for idx, ver in enumerate(block.get("versions") or [], 1):
                    body.append(_para(f"版本 {idx} {ver.get('title', '')}", bold=True))
                    body.append(_para(ver.get("text", "")))
    sect = ('<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
            '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr>')
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<w:document xmlns:w="{_W_NS}"><w:body>' + "".join(body) + sect + "</w:body></w:document>")


_STYLES = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="{_W_NS}">
<w:docDefaults><w:rPrDefault><w:rPr>
<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="微软雅黑"/>
<w:sz w:val="22"/><w:szCs w:val="22"/></w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="312" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
<w:pPr><w:spacing w:before="240" w:after="160"/><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/><w:sz w:val="36"/><w:szCs w:val="36"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
<w:pPr><w:spacing w:before="240" w:after="120"/><w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:b/><w:sz w:val="28"/><w:szCs w:val="28"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Quote"><w:name w:val="Quote"/><w:basedOn w:val="Normal"/><w:qFormat/>
<w:pPr><w:ind w:left="240"/></w:pPr><w:rPr><w:color w:val="595959"/><w:sz w:val="20"/></w:rPr></w:style>
</w:styles>'''


def to_docx(tasks: list[dict]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                   '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
                   '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
                   '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
                   '</Types>')
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
                   '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
                   '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
                   '</Relationships>')
        z.writestr("word/document.xml", _docx_document(tasks))
        z.writestr("word/styles.xml", _STYLES)
        z.writestr("word/_rels/document.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                   '</Relationships>')
        title = _title(tasks[0]) if len(tasks) == 1 else f"文案合集（{len(tasks)} 条）"
        z.writestr("docProps/core.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                   'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
                   'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
                   f'<dc:title>{_x(title)}</dc:title><dc:creator>文案工作台</dc:creator>'
                   '</cp:coreProperties>')
        z.writestr("docProps/app.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
                   '<Application>文案工作台</Application></Properties>')
    return buf.getvalue()


# ---------------------------------------------------------------- Excel

_X_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def _cell(ref: str, value) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f'<c r="{ref}" t="n"><v>{value}</v></c>'
    return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{_x(value)}</t></is></c>'


def _col(i: int) -> str:
    out = ""
    while i > 0:
        i, rem = divmod(i - 1, 26)
        out = chr(65 + rem) + out
    return out


def _sheet_rows(tasks: list[dict]) -> list[list]:
    rows: list[list] = [["任务", "序号", "开始", "结束", "文案"]]
    for task in tasks:
        name = _title(task)
        segs = _segments(task)
        if not segs:
            rows.append([name, 1, "", "", (task.get("full_text") or "").strip()])
            continue
        for i, seg in enumerate(segs, 1):
            rows.append([name, i, clock(seg["start"]), clock(seg["end"] or seg["start"]), seg["text"]])
    return rows


def to_xlsx(tasks: list[dict]) -> bytes:
    rows = _sheet_rows(tasks)
    xml_rows = []
    for r, row in enumerate(rows, 1):
        cells = "".join(_cell(f"{_col(c)}{r}", v) for c, v in enumerate(row, 1))
        xml_rows.append(f'<row r="{r}">{cells}</row>')
    width = _col(len(rows[0]))
    sheet = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             f'<worksheet xmlns="{_X_NS}"><dimension ref="A1:{width}{len(rows)}"/>'
             '<cols><col min="1" max="1" width="28"/><col min="2" max="2" width="7"/>'
             '<col min="3" max="4" width="10"/><col min="5" max="5" width="90"/></cols>'
             '<sheetData>' + "".join(xml_rows) + '</sheetData>'
             '<autoFilter ref="A1:' + width + str(len(rows)) + '"/></worksheet>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                   '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                   '</Types>')
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                   '</Relationships>')
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   f'<workbook xmlns="{_X_NS}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                   '<sheets><sheet name="逐句稿" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
                   '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                   '</Relationships>')
        z.writestr("xl/styles.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   f'<styleSheet xmlns="{_X_NS}">'
                   '<fonts count="1"><font><sz val="11"/><name val="微软雅黑"/></font></fonts>'
                   '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
                   '<borders count="1"><border/></borders>'
                   '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
                   '<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>'
                   '</styleSheet>')
        z.writestr("xl/worksheets/sheet1.xml", sheet)
    return buf.getvalue()


# ---------------------------------------------------------------- dispatch

def build(fmt: str, tasks: list[dict]) -> tuple[bytes, str, str]:
    """返回 (内容字节, MIME, 扩展名)。fmt 非法时抛 ValueError。"""
    if not tasks:
        raise ValueError("NO_TASKS")
    fmt = (fmt or "txt").lower()
    if fmt not in FORMATS:
        raise ValueError("BAD_FORMAT")
    if fmt == "txt":
        head = ""
        if len(tasks) > 1:
            head = "\n\n" + ("-" * 30) + "\n\n"
        data = head.join(to_txt(t) for t in tasks).encode("utf-8")
    elif fmt == "md":
        data = ("\n\n---\n\n".join(to_md(t) for t in tasks)).encode("utf-8")
    elif fmt == "srt":
        data = "\n".join(to_srt(t) for t in tasks).encode("utf-8")
    elif fmt == "json":
        payload = [json.loads(to_json(t)) for t in tasks]
        data = json.dumps(payload if len(payload) > 1 else payload[0],
                          ensure_ascii=False, indent=2).encode("utf-8")
    elif fmt == "docx":
        data = to_docx(tasks)
    else:
        data = to_xlsx(tasks)
    return data, FORMATS[fmt][1], FORMATS[fmt][2]


def build_zip(fmt: str, tasks: list[dict]) -> bytes:
    fmt = (fmt or "txt").lower()
    if fmt not in FORMATS:
        raise ValueError("BAD_FORMAT")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        index = ["文件名\t标题\t平台\t时长\t提取时间"]
        for i, task in enumerate(tasks, 1):
            body, _, ext = build(fmt, [task])
            name = f"{i:03d}-{safe_name(_title(task))}.{ext}"
            z.writestr(name, body)
            index.append("\t".join([name, _title(task), platform_label(task.get("platform", "")),
                                    clock(task.get("duration_sec") or 0), str(task.get("created_at") or "")]))
        z.writestr("_目录.txt", "\n".join(index) + "\n")
    return buf.getvalue()


def content_disposition(filename: str) -> str:
    from urllib.parse import quote
    stem, dot, ext = (filename or "").rpartition(".")
    if not dot:
        stem, ext = filename or "", ""
    ascii_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("_.")
    if not ascii_stem:
        ascii_stem = "export-" + datetime.now().strftime("%Y%m%d")
    ascii_name = ascii_stem + ("." + ext if ext else "")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"