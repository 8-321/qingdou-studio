"""二创：把原片结构迁移成可直接开拍的稿子。

没有 LLM Key 时输出「填空式结构稿」（规则版，零成本、离线可用）；
配了 BYOK LLM 时调用用户自己的 Key 生成 3 版成稿，平台不承担 AI 费用。
"""
import json
import re

import httpx

from .byok import decrypt

STYLES = {
    "oral": {"name": "同结构口播", "note": "保留原片节奏，换成你的题材"},
    "knowledge": {"name": "知识拆解", "note": "反常识结论 + 3 个证据"},
    "sales": {"name": "带货口播", "note": "痛点 → 产品 → 证据 → 优惠 → CTA"},
}


class RewriteError(RuntimeError):
    pass


def _find(structure: dict, key: str) -> dict:
    for sec in (structure or {}).get("sections") or []:
        if sec.get("key") == key:
            return sec
    return {}


def _numbers(text: str, limit: int = 3) -> str:
    nums = re.findall(r"\d+(?:\.\d+)?\s*(?:万|亿|倍|%|元|块|天|年|个|条|次)?", text or "")
    seen, out = set(), []
    for n in nums:
        if n not in seen:
            seen.add(n)
            out.append(n)
        if len(out) >= limit:
            break
    return "、".join(out)


def _join(blocks: list[dict]) -> str:
    return "\n\n".join("【%s %s】\n%s\n（参考原句：%s）" % (
        b["label"], b["slot"], b["line"], b["ref"]) for b in blocks)


def template_versions(task: dict, structure: dict, style: str = "oral") -> list[dict]:
    title = task.get("title") or "这条内容"
    text = task.get("full_text") or ""
    nums = _numbers(text)
    hook = _find(structure, "hook")
    pain = _find(structure, "pain")
    proof = _find(structure, "proof")
    turn = _find(structure, "turn")
    cta = _find(structure, "cta")

    oral = [
        {"label": "钩子", "slot": "0-3s",
         "line": "如果你也【你的具体场景】，做了【N 次】还是【没结果】，先别急着【常见动作】——问题不在【表面原因】，在【反常识原因】。",
         "ref": hook.get("text") or title},
        {"label": "痛点", "slot": "前 1/3",
         "line": "你是不是也这样：【具体场景】，每次都【具体损失】。我一开始也以为是【误判】，直到【触发事件】。",
         "ref": pain.get("text") or ""},
        {"label": "证据", "slot": "中段",
         "line": "我拿【N 个样本】实测，只有【M 个】做对了。差距不在【大家以为的变量】，在【关键变量】%s。" % (
             "，比如 " + nums if nums else ""),
         "ref": proof.get("text") or ""},
        {"label": "转折", "slot": "中段",
         "line": "但真正的问题不是【表层原因】，是你没有【更高维度的缺失】。把【关键动作】换掉，结果立刻不一样。",
         "ref": turn.get("text") or ""},
        {"label": "CTA", "slot": "结尾",
         "line": "我把【清单/模板】放在【评论区/主页】，想要的说一声；下一条讲【下一个具体问题】。",
         "ref": cta.get("text") or ""},
    ]
    knowledge = [
        {"label": "反常识结论", "slot": "0-3s",
         "line": "大多数人以为【常识结论】，但实测下来，真正决定结果的是【反常识变量】。",
         "ref": hook.get("text") or title},
        {"label": "证据 1", "slot": "第 1 段",
         "line": "第一，【可验证的事实/数字】。你可以用【低成本验证方式】自己试一次。",
         "ref": proof.get("text") or ""},
        {"label": "证据 2", "slot": "第 2 段",
         "line": "第二，【对比案例】。同样的【条件】，只改了【变量】，结果差【倍数】。",
         "ref": pain.get("text") or ""},
        {"label": "证据 3", "slot": "第 3 段",
         "line": "第三，【边界条件】。这套方法在【场景】有效，在【场景】不成立，别用错。",
         "ref": turn.get("text") or ""},
        {"label": "收束", "slot": "结尾",
         "line": "记住一句话：【一句话结论】。想要完整清单，评论区留【关键词】。",
         "ref": cta.get("text") or ""},
    ]
    sales = [
        {"label": "痛点开场", "slot": "0-3s",
         "line": "还在为【具体痛点】反复【无效动作】？不是你不行，是【产品/方法】没选对。",
         "ref": pain.get("text") or hook.get("text") or title},
        {"label": "产品出场", "slot": "前 1/3",
         "line": "我用的是【产品名】，它只解决一件事：【一句话卖点】。",
         "ref": proof.get("text") or ""},
        {"label": "证据", "slot": "中段",
         "line": "实测【N 次/天】，【具体指标】从【A】到【B】%s。" % (
             "，原片里的 " + nums + " 可以换成你的数据" if nums else ""),
         "ref": proof.get("text") or ""},
        {"label": "对比", "slot": "中段",
         "line": "和【旧方案】比，它省掉【步骤】，成本从【X】降到【Y】。",
         "ref": turn.get("text") or ""},
        {"label": "优惠 + CTA", "slot": "结尾",
         "line": "现在【优惠】还剩【N 份】，点【位置】报【暗号】；不适合【人群】的别买。",
         "ref": cta.get("text") or ""},
    ]
    families = {"oral": oral, "knowledge": knowledge, "sales": sales}
    base = families.get(style, oral)
    variants = [("标准版", base)]
    if len(base) >= 5:
        variants.append(("快节奏版", [base[0], base[1], base[3], base[4]]))
        lead = [dict(base[0])]
        lead[0]["line"] = "先说结论：" + lead[0]["line"]
        variants.append(("结论前置版", lead + base[1:]))
    out = []
    for idx, (vname, blocks) in enumerate(variants):
        out.append({"style": style, "name": STYLES[style]["name"], "variant": vname,
                    "title": "%s · %s·%s" % (title, STYLES[style]["name"], vname),
                    "text": _join(blocks), "blocks": blocks})
    return out


