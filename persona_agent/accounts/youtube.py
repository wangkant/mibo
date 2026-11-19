"""YouTube channels the person follows, read from their public feeds.

Nothing signs in. The person pastes channel links or handles once, or the
subscriptions.csv Google Takeout exports, and each becomes a channel id: a
handle or channel page names it in its canonical link, a video page in its
details. A look reads the public feed of each channel that is on and adds the
videos it has not seen as items, with YouTube's cookieless player.
"""
from __future__ import annotations

import asyncio
import csv
import logging
import re
import time
from datetime import datetime
from urllib.parse import urlsplit
from xml.etree import ElementTree

import httpx

from ..library import Library, item_id
from ..sources import base as sources_base, catalog
from ..sources.culture import _youtube_feed
from .base import AccountError, Connector, iso

logger = logging.getLogger("agent.accounts.youtube")

FEED = "https://www.youtube.com/feeds/videos.xml"
TAKEOUT = "https://takeout.google.com/settings/takeout/custom/youtube"
HOSTS = ("youtube.com", "youtu.be")
# Past YouTube's cookie question in Europe, so the channel page itself answers.
COOKIES = {"SOCS": "CAI"}
PASTE_MAX = 500_000
CHANNELS_MAX = 1000
LOOKUPS_MAX = 50
# A feed changes slowly and YouTube caches it: each channel at most this often,
# and a look reads at most this many, the longest unread first.
READ_EVERY_S = 30 * 60
PER_LOOK = 40
AT_ONCE = 6
# A channel read for the first time brings only its videos from these last days.
FIRST_DAYS = 3
FIRST_MAX = 2
_ID = re.compile(r"UC[\w-]{22}")
_CANONICAL = re.compile(r'<link rel="canonical" href="https://www\.youtube\.com/channel/(UC[\w-]{22})"')
_VIDEO_CHANNEL = re.compile(r'"videoDetails":\{[^{}]*?"channelId":"(UC[\w-]{22})"')
_ATOM = "{http://www.w3.org/2005/Atom}"


def _moment(text: str) -> float:
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return 0.0


def wanted(text: str) -> tuple[list[tuple[str, str]], list[str]]:
    """What was pasted: channel ids with the name a Takeout CSV gives them, and the addresses to look up."""
    ids, lookups = [], []
    for line in text.splitlines():
        found = _ID.search(line)
        if found:
            cells = next(csv.reader([line]))
            ids.append((found.group(0), cells[2].strip() if len(cells) >= 3 else ""))
        elif line.count(",") < 2:       # the CSV's header line has no id
            lookups += [address for word in line.split() if (address := page_for(word))]
    return ids, lookups


def page_for(word: str) -> str:
    """The YouTube page a pasted word names: a link as it is, "@name" or "name" as a handle; else ""."""
    word = word.strip().strip("<>\"'")
    if "/" in word or "." in word:
        address = word if "://" in word else "https://" + word
        host = (urlsplit(address).hostname or "").lower()
        return address if any(host == h or host.endswith("." + h) for h in HOSTS) else ""
    return f"https://www.youtube.com/@{word.lstrip('@')}" if word.lstrip("@") else ""


def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=sources_base.TIMEOUT_S, headers=sources_base.HEADERS, cookies=COOKIES,
                             follow_redirects=True)


async def channel_of(http: httpx.AsyncClient, address: str) -> str:
    """The channel id behind a YouTube page, "" when it names none."""
    answer = await http.get(address)
    if answer.status_code != 200 or not any(
            answer.url.host == h or answer.url.host.endswith("." + h) for h in HOSTS):
        return ""
    found = _CANONICAL.search(answer.text) or _VIDEO_CHANNEL.search(answer.text)
    return found.group(1) if found else ""


async def feed_title(http: httpx.AsyncClient, channel: str) -> str:
    """The channel's name from its feed; "" when it has no feed."""
    answer = await http.get(FEED, params={"channel_id": channel})
    if answer.status_code != 200:
        return ""
    return (ElementTree.fromstring(answer.content).findtext(f"{_ATOM}title") or "").strip() or channel


