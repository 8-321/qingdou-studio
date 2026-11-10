import re

RULES = {
    "hook": {"label": "钩子", "slot": "0-3s", "patterns": [r"如果", r"你有没有", r"为什么", r"别再", r"千万别", r"我发现", r"99%"]},
    "pain": {"label": "痛点", "slot": "前 1/3", "patterns": [r"是不是", r"有没有", r"还在", r"总是", r"每次", r"以为", r"难怪"]},
    "proof": {"label": "证据", "slot": "全篇", "patterns": [r"\d", r"万", r"倍", r"案例", r"数据", r"实测", r"对比"]},
    "turn": {"label": "转折", "slot": "中段", "patterns": [r"但是", r"但", r"其实", r"直到", r"真正", r"问题不在", r"反过来"]},
    "cta": {"label": "CTA", "slot": "结尾", "patterns": [r"评论区", r"关注", r"主页", r"私信", r"下单", r"收藏", r"点赞", r"链接"]},
}


def _first(segs: list[dict], patterns: list[str], start_idx: int = 0) -> int:
    for i in range(start_idx, len(segs)):
        t = segs[i]["text"]
        if any(re.search(p, t) for p in patterns):
            return i
    return -1


def build(segs: list[dict]) -> dict:
    if not segs:
        return {"score": 0, "sections": [], "summary": "内容为空"}

    hook_idx = 0
    pain_idx = _first(segs, RULES["pain"]["patterns"], 1)
    proof_idx = _first(segs, RULES["proof"]["patterns"], 1)
    turn_idx = _first(segs, RULES["turn"]["patterns"], 1)
    cta_idx = _first(segs, RULES["cta"]["patterns"], max(0, len(segs) // 2))

    if pain_idx < 0:
        pain_idx = min(len(segs) - 1, 2)
    if turn_idx < 0:
        turn_idx = min(len(segs) - 1, max(0, len(segs) // 2))
    if cta_idx < 0:
        cta_idx = len(segs) - 1

    hook_strength = 60 + (18 if re.search(r"\d", segs[hook_idx]["text"]) else 0) \
        + (10 if re.search(r"如果|别再|千万", segs[hook_idx]["text"]) else 0)
    hook_strength = min(98, hook_strength)
    proof_strength = 45 + min(40, len(re.findall(r"\d+", " ".join(s["text"] for s in segs))) * 4)
    turn_strength = 55 + (25 if turn_idx > 1 else 0)
    cta_strength = 50 + (25 if re.search(r"评论区|主页|私信", segs[cta_idx]["text"]) else 10)
    score = round(hook_strength * 0.3 + proof_strength * 0.25 + turn_strength * 0.2 + cta_strength * 0.25)

    sections = [
        {
            "key": "hook", "label": "钩子", "slot": _slot(segs[hook_idx]),
            "text": segs[hook_idx]["text"], "strength": int(hook_strength),
            "why": "用一个具体的失败场景把目标人群圈出来，再把原因指向反常识的位置，制造继续看下去的理由。",
            "template": "如果你【做了 N 次】还是【没结果】，问题不在【表面原因】，在【反常识原因】。",
        },
        {
            "key": "pain", "label": "痛点", "slot": _slot(segs[pain_idx]),
            "text": segs[pain_idx]["text"], "strength": 78,
            "why": "复述观众正在发生的具体行为，比抽象描述更容易让人对号入座。",
            "template": "你是不是也这样：【具体场景】，结果【具体损失】。",
        },
        {
            "key": "proof", "label": "证据", "slot": _slot(segs[proof_idx]),
            "text": segs[proof_idx]["text"], "strength": int(proof_strength),
            "why": "数字让观点可被验证。若加入第三方案例，可信度还能再上一档。",
            "template": "我实测了【N】个样本，只有【M】个做对了，差距在【关键变量】。",
        },
        {
            "key": "turn", "label": "转折", "slot": _slot(segs[turn_idx]),
            "text": segs[turn_idx]["text"], "strength": int(turn_strength),
            "why": "先承认表层原因，再抬到更高维度，是知识类口播最稳的转折句式。",
            "template": "但真正的问题不是【表层原因】，是你没有【更高维度的缺失】。",
        },
        {
            "key": "cta", "label": "CTA", "slot": _slot(segs[cta_idx]),
            "text": segs[cta_idx]["text"], "strength": int(cta_strength),
            "why": "行动成本越低、回报越具体，转化越高。'点赞关注'是最弱的一种。",
            "template": "把【低成本动作】发在评论区，我挑【N】个【具体回报】。",
        },
    ]
    return {
        "score": int(score),
        "sections": sections,
        "summary": f"钩子强、结构完整，{len(segs)} 句，预估信息密度中等偏上。",
        "paragraphs": len(segs),
    }


def _slot(seg: dict) -> str:
    s = int(seg.get("start", 0))
    return f"{s // 60}:{s % 60:02d}"
