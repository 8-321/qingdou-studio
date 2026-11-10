import re

FILLERS = ["嗯", "啊", "呃", "那个", "就是", "然后呢", "对吧", "你知道吧", "怎么说呢"]
SENT_END = re.compile(r"(?<=[。！？!?；;])\s*")


def clean_text(raw: str) -> str:
    if not raw:
        return ""
    text = raw.replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    for filler in FILLERS:
        text = re.sub(rf"(?<=[，。！？\s]){filler}(?=[，。！？\s])", "", text)
    text = re.sub(r"(，){2,}", "，", text)
    text = re.sub(r"\s+([，。！？；])", r"\1", text)
    return text.strip()


def split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in SENT_END.split(text) if p and p.strip()]
    if len(parts) <= 1:
        parts = [p.strip() for p in re.split(r"(?<=[，,])", text) if p.strip()]
    return parts


def to_paragraphs(sentences: list[str], per_para: int = 4) -> list[str]:
    return ["".join(sentences[i:i + per_para]) for i in range(0, len(sentences), per_para)]
