"""Bilibili, Weibo and Zhihu: the person's own follow feed, read in a browser they signed in to.

Connecting opens a window of the app's own (the installed Edge, Chrome or
Chromium with a profile kept for this, see direct/browser.py) on the site's
sign-in page, where the person signs in as they always do, usually by scanning
the site's QR code with its app. Once the site's sign-in cookie is there the
window closes and the sign-in stays in that profile.

A look opens the follow feed in that browser and reads what the site's own page
loads for itself as it shows the feed, so nothing here signs or calls the
sites' APIs. Each new post or video becomes one library item. Nothing is
posted, liked or followed. When a site signs the person out or wants a
verification, the look stops and the page says so.
"""
from __future__ import annotations

import asyncio
import logging
import re
import shutil
import time
from datetime import datetime, timezone
from typing import Any, Optional

from ..direct import base as direct_base, browser as web
from ..library import Item, item_id
from ..roam import player_for
from .base import AccountError, Connector, iso

logger = logging.getLogger("agent.accounts.sites")

# A feed is read at most this often; a person checks theirs now and then.
EVERY_S = 30 * 60
# The sign-in window waits this long for the person.
SIGN_IN_S = 10 * 60
# What a page loads keeps coming for a moment after the first answer.
LOAD_S = 20
SETTLE_S = 2.5
# A feed read for the first time shows only its last two days.
FIRST_DAYS = 2
TITLE_MAX = 120
EXCERPT_MAX = 600
_TAGS = re.compile(r"<[^>]+>")


def plain(text: Any) -> str:
    """Without markup, each line's spaces made one; the lines kept."""
    lines = (" ".join(line.split()) for line in _TAGS.sub(" ", str(text or "")).splitlines())
    return "\n".join(line for line in lines if line)


def first_line(text: str) -> str:
    return plain(text.strip().split("\n", 1)[0])[:TITLE_MAX]


