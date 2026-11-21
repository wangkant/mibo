"""A public page read for a chat reply: fetched plainly first, read again rendered when the fetch is thin.

The search assistants fetch a page first and fall back to a rendered read; Jina Reader and Firecrawl render
with a headless browser. Here the plain fetch comes first (about a second for an article), and the same
address is read again, in the same reply, in the signed-out visitor browser (roam.Visitor: the installed
Edge or Chrome, headless, its own profile) when the fetch was refused, came back a script's shell, held
little text for its size, or lacked the list the question is for. The rendered read takes the text from the
live DOM with reader.js, scrolls a screen for a lazy list and ends by RENDER_S (web/read.py); a check, a
sign-in or an error stops it as it stops any read, and nothing is clicked or sent.
"""
from __future__ import annotations

import asyncio
import logging
import re
from html.parser import HTMLParser
from typing import Any, Optional

from ..ingestion import safe_fetch_url
from . import read as reading

logger = logging.getLogger("mibo.web")

# The plain fetch: its time, and how much of a page it takes (a long article's page runs to a few megabytes).
FETCH_S = 8.0
FETCH_MAX = 4 * 1024 * 1024
# The rendered read: all of it, the browser's start included, and a screen scrolled for a list that shows
# fewer than LIST_ROWS rows.
RENDER_S = 12.0
LIST_SCREENS, LIST_ROWS = 1, 15
# A fetch is thin below SHELL characters of text, or under SPARSE of a page longer than SPARSE_FROM; a list
# is lacking with fewer than LIST_LINKS links that carry words.
SHELL = 400
SPARSE, SPARSE_FROM = 0.02, 50_000
LIST_LINKS = 12
ROWS_SHOWN = 50
# Words that ask for a list: a ranking, what is on a page now (what a person types; copy: voice).
_LISTY = re.compile(r"热搜|热点|热榜|热门|热帖|最热|排行|榜|前十|前几|前\d+|有哪些|有什么|有啥|都有|列表|最新|几条|"
                    r"\b(?:top|trending|popular|rank(?:ing)?|list|latest|new(?:est)?|which|front page|leaderboard)\b",
                    re.I)
_LINK = re.compile(r"<a\b[^>]*>(.*?)</a>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")


class _PageText(HTMLParser):
    """A page's title and readable text, without its scripts, styles and chrome."""

    _SKIP = {"script", "style", "noscript", "svg", "template", "nav", "footer", "header", "form", "aside"}
    _BREAK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article", "pre"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title, self.parts, self._skip, self._in_title = "", [], 0, False

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag in self._BREAK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)

    def text(self) -> str:
        lines = (" ".join(line.split()) for line in "".join(self.parts).splitlines())
        return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def listy(said: str) -> bool:
    """Whether the person's message asks for a list."""
    return bool(_LISTY.search(said or ""))


def thin(status: int, html: str, text: str, wants_list: bool) -> str:
    """Why a plain fetch is not the page as a person sees it ("" when it is): refused, a shell, sparse
    text for its size, or no list where one is asked for."""
    if status >= 400:
        return "refused"
    if len(text) < SHELL:
        return "shell"
    if len(html) > SPARSE_FROM and len(text) < SPARSE * len(html):
        return "sparse"
    if wants_list and sum(1 for words in _LINK.findall(html) if len(_TAG.sub("", words).strip()) >= 4) < LIST_LINKS:
        return "no_list"
    return ""


async def plain(agent: Any, url: str) -> Optional[tuple[int, str, str, str, str]]:
    """(status, html, title, text, final address) of a plain fetch; None when it failed or may not be made
    (every redirect hop is checked to be public)."""
    from .sites import TOKEN
    from ..sources.base import HEADERS
    result = await safe_fetch_url(
        url, timeout=FETCH_S, max_wire_bytes=FETCH_MAX, max_decoded_bytes=2 * FETCH_MAX,
        headers={**HEADERS, "User-Agent": f"{HEADERS['User-Agent']} {TOKEN}",
                 "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"},
        allowed_content_types=("text/html", "application/xhtml+xml"), require_content_type=True,
        client_factory=agent.__dict__.get("_http"))
    if result is None:
        return None
    charset = re.search(r"charset=([\w-]+)", str(result.headers.get("content-type") or ""), re.I)
    try:
        html = result.content.decode(charset.group(1) if charset else "utf-8", errors="replace")
    except LookupError:
        html = result.content.decode("utf-8", errors="replace")
    page = _PageText()
    page.feed(html)
    return result.status_code, html, " ".join(page.title.split())[:300], page.text(), result.url


