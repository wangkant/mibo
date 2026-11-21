"""Hot lists and rankings a chat message asks for, read straight from where they are kept.

A message that names one of these lists ("今天的微博热点", "what's on Hacker News") gets the list itself as
data before the reply model's first round, the way the search assistants answer a known live list from
its source instead of searching for pages about it: the source's own public API where the catalogue
has one (china.py, tech.py), else the list's page, read for the chat (web/fetch.py: rendered when a script
draws it). Weibo's hot search turns a signed-out visitor to its visitor check, so it is read only with the
person's own session in the app's browser, where they signed in to Weibo there and let it be read
(browsed.read_signed_in). Rules only, no model: the message must name the site and ask for a list.
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from . import china, tech
from .base import client

logger = logging.getLogger("mibo.sources")

# Rows handed over, and the time the list may take (a page read rendered takes longest).
ROWS = 30
API_S = 6.0
PAGE_S = 20.0
# Words that ask for what is on a list now.
_ASKS = re.compile(r"热搜|热点|热榜|热门|热帖|热议|最热|排行|榜|趋势|首页|有什么|有哪些|有啥|上什么|今天.*(什么|哪些|啥)|"
                   r"\b(?:top|trending|hot|popular|front page|ranking|leaderboard|stories|today|right now|what'?s on)\b",
                   re.I)
_URL = re.compile(r"https?://[^\s<>\"'，。）)]+")


@dataclass(frozen=True)
class Live:
    name: tuple[str, str]                    # (English, Chinese)
    page: str                                # the list's own page
    sites: tuple[str, ...]                   # words naming the site, lower case
    fetch: Optional[Callable[[Any], Awaitable[list]]] = None   # the source's fetch; None: the page is read
    also: str = ""                           # what the message must hold too, beside the site's other list
    signed: bool = False                     # read only with the person's session, where they signed in


_BILI = ("b站", "b 站", "哔哩哔哩", "bilibili")
# First match wins: a site's narrower list before its general one.
LISTS = (
    Live(("Weibo hot search", "微博热搜"), "https://s.weibo.com/top/summary", ("微博", "weibo"), signed=True),
    Live(("Zhihu hot list", "知乎热榜"), "https://www.zhihu.com/hot", ("知乎", "zhihu"),
         partial(china._zhihu_hot, limit=ROWS)),
    Live(("Bilibili ranking", "B站排行榜"), "https://www.bilibili.com/v/popular/rank/all", _BILI,
         partial(china._bili_rank(0), limit=ROWS), also="排行|榜|rank"),
    Live(("Bilibili popular", "B站热门"), "https://www.bilibili.com/v/popular/all", _BILI,
         partial(china._bili_hot, limit=ROWS)),
    Live(("Tieba hot topics", "贴吧热议"), "https://tieba.baidu.com/hottopic/browse/topicList", ("贴吧", "tieba"),
         partial(china._tieba_hot, limit=ROWS)),
    Live(("Baidu hot search", "百度热搜"), "https://top.baidu.com/board?tab=realtime", ("百度", "baidu"),
         partial(china._baidu_hot, limit=ROWS)),
    Live(("Toutiao hot list", "今日头条热榜"), "https://www.toutiao.com/", ("头条", "toutiao"),
         partial(china._toutiao_hot, limit=ROWS)),
    Live(("V2EX hot", "V2EX 最热"), "https://www.v2ex.com/?tab=hot", ("v2ex",), partial(china._v2ex_hot, limit=ROWS)),
    Live(("Juejin hot list", "掘金热榜"), "https://juejin.cn/hot/articles", ("掘金", "juejin"),
         partial(tech._juejin, limit=ROWS)),
    Live(("Hacker News", "Hacker News"), "https://news.ycombinator.com/", ("hacker news", "hackernews"),
         partial(tech._hn_top, limit=ROWS)),
    Live(("GitHub trending", "GitHub 趋势"), "https://github.com/trending", ("github",),
         also="trending|趋势|热门|排行|榜|star"),
    Live(("Hugging Face trending models", "Hugging Face 热门模型"), "https://huggingface.co/models?sort=trending",
         ("hugging face", "huggingface"), tech._hf_models, also="model|模型"),
    Live(("Product Hunt", "Product Hunt"), "https://www.producthunt.com/", ("product hunt", "producthunt"),
         next(s.fetch for s in tech.SOURCES if s.key == "ph-today")),
    Live(("Lobsters", "Lobsters"), "https://lobste.rs/", ("lobsters", "lobste.rs"), tech._lobsters),
)


def asked(said: str) -> Optional[Live]:
    """The list the message asks for, or None. A message with an address asks for that page: a list only
    when the address is the list's own page."""
    low = (said or "").lower()
    if not _ASKS.search(low):
        return None
    named = _URL.search(low)
    if named:
        return next((live for live in LISTS if named.group(0).rstrip("/") == live.page.lower().rstrip("/")), None)
    return next((live for live in LISTS if any(site in low for site in live.sites)
                 and (not live.also or re.search(live.also, low))), None)


async def rows(agent: Any, live: Live, lang: str, home: Path) -> Optional[str]:
    """The list as numbered lines for the model, read now; None when it could not or may not be read in time."""
    title = live.name[1] if lang.startswith("zh") else live.name[0]
    try:
        if live.signed:
            from .. import browsed
            from ..search import _page_words
            from ..web import signin
            desktop = home / "runtime" / "desktop"
            if not (signin.signed_in(desktop, live.page) and signin.chose(desktop, live.page, "task")):
                return None
            page = await asyncio.wait_for(asyncio.to_thread(browsed.read_signed_in, home, live.page), PAGE_S)
            return None if page.get("error") else f"{title}, read just now with their session:\n{_page_words(page)}"
        if live.fetch is None:
            from ..web import fetch
            page = await asyncio.wait_for(fetch.for_chat(agent, live.page, wants_list=True), PAGE_S)
            return f"{title} ({page[2]}), read just now:\n\n{page[1]}" if page else None
        async with client() as http:
            found = await asyncio.wait_for(live.fetch(http), API_S)
    except Exception as exc:
        logger.info("[Agent] live list %s not read: %s", live.name[0], type(exc).__name__)
        return None
    lines = []
    for n, one in enumerate(found[:ROWS], 1):
        about = " ".join(one.item.description.split())[:80]
        lines.append(f"{n}. {one.item.title}" + (f" — {about}" if about else ""))
    return f"{title} ({live.page}), read just now, in its order:\n" + "\n".join(lines) if lines else None