def utc(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat() if seconds else ""


def seconds_of(clock: str) -> Optional[int]:
    """"1:02:03" or "12:34" as seconds."""
    parts = str(clock or "").split(":")
    if not all(p.isdigit() for p in parts) or not 1 < len(parts) < 4:
        return None
    total = 0
    for part in parts:
        total = total * 60 + int(part)
    return total


def _errors(key: str) -> frozenset:
    return frozenset(f"{key}_{code}" for code in (
        "browser_missing", "browser_support_missing", "browser_start_failed", "window_closed",
        "expired", "signed_out", "page_changed"))


class Site(Connector):
    """One site read through its own pages. A subclass names its pages and reads its feed's data."""

    how = "browser"
    every = EVERY_S
    #: Where the person signs in; the cookie that says they did, and where it is set.
    sign_in_url = ""
    cookie_url = ""
    signed_in_cookies: tuple[str, ...] = ()
    #: The feed's page, and parts of the addresses its data and its account come from.
    feed_url = ""
    feed_part = ""
    who_part = ""
    who_script = ""

    def __init__(self, workspace):
        super().__init__(workspace)
        self._window: Optional[web.Browser] = None
        self._deadline = 0.0

    def profile(self):
        return web.profile_path(self.ws.home, f"account-{self.key}")

    def error(self, problem: BaseException) -> AccountError:
        """The site's own code for a browser that would not start."""
        code = {web.NO_BROWSER: "browser_missing", web.NO_DRIVER: "browser_support_missing"}.get(
            str(problem), "browser_start_failed")
        return AccountError(f"{self.key}_{code}")

    # -- what a subclass reads

    def who(self, answers: list) -> str:
        """The signed-in account's name in what the page loaded, or ""."""
        return ""

    def items(self, answers: list) -> list[Item]:
        raise NotImplementedError

    # -- connecting

    async def start(self, values: dict) -> dict:
        await self._close_window()
        window = web.Browser(self.profile(), headless=False)
        try:
            context = await window.start()
            page = context.pages[0] if context.pages else await context.new_page()
            # The browser starts minimised for the looks; this window is for the person.
            cdp = await context.new_cdp_session(page)
            found = await cdp.send("Browser.getWindowForTarget")
            await cdp.send("Browser.setWindowBounds", {"windowId": found["windowId"],
                                                       "bounds": {"windowState": "normal"}})
            await page.goto(self.sign_in_url, wait_until="domcontentloaded")
            await page.bring_to_front()
        except (direct_base.Refused, ConnectionError) as problem:
            await window.stop()
            raise self.error(problem) from None
        except Exception:
            await window.stop()
            raise AccountError(f"{self.key}_browser_start_failed") from None
        self._window, self._deadline = window, time.monotonic() + SIGN_IN_S
        # Not the system browser: the window is already open, and the page waits on poll.
        return {"window": self.sign_in_url}

    async def _signed_in(self, context: Any) -> str:
        """The value of the site's sign-in cookie, or ""."""
        for cookie in await context.cookies(self.cookie_url):
            if cookie["name"] in self.signed_in_cookies and cookie["value"]:
                return cookie["value"]
        return ""

    async def poll(self) -> dict:
        window = self._window
        if window is None:
            return {"state": "failed", "error": f"{self.key}_window_closed"}
        try:
            signed = await self._signed_in(window.context)
        except Exception:
            # The person closed the window.
            await self._close_window()
            return {"state": "failed", "error": f"{self.key}_window_closed"}
        if not signed:
            if time.monotonic() < self._deadline:
                return {"state": "pending", "error": ""}
            await self._close_window()
            return {"state": "expired", "error": f"{self.key}_expired"}
        # Closed the way its close button does, so the sign-in reaches the profile.
        await self._close_window()
        await asyncio.to_thread(self.change, lambda s: (s.clear(), s.update(
            connected=True, account="", last=0, error="", since=0)))
        return {"state": "done", "error": ""}

    async def _close_window(self) -> None:
        window, self._window = self._window, None
        if window is not None:
            await window.stop()

    async def close(self) -> None:
        await self._close_window()

    # -- reading

    async def _read(self, page: Any) -> tuple[list, list]:
        """What the feed's page loads for itself as it opens: its feed data and its account data."""
        feed: list = []
        who: list = []
        pending: list[asyncio.Task] = []

        async def keep(into: list, response: Any) -> None:
            try:
                into.append(await response.json())
            except Exception:
                pass            # not JSON after all

        def heard(response: Any) -> None:
            if response.ok and self.feed_part in response.url:
                pending.append(asyncio.ensure_future(keep(feed, response)))
            elif response.ok and self.who_part and self.who_part in response.url:
                pending.append(asyncio.ensure_future(keep(who, response)))

        page.on("response", heard)
        try:
            await page.goto(self.feed_url, wait_until="domcontentloaded")
            deadline = time.monotonic() + LOAD_S
            while not feed and time.monotonic() < deadline:
                if pending:
                    await asyncio.wait(pending, timeout=1)
                await asyncio.sleep(0.25)
            await asyncio.sleep(SETTLE_S)
            if pending:
                await asyncio.wait(pending, timeout=5)
        finally:
            page.remove_listener("response", heard)
        return feed, who

    async def look(self) -> int:
        state = await asyncio.to_thread(self.load)
        if not state.get("connected") or self._window is not None:
            return 0
        browser = web.Browser(self.profile())
        problem, account, found = "", "", []
        try:
            context = await browser.start()
            if not await self._signed_in(context):
                problem = f"{self.key}_signed_out"
            else:
                page = context.pages[0] if context.pages else await context.new_page()
                feed, who = await self._read(page)
                account = self.who(who)
                if not account and self.who_script:
                    account = plain(await page.evaluate(self.who_script))[:64]
                found = self.items(feed)
                if not await self._signed_in(context):
                    problem = f"{self.key}_signed_out"
                elif not feed:
                    problem = f"{self.key}_page_changed"
        except (direct_base.Refused, ConnectionError) as error:
            problem = str(self.error(error))
        except Exception as error:
            logger.warning("%s: a look failed (%s)", self.key, type(error).__name__)
            problem = f"{self.key}_page_changed"
        finally:
            await browser.stop()
        now = time.time()
        # Since a little before the last look, or the last two days the first time.
        floor = (state.get("since") or now) - FIRST_DAYS * 86400
        for item in found:
            item.seen_at = min(item.seen_at or int(now), int(now))

        def keep() -> int:
            known = self.known()
            return self.keep_items([item for item in found
                                    if item.seen_at >= floor and item_id(item.url) not in known])

        kept = await asyncio.to_thread(keep)

        def record(saved: dict) -> None:
            if not saved.get("connected"):
                return          # revoked while this look read
            saved.update(error=problem, account=account or saved.get("account", ""))
            if not problem:
                saved.update(last=int(now), since=int(now))

        await asyncio.to_thread(self.change, record)
        logger.info("%s: a look kept %d new posts%s", self.key, kept, f" ({problem})" if problem else "")
        return kept

    def view(self) -> dict:
        state = self.load()
        return {"connected": bool(state.get("connected")), "account": state.get("account", ""),
                "last": iso(state.get("last")), "problem": state.get("error", ""), "ready": True, "choices": []}

    async def revoke(self) -> None:
        await self._close_window()
        await asyncio.to_thread(self.forget)
        # The sign-in goes with its profile.
        profile = self.profile()
        await asyncio.to_thread(web.end_profile, profile)
        await asyncio.to_thread(shutil.rmtree, profile, True)


def _warn(site: str, zh: str) -> tuple[str, str]:
    return (f"This opens {site} in a browser window of personagent's own, where you sign in yourself. "
            f"personagent then reads your {site} follow feed in that window now and then, the way you would "
            f"scroll it. {site} does not offer this to apps; it may ask you to verify or sign in again, "
            f"and, rarely, limit an account that is read this way. Nothing is posted, liked or followed.",
            f"这会在 personagent 自己的浏览器窗口里打开{zh}，由你亲自登录。之后 personagent 会隔一阵在那个窗口里看一看"
            f"你在{zh}关注的动态，就像你自己刷一样。{zh}并没有为应用提供这种读取方式，它可能要你验证或重新登录，"
            f"也有很小的可能限制这样被读取的账号。不会发帖、点赞或关注。")


# ------------------------------------------------------------------ Bilibili --

def _bili_item(entry: dict) -> Optional[Item]:
    modules = entry.get("modules") or {}
    author = modules.get("module_author") or {}
    dynamic = modules.get("module_dynamic") or {}
    words = plain((dynamic.get("desc") or {}).get("text"))
    origin = entry.get("orig") if entry.get("type") == "DYNAMIC_TYPE_FORWARD" else None
    if origin:
        # A repost: the thing reposted, with what the reposter said in front.
        found = _bili_item(origin)
        if found is not None:
            said = f"{plain(author.get('name'))}: {words}" if words else ""
            found.description = " · ".join(p for p in (said, found.description) if p)[:EXCERPT_MAX]
            found.seen_at = int(author.get("pub_ts") or 0) or found.seen_at
        return found
    major = dynamic.get("major") or {}
    at = int(author.get("pub_ts") or 0)
    common = {"site": "哔哩哔哩", "author": plain(author.get("name"))[:120], "published": utc(at), "seen_at": at,
              "fits": False, "why": ""}
    archive, article, opus = major.get("archive"), major.get("article"), major.get("opus")
    if archive and archive.get("bvid"):
        url = f"https://www.bilibili.com/video/{archive['bvid']}"
        return Item(url=url, kind="video", title=plain(archive.get("title"))[:TITLE_MAX],
                    description=" · ".join(p for p in (words, plain(archive.get("desc"))) if p)[:EXCERPT_MAX],
                    length=seconds_of(archive.get("duration_text")), embed=player_for(url), **common)
    if article and article.get("id"):
        return Item(url=f"https://www.bilibili.com/read/cv{article['id']}", kind="article",
                    title=plain(article.get("title"))[:TITLE_MAX], description=plain(article.get("desc"))[:EXCERPT_MAX],
                    **common)
    if opus:
        words = plain((opus.get("summary") or {}).get("text")) or words
        title = plain(opus.get("title")) or first_line(words)
    else:
        title = first_line(words)
    if not entry.get("id_str") or not (title or words):
        return None     # a live room, a deleted post, an ad
    return Item(url=f"https://t.bilibili.com/{entry['id_str']}", kind="post", title=title or words[:TITLE_MAX],
                description=words[:EXCERPT_MAX], **common)


class Bilibili(Site):
    key = "bilibili"
    errors = _errors("bilibili")
    name = ("Bilibili", "哔哩哔哩")
    warn = _warn("Bilibili", "哔哩哔哩")
    reads = ("New videos, articles and posts from the people you follow, from your follow feed; not your "
             "messages, comments or history.",
             "你关注的人发的新视频、专栏和动态，读自你的关注动态；读不到私信、评论和观看记录。")
    sign_in_url = "https://passport.bilibili.com/login"
    cookie_url = "https://www.bilibili.com/"
    signed_in_cookies = ("DedeUserID",)
    feed_url = "https://t.bilibili.com/"
    feed_part = "/x/polymer/web-dynamic/v1/feed/all"
    who_part = "/x/web-interface/nav"

    def who(self, answers: list) -> str:
        for answer in answers:
            data = (answer or {}).get("data") or {}
            if data.get("isLogin") and data.get("uname"):
                return plain(data["uname"])[:64]
        return ""

    def items(self, answers: list) -> list[Item]:
        found = [_bili_item(entry) for answer in answers
                 for entry in ((answer or {}).get("data") or {}).get("items") or []]
        return [item for item in found if item is not None]


# --------------------------------------------------------------------- Weibo --

def _weibo_time(text: str) -> int:
    try:
        return int(datetime.strptime(str(text), "%a %b %d %H:%M:%S %z %Y").timestamp())
    except ValueError:
        return 0


def _weibo_item(status: dict) -> Optional[Item]:
    user = status.get("user") or {}
    if not (user.get("idstr") and status.get("mblogid")) or status.get("promotion"):
        return None     # an ad, or something not a post
    words = plain(status.get("text_raw") or status.get("text"))
    shared = status.get("retweeted_status") or {}
    if shared:
        name = plain((shared.get("user") or {}).get("screen_name"))
        words = " // ".join(p for p in (words, f"@{name}: " + plain(shared.get("text_raw") or shared.get("text"))) if p)
    page = status.get("page_info") or shared.get("page_info") or {}
    video = page.get("object_type") == "video"
    at = _weibo_time(status.get("created_at"))
    duration = (page.get("media_info") or {}).get("duration")
    return Item(url=f"https://weibo.com/{user['idstr']}/{status['mblogid']}", site="微博",
                kind="video" if video else "post",
                title=(plain(page.get("page_title")) if video else "") or first_line(words) or "微博",
                author=plain(user.get("screen_name"))[:120], description=words[:EXCERPT_MAX],
                length=int(duration) if video and isinstance(duration, (int, float)) else None,
                published=utc(at), seen_at=at, fits=False, why="")


class Weibo(Site):
    key = "weibo"
    errors = _errors("weibo")
    name = ("Weibo", "微博")
    warn = _warn("Weibo", "微博")
    reads = ("New posts from the people you follow, from your home feed; not your messages, comments or likes.",
             "你关注的人发的新微博，读自你的首页；读不到私信、评论和点赞。")
    sign_in_url = "https://passport.weibo.com/sso/signin?entry=miniblog&source=miniblog&url=https%3A%2F%2Fweibo.com%2F"
    cookie_url = "https://weibo.com/"
    signed_in_cookies = ("ALF", "SSOLoginState")
    feed_url = "https://weibo.com/"
    feed_part = "friendstimeline"
    # The home page names the account in its own config, not in what it loads.
    who_script = "() => String((window.$CONFIG && window.$CONFIG.user && window.$CONFIG.user.screen_name) || '')"

    def items(self, answers: list) -> list[Item]:
        found = [_weibo_item(status) for answer in answers for status in (answer or {}).get("statuses") or []]
        return [item for item in found if item is not None]


# --------------------------------------------------------------------- Zhihu --

def _zhihu_item(entry: dict) -> Optional[Item]:
    target = entry.get("target") or {}
    kind, ident = target.get("type"), target.get("id")
    if not ident:
        return None
    question = target.get("question") or {}
    author = plain((target.get("author") or {}).get("name"))
    if kind == "answer" and question.get("id"):
        url, form, title = f"https://www.zhihu.com/question/{question['id']}/answer/{ident}", "article", question.get("title")
    elif kind == "article":
        url, form, title = f"https://zhuanlan.zhihu.com/p/{ident}", "article", target.get("title")
    elif kind == "zvideo":
        url, form, title = f"https://www.zhihu.com/zvideo/{ident}", "video", target.get("title")
    elif kind == "question":
        url, form, title = f"https://www.zhihu.com/question/{ident}", "page", target.get("title")
    elif kind == "pin":
        url, form, title = f"https://www.zhihu.com/pin/{ident}", "post", target.get("excerpt_title")
    else:
        return None     # an ad, a live, a topic
    at = int(entry.get("created_time") or target.get("created_time") or target.get("created") or 0)
    # Who of the people followed did it: wrote it, or agreed with it.
    action = plain(entry.get("action_text"))
    excerpt = plain(target.get("excerpt") or target.get("description"))
    actors = ", ".join(plain(a.get("name")) for a in entry.get("actors") or [] if isinstance(a, dict) and a.get("name"))
    return Item(url=url, site="知乎", kind=form, title=plain(title)[:TITLE_MAX] or first_line(excerpt) or "知乎",
                author=author[:120],
                description=" · ".join(p for p in (f"{actors} {action}".strip(), excerpt) if p)[:EXCERPT_MAX],
                published=utc(at), seen_at=at, fits=False, why="")


class Zhihu(Site):
    key = "zhihu"
    errors = _errors("zhihu")
    name = ("Zhihu", "知乎")
    warn = _warn("Zhihu", "知乎")
    reads = ("New answers, articles, videos and questions from the people you follow, from your follow feed; "
             "not your messages, notifications or votes.",
             "你关注的人新写或赞同的回答、文章、视频和问题，读自你的关注动态；读不到私信、通知和投票。")
    sign_in_url = "https://www.zhihu.com/signin?next=%2Ffollow"
    cookie_url = "https://www.zhihu.com/"
    signed_in_cookies = ("z_c0",)
    feed_url = "https://www.zhihu.com/follow"
    feed_part = "/api/v3/moments"
    who_part = "/api/v4/me"

    def who(self, answers: list) -> str:
        for answer in answers:
            if isinstance(answer, dict) and answer.get("name") and answer.get("url_token") is not None:
                return plain(answer["name"])[:64]
        return ""

    def items(self, answers: list) -> list[Item]:
        entries = []
        for answer in answers:
            for entry in (answer or {}).get("data") or []:
                # A group of the same kind of thing comes as one entry holding the rest.
                entries += (entry.get("list") or []) if entry.get("type") == "feed_group" else [entry]
        found = [_zhihu_item(entry) for entry in entries if isinstance(entry, dict)]
        return [item for item in found if item is not None]
