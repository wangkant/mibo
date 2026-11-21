"""Reading any page: an address in, its rows, its content or the wall it shows out.

`read(tab, url)` opens the address in the tab, waits for the page to settle,
runs reader.js (with Mozilla's Readability for an article's text) and, for a
list, scrolls a few screens and merges the rows by link. No model is called.
With `runtime` the host's card (sites.py) is asked first and told after: an
address known dead, a wall still in its back-off, or for a background read a
path the site's robots.txt keeps from Mibo, is not loaded at all.

Walls, first match wins: the address is a sign-in or check page; the page is
gone (404, 410 or a page saying it was not found: "dead", that address only);
the browser or the site refused the page; reader.js saw a check, a sign-in, an
error, a sign-in layer in front of the page or nothing at all. Nothing gets
around a wall: a check is never waited on or clicked, a layer never closed.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

from .tabs import Tab, TabError

logger = logging.getLogger("mibo.web")

_HERE = Path(__file__).parent
# reader.js with Mozilla's Readability 0.6.0 (Readability.js, vendored unchanged) in scope: one function of opts.
READER = ("(opts) => {\n" + (_HERE / "Readability.js").read_text(encoding="utf-8")
          + "\nreturn (" + (_HERE / "reader.js").read_text(encoding="utf-8") + ")(opts, Readability);\n}")
# A list is settled when the element count and the text length are unchanged for STILL looks POLL_S apart,
# at most SETTLE_S; an item when nothing in the document changed for QUIET_MS, at most ITEM_S (Jina Reader's
# mutation idle; waiting for requests too added 0.4 s a page and never ended on pages that keep beaconing).
SETTLE_S = 12.0
POLL_S = 0.5
STILL = 3
ITEM_S = 5.0
QUIET_MS = 500
QUIET_POLL_S = 0.2
# Screens scrolled on a list: a walk, the person's feed, a page asked about in chat.
WALK_SCREENS, FEED_SCREENS = 4, 3
SCROLL_PAUSE_S = 1.8
AFTER_SCROLL_S = 5.0
# A redirect after load replaces the document under a running script: tried again this often.
TRIES = 5
EVIDENCE_MAX = 80
# Walls after which the page is not scrolled: what is on screen is all that is read.
STOPS = ("verification", "sign_in", "error", "dead", "sign_in_overlay")
# Answers a bot check or a sign-in page often comes with: the page is read to say which it is.
_REFUSALS = (401, 403, 429, 503)
# Answers and page words that say this one address is gone.
_GONE = (404, 410)
_SETTLE = "() => [document.getElementsByTagName('*').length, document.body ? document.body.innerText.length : 0]"
# Milliseconds since the document last changed, watched from the first call on.
_QUIET = """() => {
  if (!window.__miboQuiet) {
    const seen = window.__miboQuiet = {at: performance.now()};
    new MutationObserver(() => { seen.at = performance.now(); })
      .observe(document, {childList: true, subtree: true, characterData: true});
  }
  return document.readyState === 'loading' ? 0 : performance.now() - window.__miboQuiet.at;
}"""
# Where a site sends a visitor it will not serve.
_CHECK_PATHS = ("/sorry/", "/captcha", "/challenge")
_SIGN_IN_PATHS = ("/login", "/signin", "/sign-in", "/passport", "/consent", "/account/login", "/accounts/login")
_SIGN_IN_HOSTS = ("passport.", "accounts.", "consent.", "login.", "signin.")


@dataclass
class Found:
    """One row of a list, as the walk and the sources hand it on."""
    url: str
    title: str
    site: str
    author: str = ""
    time: str = ""
    picture: str = ""
    counts: dict = field(default_factory=dict)
    text: str = ""


@dataclass
class Page:
    """What reading an address gave. `data` is reader.js's answer (empty for a wall met before it ran),
    `rows` its rows merged over the screens scrolled; `wall` is "" or the wall's kind."""
    url: str
    kind: str = ""
    rows: list = field(default_factory=list)
    data: dict = field(default_factory=dict)
    wall: str = ""
    evidence: str = ""
    status: int = 0


