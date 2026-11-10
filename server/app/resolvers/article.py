import re
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from ..config import HTTP_PROXY, USER_AGENT


async def resolve(url: str) -> dict:
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9"}
    kwargs = {"timeout": 25, "follow_redirects": True, "headers": headers}
    if HTTP_PROXY:
        kwargs["proxy"] = HTTP_PROXY
    async with httpx.AsyncClient(**kwargs) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        html = resp.text

    soup = BeautifulSoup(html, "html.parser")
    node = soup.select_one("#js_content") or soup.select_one(".rich_media_content")
    if node is None:
        raise ValueError("ARTICLE_BLOCKED")

    for tag in node.select("script,style,svg,noscript"):
        tag.decompose()
    blocks = []
    for el in node.find_all(["p", "section", "h1", "h2", "h3", "li", "blockquote"]):
        text = el.get_text(" ", strip=True)
        if text and (not blocks or blocks[-1] != text):
            blocks.append(text)
    text = "\n".join(blocks).strip()
    if len(text) < 30:
        text = node.get_text("\n", strip=True)

    title_node = soup.select_one("#activity-name") or soup.select_one("meta[property='og:title']")
    author_node = soup.select_one("#js_name") or soup.select_one("meta[property='og:article:author']")
    cover_node = soup.select_one("meta[property='og:image']")
    title = (title_node.get("content") if title_node and title_node.name == "meta" else
             (title_node.get_text(strip=True) if title_node else "微信公众号文章"))
    author = (author_node.get("content") if author_node and author_node.name == "meta" else
              (author_node.get_text(strip=True) if author_node else ""))
    cover = cover_node.get("content", "") if cover_node else ""

    m = re.search(r'var\s+ct\s*=\s*"(\d{10})"', html)
    published = ""
    if m:
        published = datetime.fromtimestamp(int(m.group(1))).strftime("%Y-%m-%d %H:%M")

    return {
        "title": title.strip(),
        "author": author.strip(),
        "cover": cover,
        "published_at": published,
        "text": text,
        "paragraphs": blocks,
        "duration_sec": max(30, len(text) // 5),
    }