async def _warm(roam: Any) -> None:
    """The visitor browser started, while the plain fetch runs, so a rendered read after it begins at once."""
    try:
        async with roam.visitor.lock:
            await roam.visitor._open()
    except Exception as exc:
        logger.info("[Agent] the visitor browser did not start: %s", type(exc).__name__)


def _rows(rows: list) -> str:
    """A list's rows as numbered lines: title, author, time and counts."""
    lines = []
    for row in rows[:ROWS_SHOWN]:
        counts = row.get("counts") if isinstance(row.get("counts"), dict) else {}
        bits = [" ".join(str(row.get(k) or "").split())[:200] for k in ("title", "author", "time")]
        bits.append(" ".join(f"{k} {v}" for k, v in list(counts.items())[:4]))
        if bits[0]:
            lines.append(f"{len(lines) + 1}. " + " | ".join(b for b in bits if b))
    return "\n".join(lines)


async def rendered(roam: Any, url: str, wants_list: bool) -> Optional[tuple[str, str, str]]:
    """(title, text, final address) of `url` read in the visitor browser by RENDER_S; None for a wall, a
    private address or nothing read. A list asked for that shows few rows is scrolled a screen."""
    from ..roam import facts_from
    if not await roam.public(url):
        return None
    until = asyncio.get_running_loop().time() + RENDER_S - 2
    async with roam.visitor.tab() as tab:
        page = await reading.read(tab, url, within_s=until - asyncio.get_running_loop().time())
        if wants_list and page.kind == "list" and len(page.rows) < LIST_ROWS and not page.wall:
            more = await reading.read(tab, url, here=True, screens=LIST_SCREENS,
                                      within_s=until - asyncio.get_running_loop().time())
            rows = {}
            reading.merge(rows, page.rows)
            reading.merge(rows, more.rows)
            page.rows = list(rows.values())
    if not await roam.public(page.url):
        return None
    facts = facts_from(page.data, page.url)
    text = facts.get("text") or str(page.data.get("text") or "")
    if page.wall in ("verification", "sign_in", "error", "dead", "robots") or (page.wall and not page.rows and not text):
        logger.info("[Agent] read_page rendered: a %s wall (%s)", page.wall, page.evidence or "-")
        return None
    shown = page.kind == "list" or (page.kind != "item" and len(page.rows) >= 5)
    body = "\n\n".join(b for b in (_rows(page.rows) if shown else "", facts.get("description"), text) if b)
    if not body:
        return None
    return facts.get("title") or str(page.data.get("title") or ""), body, page.url


async def for_chat(agent: Any, url: str, wants_list: bool = False) -> Optional[tuple[str, str, str]]:
    """(title, readable text, final address) of a public page, or None when it cannot or may not be read: the
    plain fetch, else, when that is thin and a visitor browser is there (started while the fetch runs), the
    rendered read, and the fetch's text when that read is not to be had."""
    roam = getattr(agent, "roam", None)
    usable = roam is not None and not roam.available()
    if usable and roam.visitor.context is None:
        asyncio.ensure_future(_warm(roam))
    fetched = await plain(agent, url)
    if fetched is not None and reading.wall_at(fetched[4]):
        # Sent to a sign-in or a check: a browser is sent there too, and a wall is not got around.
        return None
    why = "failed" if fetched is None else thin(fetched[0], fetched[1], fetched[3], wants_list)
    kept = None if fetched is None or fetched[0] >= 400 or len(fetched[3]) < SHELL else fetched[2:]
    if not why or not usable:
        return kept
    try:
        seen = await asyncio.wait_for(rendered(roam, url, wants_list), RENDER_S)
    except asyncio.TimeoutError:
        seen = None
    except Exception as exc:
        # The browser itself failed: what the fetch brought stands.
        logger.warning("[Agent] the visitor browser could not read a page: %s", type(exc).__name__)
        seen = None
    logger.info("[Agent] read_page: plain fetch %s, rendered read %s", why, "used" if seen else "none")
    return seen or kept