def _prompt(task: dict, structure: dict, style: str) -> list[dict]:
    name = STYLES.get(style, STYLES["oral"])["name"]
    src = (task.get("full_text") or "")[:6000]
    secs = "\n".join("%s(%s): %s" % (s.get("label"), s.get("slot"), s.get("text"))
                      for s in (structure or {}).get("sections") or [])
    system = ("你是中文短视频编剧。只输出 JSON，不要解释。"
              "JSON 结构：{\"versions\":[{\"title\":\"\",\"text\":\"\"}]}，共 3 版。")
    user = ("把下面这条爆款文案的结构迁移成 3 版可直接照读的【%s】，"
            "换一个具体题材，不要抄原句，保留原片的节奏和转折位置。\n"
            "每版 150-300 字，口语化，不要书面语，不要 emoji。\n\n"
            "标题：%s\n结构卡：\n%s\n\n原文：\n%s") % (name, task.get("title") or "", secs, src)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def llm_versions(task: dict, structure: dict, style: str, key: dict) -> list[dict]:
    base = (key.get("base_url") or "").rstrip("/")
    if not base:
        raise RewriteError("LLM_BASE_URL_MISSING")
    try:
        api_key = decrypt(key["cipher"])
    except Exception as e:
        raise RewriteError("LLM_KEY_DECRYPT_FAILED") from e
    try:
        with httpx.Client(timeout=60) as client:
            r = client.post(base + "/chat/completions",
                            headers={"Authorization": "Bearer " + api_key},
                            json={"model": key.get("model") or "gpt-4o-mini",
                                  "messages": _prompt(task, structure, style),
                                  "temperature": 0.8, "max_tokens": 1400})
    except httpx.TimeoutException as e:
        raise RewriteError("LLM_TIMEOUT") from e
    except Exception as e:
        raise RewriteError("LLM_NETWORK") from e
    if r.status_code >= 300:
        raise RewriteError("LLM_%s" % r.status_code)
    try:
        content = r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        raise RewriteError("LLM_BAD_RESPONSE") from e
    content = content.strip().strip("`")
    if content.startswith("json"):
        content = content[4:].strip()
    start, end = content.find("{"), content.rfind("}")
    try:
        data = json.loads(content[start:end + 1])
    except Exception as e:
        raise RewriteError("LLM_BAD_JSON") from e
    items = data.get("versions") or []
    out = []
    for it in items[:3]:
        text = (it.get("text") or "").strip()
        if not text:
            continue
        out.append({"style": style, "name": STYLES.get(style, {}).get("name", "二创"),
                    "title": (it.get("title") or task.get("title") or "二创稿").strip(),
                    "text": text})
    if not out:
        raise RewriteError("LLM_EMPTY")
    return out


def generate(task: dict, structure: dict, style: str = "oral", key: dict | None = None) -> dict:
    style = style if style in STYLES else "oral"
    if key:
        try:
            return {"engine": "llm", "versions": llm_versions(task, structure, style, key)}
        except RewriteError as e:
            return {"engine": "template", "fallback": str(e),
                    "versions": template_versions(task, structure, style)}
    return {"engine": "template", "versions": template_versions(task, structure, style)}