def wall_at(url: str) -> str:
    """"verification" or "sign_in" when `url` is where a site turns visitors away; "" otherwise."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return ""
    host, path = (parts.hostname or "").lower(), parts.path.lower()
    if any(mark in path for mark in _CHECK_PATHS):
        return "verification"
    if host.startswith(_SIGN_IN_HOSTS) or any(path.startswith(mark) for mark in _SIGN_IN_PATHS):
        return "sign_in"
    return ""


async def settle(tab: Tab, most_s: float = SETTLE_S) -> None:
    """Wait until the page stops changing, at most `most_s`."""
    last, still, start = None, 0, time.monotonic()
    while time.monotonic() - start < most_s:
        try:
            now = await tab.evaluate(_SETTLE)
        except Exception:
            # The page moved on (a redirect): wait for the new one.
            last, still = None, 0
            await asyncio.sleep(1.0)
            continue
        still = still + 1 if now == last else 0
        if still >= STILL:
            return
        last = now
        await asyncio.sleep(POLL_S)


async def quiet(tab: Tab, most_s: float = ITEM_S) -> None:
    """Wait until nothing in the page has changed for QUIET_MS, at most `most_s`."""
    start = time.monotonic()
    while time.monotonic() - start < most_s:
        try:
            if await tab.evaluate(_QUIET) >= QUIET_MS:
                return
        except Exception:
            # The page moved on (a redirect): wait for the new one.
            pass
        await asyncio.sleep(QUIET_POLL_S)


async def run_reader(tab: Tab, opts: Optional[dict] = None) -> dict:
    """reader.js's answer for the page as it is now."""
    for attempt in range(TRIES):
        try:
            data = await tab.evaluate(READER, opts or {})
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            # A document replaced mid-call (a redirect to a language's address) is read again once settled.
            if "destroyed" not in str(exc) and "navigat" not in str(exc) or attempt == TRIES - 1:
                raise
            await asyncio.sleep(3.0)
            await settle(tab)
    return {}


def merge(rows: dict, more: list) -> None:
    """`more` into `rows` (by link, else title): new rows added, a known row's empty fields filled."""
    for row in more:
        if not isinstance(row, dict):
            continue
        key = row.get("link") or row.get("title")
        if not key:
            continue
        old = rows.setdefault(key, row)
        for name, value in row.items():
            if value and not old.get(name):
                old[name] = value


def _wall(data: dict) -> tuple[str, str]:
    """The wall reader.js saw and its evidence."""
    wall = data.get("wall") if isinstance(data.get("wall"), dict) else {}
    kind, evidence = str(wall.get("kind") or ""), str(wall.get("evidence") or "")[:EVIDENCE_MAX]
    return kind, evidence


async def read(tab: Tab, url: str, *, screens: int = 0, here: bool = False, runtime: Optional[Path] = None,
               background: bool = False, mode: str = "signed_out", item: bool = False, within_s: float = 0.0) -> Page:
    """`url` read in `tab` (`here`: the page the tab is on, not loaded again). `screens` more screens are
    scrolled and merged for a list; an `item` page settles sooner. With `within_s`, the waits and the screens
    end by then and what was read so far is the answer. With `runtime`, the host's card is asked
    first (an address known dead, a wall in its back-off, and for a `background` read robots.txt, keep the
    page from loading) and told what the page showed."""
    from . import sites
    if runtime is not None and not here:
        held = sites.held(runtime, url, mode)
        if held:
            return Page(url, wall=held, evidence="remembered")
        if background and not await sites.robots_allow(runtime, tab, url):
            return Page(url, wall="robots", evidence="robots.txt")
    page = await _read(tab, url, screens=screens, here=here, item=item,
                       until=time.monotonic() + within_s if within_s else 0.0)
    if runtime is not None:
        sites.saw(runtime, page, mode, asked=url)
    return page