class YouTube(Connector):
    key = "youtube"
    name = ("YouTube", "YouTube")
    how = "paste"
    reads = ("Only the public video lists of the channels you paste; it never signs in to YouTube "
             "and cannot see your account, history or private videos.",
             "只读你贴进来的频道公开的视频列表；不登录 YouTube，看不到你的账号、观看记录或私享视频。")
    errors = frozenset({"youtube_invalid", "youtube_not_found", "youtube_unreachable"})

    def _state(self) -> dict:
        state = self.load()
        state.setdefault("channels", [])
        return state

    async def start(self, values: dict) -> dict:
        text = str(values.get("channels") or "").strip()
        if not text:
            return {"fields": [{"key": "channels", "secret": False, "multiline": True,
                                "label": ("Channel links or handles, one per line", "频道链接或账号名，每行一个"),
                                "help": ("Such as @veritasium or a channel's address. To bring every channel you "
                                         "subscribe to, export YouTube from Google Takeout (the link opens it) and "
                                         "paste the subscriptions.csv inside.",
                                         "例如 @veritasium 或频道地址。想一次带上全部订阅，用 Google Takeout 导出 "
                                         "YouTube（链接直接打开），把里面的 subscriptions.csv 内容贴进来。")}],
                    "link": TAKEOUT}
        if len(text) > PASTE_MAX:
            raise AccountError("youtube_invalid")
        ids, lookups = wanted(text)
        if not ids and not lookups:
            raise AccountError("youtube_invalid")
        gate = asyncio.Semaphore(AT_ONCE)

        async def look_up(address: str) -> tuple[str, str]:
            async with gate:
                channel = await channel_of(http, address)
                return (channel, await feed_title(http, channel)) if channel else ("", "")

        try:
            async with client() as http:
                looked = await asyncio.gather(*(look_up(a) for a in lookups[:LOOKUPS_MAX]))
        except (httpx.HTTPError, ElementTree.ParseError):
            raise AccountError("youtube_unreachable") from None
        found = ids + [(c, title) for c, title in looked if c and title]
        if len(lookups) > LOOKUPS_MAX:
            logger.info("youtube: %d addresses past the first %d were not looked up", len(lookups) - LOOKUPS_MAX,
                        LOOKUPS_MAX)
        if not found:
            raise AccountError("youtube_not_found")

        def put(state: dict) -> None:
            channels = state.setdefault("channels", [])
            known = {c["id"] for c in channels}
            for channel, title in found:
                if channel not in known and len(channels) < CHANNELS_MAX:
                    channels.append({"id": channel, "name": title or channel, "on": True, "read": 0, "newest": ""})
                    known.add(channel)
            state["error"] = ""

        await asyncio.to_thread(self.change, put)
        return {"done": True}

    async def poll(self) -> dict:
        return {"state": "done" if self._state()["channels"] else "pending", "error": ""}

    async def look(self) -> int:
        now = time.time()
        due = sorted((c for c in (await asyncio.to_thread(self._state))["channels"]
                      if c["on"] and now - c["read"] >= READ_EVERY_S), key=lambda c: c["read"])[:PER_LOOK]
        if not due:
            return 0
        gate = asyncio.Semaphore(AT_ONCE)

        async def read(channel: dict) -> tuple[str, list, str]:
            """(channel id, its new finds, the newest video's moment), or None finds when the feed did not answer."""
            async with gate:
                try:
                    answer = await http.get(FEED, params={"channel_id": channel["id"]})
                    answer.raise_for_status()
                    finds = _youtube_feed(answer.text)
                except (httpx.HTTPError, ElementTree.ParseError):
                    return channel["id"], None, channel["newest"]
            newest = max((f.item.published for f in finds), key=_moment, default=channel["newest"])
            if channel["newest"]:
                new = [f for f in finds if _moment(f.item.published) > _moment(channel["newest"])]
            else:
                new = [f for f in finds if _moment(f.item.published) > now - FIRST_DAYS * 86400][:FIRST_MAX]
            return channel["id"], new, newest

        async with client() as http:
            read_now = await asyncio.gather(*(read(c) for c in due))
            known = await asyncio.to_thread(self.known)
            covers = asyncio.Semaphore(AT_ONCE)
            finds = [f for _, new, _ in read_now for f in new or [] if item_id(f.item.url) not in known]
            pictures = await asyncio.gather(*(catalog._covered(http, f, covers) for f in finds))

        def keep() -> int:
            library = Library(self.runtime())
            items = []
            for found, picture in zip(finds, pictures):
                item = found.item
                item.id = item_id(item.url)
                # Found when it came out, so the feed's freshness follows the channel; a clock ahead counts as now.
                item.seen_at = int(min(_moment(item.published) or now, now))
                if picture:
                    item.picture = library.save_picture(item.id, picture)
                items.append(item)
            return self.keep_items(items)

        kept = await asyncio.to_thread(keep)
        answered = {cid: newest for cid, new, newest in read_now if new is not None}

        def record(state: dict) -> None:
            for channel in state.get("channels", []):
                if channel["id"] in answered:
                    channel.update(read=int(now), newest=answered[channel["id"]])
            state["last"] = int(now)
            state["error"] = "" if answered else "youtube_unreachable"

        await asyncio.to_thread(self.change, record)
        logger.info("youtube: %d of %d channels answered, %d new videos", len(answered), len(due), kept)
        return kept

    def view(self) -> dict:
        state = self._state()
        channels = state["channels"]
        names = [c["name"] for c in channels]
        account = ", ".join(names[:3]) + (f" +{len(names) - 3}" if len(names) > 3 else "")
        return {"connected": bool(channels), "account": account, "last": iso(state.get("last")),
                "problem": state.get("error", "") if channels else "", "ready": True,
                "choices": [{"id": c["id"], "name": c["name"], "on": c["on"]} for c in channels]}

    async def choose(self, on: list[str]) -> None:
        chosen = set(on)

        def turn(state: dict) -> None:
            for channel in state.get("channels", []):
                channel["on"] = channel["id"] in chosen

        await asyncio.to_thread(self.change, turn)

    async def revoke(self) -> None:
        # What it already brought stays in the feed, like the mail's.
        await asyncio.to_thread(self.forget)
