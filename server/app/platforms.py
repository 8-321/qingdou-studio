import re
from dataclasses import dataclass
from urllib.parse import urlparse

URL_RE = re.compile(r"https?://[^\s<>'\"，。！？、）)】]+", re.I)
BARE_RE = re.compile(
    r"(?<![\w./])((?:v\.douyin\.com|v\.kuaishou\.com|xhslink\.com|b23\.tv|youtu\.be)/[A-Za-z0-9_\-./?=&%]+)",
    re.I,
)

PLATFORMS = [
    ("wechat_article", r"(^|\.)mp\.weixin\.qq\.com$"),
    ("wechat_channels", r"(^|\.)channels\.weixin\.qq\.com$|(^|\.)finder\.video\.qq\.com$"),
    ("douyin", r"(^|\.)douyin\.com$|(^|\.)iesdouyin\.com$"),
    ("kuaishou", r"(^|\.)kuaishou\.com$|(^|\.)chenzhongtech\.com$"),
    ("xiaohongshu", r"(^|\.)xiaohongshu\.com$|(^|\.)xhslink\.com$"),
    ("bilibili", r"(^|\.)bilibili\.com$|(^|\.)b23\.tv$"),
    ("weibo", r"(^|\.)weibo\.com$|(^|\.)weibo\.cn$"),
    ("ixigua", r"(^|\.)ixigua\.com$"),
    ("youtube", r"(^|\.)youtube\.com$|(^|\.)youtu\.be$"),
    ("tiktok", r"(^|\.)tiktok\.com$"),
    ("instagram", r"(^|\.)instagram\.com$"),
    ("twitter", r"(^|\.)twitter\.com$|(^|\.)x\.com$"),
]

SUPPORTED = {
    "wechat_article": "微信公众号文章",
    "wechat_channels": "微信视频号（需上传）",
    "douyin": "抖音",
    "kuaishou": "快手",
    "xiaohongshu": "小红书",
    "bilibili": "B站",
    "weibo": "微博",
    "ixigua": "西瓜视频",
    "youtube": "YouTube",
    "tiktok": "TikTok",
    "instagram": "Instagram",
    "twitter": "X / Twitter",
    "upload": "本地上传",
}


@dataclass
class Target:
    platform: str
    url: str


def extract_url(text: str) -> str:
    text = (text or "").strip()
    m = URL_RE.search(text)
    if m:
        return m.group(0).rstrip(".,;:!?)）】")
    m = BARE_RE.search(text)
    if m:
        return "https://" + m.group(1)
    return ""


def detect(text: str) -> Target:
    url = extract_url(text)
    if not url:
        return Target("unknown", "")
    host = (urlparse(url).hostname or "").lower()
    for name, pattern in PLATFORMS:
        if re.search(pattern, host):
            return Target(name, url)
    return Target("unknown", url)