async def _read(tab: Tab, url: str, *, screens: int, here: bool, item: bool, until: float) -> Page:
    def left(most: float) -> float:
        # The wait `most`, cut to what is left before `until`.
        return max(0.0, min(most, until - time.monotonic())) if until else most

    found = wall_at(url)
    if found:
        return Page(url, wall=found, evidence="address")
    status = 0
    if not here:
        try:
            answer = await tab.goto(url)
        except TabError as exc:
            return Page(url, wall="error", evidence=str(exc)[:EVIDENCE_MAX])
        status = answer.status
        final = answer.url or tab.url
        found = wall_at(final)
        if found:
            return Page(final, wall=found, evidence="address", status=status)
        if status in _GONE:
            return Page(final, wall="dead", evidence=f"http {status}", status=status)
        if status >= 400 and status not in _REFUSALS:
            return Page(final, wall="error", evidence=f"http {status}", status=status)
        if answer.kind and "html" not in answer.kind and "xml" not in answer.kind:
            return Page(final, wall="error", evidence=f"not a page ({answer.kind[:40]})", status=status)
    await (quiet(tab, left(ITEM_S)) if item else settle(tab, left(SETTLE_S)))
    # An item page's article is read whatever lists sit beside it.
    opts = {"article": True} if item else {}
    try:
        data = await run_reader(tab, opts)
    except Exception as exc:
        return Page(tab.url, wall="error", evidence=f"unread ({type(exc).__name__})", status=status)
    kind, evidence = _wall(data)
    if status >= 400 and kind not in ("verification", "sign_in"):
        return Page(tab.url, wall="error", evidence=f"http {status}", status=status)
    if kind == "empty" and left(SETTLE_S):
        # An empty shell gets one more chance to draw: a longer settle and a screen.
        await settle(tab, left(SETTLE_S))
        await tab.scroll(1)
        await settle(tab, left(AFTER_SCROLL_S))
        data = await run_reader(tab, opts)
        kind, evidence = _wall(data)
    rows: dict = {}
    merge(rows, data.get("rows") or [])
    if data.get("kind") == "list" and kind not in STOPS:
        for _ in range(screens):
            if not left(SCROLL_PAUSE_S):
                break
            await tab.scroll(1)
            await asyncio.sleep(left(SCROLL_PAUSE_S))
            await settle(tab, left(AFTER_SCROLL_S))
            try:
                more = await run_reader(tab)
            except Exception:
                break
            merge(rows, more.get("rows") or [])
            more_kind, more_evidence = _wall(more)
            if more_kind in STOPS:
                # A wall that came up while scrolling ends the reading with what was seen before it.
                kind, evidence = more_kind, more_evidence
                break
    final = str(data.get("url") or tab.url)
    found = wall_at(final)
    if found:
        kind, evidence = found, "address"
    return Page(final, kind=str(data.get("kind") or ""), rows=list(rows.values()), data=data, wall=kind,
                evidence=evidence, status=status)


def found_rows(page: Page, site_of, *, shape_ok=None, limit: int = 40) -> list[Found]:
    """A list's rows as Found, each address once: `site_of(url)` names the site, `shape_ok(url)` (when given)
    keeps only rows whose link is shaped like the host's items."""
    out, seen = [], set()
    for row in page.rows:
        link, title = str(row.get("link") or ""), " ".join(str(row.get("title") or "").split())
        if not link.startswith(("http://", "https://")) or not title or link in seen:
            continue
        if shape_ok is not None and not shape_ok(link):
            continue
        seen.add(link)
        counts = row.get("counts") if isinstance(row.get("counts"), dict) else {}
        out.append(Found(link, title[:200], site_of(link), author=str(row.get("author") or "")[:80],
                         time=str(row.get("time") or "")[:40], picture=str(row.get("picture") or "")[:2000],
                         counts={str(k)[:20]: str(v)[:20] for k, v in list(counts.items())[:5]},
                         text=str(row.get("text") or "")[:300]))
        if len(out) >= limit:
            break
    return out


def trimmed(rows: list[Found], limit: int = 30) -> str:
    """Rows cut to title, author, time and counts (about 2k tokens at most) for a model to see."""
    lines = []
    for n, row in enumerate(rows[:limit], 1):
        bits = [row.title[:120], row.author, row.time, " ".join(f"{k} {v}" for k, v in row.counts.items())]
        lines.append(f"{n}. " + " | ".join(b for b in bits if b))
    return "\n".join(lines)

