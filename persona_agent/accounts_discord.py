"""The person's own Discord as a source, read through a bot they add to their servers.

Reading a person's account with their own token breaks Discord's terms and
gets accounts banned, so the person makes an application in the developer
portal, turns on its Message Content intent, pastes the bot's token here and
invites the bot to the servers they want read, with View Channels and Read
Message History only. The token is kept in the home's .env as
DISCORD_READ_TOKEN; the bot, its servers and channels, and where each channel
was last read, in `<runtime>/discord.json`.

A look reads the new messages of every channel that is on over REST and keeps
each stretch of conversation (messages less than an hour apart) as one item in
the library, opening at its first message. A stretch that mentions or answers
the person counts as one the character thinks fits them. What was said enters
the library only while the person lets the character read their messages
(privacy.py); otherwise only how many came and from whom is said, on this computer.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import threading
import time
import weakref
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import httpx

from . import privacy, quiet
from .direct.discord import API
from .direct.base import plain_name
from .library import Item
from .storage import atomic_write_text

logger = logging.getLogger("agent.discord")

ENV_KEY = "DISCORD_READ_TOKEN"
STATE_FILE = "discord.json"
PORTAL = "https://discord.com/developers/applications"
USER_AGENT = "DiscordBot (personagent, 1)"
TIMEOUT_S = 20
VIEW_CHANNEL, READ_HISTORY, ADMINISTRATOR = 1 << 10, 1 << 16, 1 << 3
# All the invite asks for: seeing channels and reading what was said in them.
INVITE_PERMISSIONS = VIEW_CHANNEL | READ_HISTORY
# The application flags Discord sets while the Message Content intent is on (verified bots, and the rest).
CONTENT_FLAGS = (1 << 18) | (1 << 19)
TEXT_CHANNELS = (0, 5)              # text, announcement
SPOKEN = (0, 19, 20)                # a message, a reply, an answer to a slash command
EPOCH_MS = 1420070400000            # Discord's snowflakes count from 2015
# A look soon after the app starts, then this often; the server list at most this often.
FIRST_LOOK_S = 20
LOOK_EVERY_S = 5 * 60
SERVERS_EVERY_S = 30 * 60
# A channel read for the first time shows only its last two days.
FIRST_DAYS = 2
PAGE = 50
PAGES_MAX = 4                       # a busy channel catches up over the next looks
# Messages further apart than this start a new stretch; a stretch is never longer than SPAN_MAX_S.
GAP_S = 60 * 60
SPAN_MAX_S = 6 * 60 * 60
LINES_MAX = 8
LINE_MAX = 200
EXCERPT_MAX = 600
TOKEN_MAX = 200
# This many messages with nothing in them, and none with words: Discord is withholding the words.
EMPTY_MIN = 3
WAIT_MAX_S = 60
_TOKEN = re.compile(r"[A-Za-z0-9._-]+")
_TAG = re.compile(r"<(@!?|@&|#)(\d+)>|<a?:(\w+):\d+>")

# The state is written from the page's worker threads and from the looks.
_lock = threading.Lock()


class DiscordError(ValueError):
    """What went wrong, by its code: discord_invalid, discord_not_connected,
    discord_token_invalid, discord_intent_missing, discord_unreachable or
    discord_failed. A ValueError, so the page answers it by its code."""


class NoAccess(Exception):
    """A server or channel the bot cannot read now (403 or 404)."""


# ------------------------------------------------------------------ the state --

def state_path(runtime: Path) -> Path:
    return Path(runtime) / STATE_FILE


def blank_state() -> dict:
    return {"bot": {"id": "", "name": ""}, "app": "", "owner": "", "servers": [], "channels": {},
            "synced": 0, "last": 0, "error": ""}


def load_state(runtime: Path) -> dict:
    try:
        saved = json.loads(state_path(runtime).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    state = blank_state()
    if isinstance(saved, dict):
        state.update({k: saved[k] for k in state if k in saved and type(saved[k]) is type(state[k])})
    return state


def change_state(runtime: Path, change: Callable[[dict], None]) -> dict:
    with _lock:
        state = load_state(runtime)
        change(state)
        atomic_write_text(state_path(runtime), json.dumps(state, ensure_ascii=False, indent=1))
        return state


def forget(runtime: Path) -> None:
    with _lock:
        state_path(runtime).unlink(missing_ok=True)


def clean_token(raw) -> str:
    """The token as pasted, without a "Bot " in front; DiscordError("discord_invalid") when it cannot be one."""
    token = str(raw or "").strip()
    token = token[4:].strip() if token.lower().startswith("bot ") else token
    if not token or len(token) > TOKEN_MAX or not _TOKEN.fullmatch(token):
        raise DiscordError("discord_invalid")
    return token


def invite(app_id: str) -> str:
    return (f"https://discord.com/oauth2/authorize?client_id={app_id}&scope=bot"
            f"&permissions={INVITE_PERMISSIONS}")


def bot_page(app_id: str) -> str:
    """The application's Bot page in the portal, where the intent and the token are."""
    return f"{PORTAL}/{app_id}/bot"


def jump(guild: str, channel: str, message: str) -> str:
    return f"https://discord.com/channels/{guild}/{channel}/{message}"


def snowflake_at(seconds: float) -> int:
    return (int(seconds * 1000) - EPOCH_MS) << 22


def moment(snowflake) -> float:
    return ((int(snowflake) >> 22) + EPOCH_MS) / 1000


# ----------------------------------------------------------------------- REST --

def client(token: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=TIMEOUT_S, headers={"Authorization": f"Bot {token}", "User-Agent": USER_AGENT})


async def rest(http: httpx.AsyncClient, path: str, params: Optional[dict] = None):
    """GET `path`, waiting out the rate limits; never hands back what Discord said on a failure."""
    for _ in range(5):
        try:
            response = await http.get(API + path, params=params)
        except httpx.HTTPError:
            raise DiscordError("discord_unreachable") from None
        if response.status_code == 429:
            try:
                wait = float(response.json().get("retry_after") or 2)
            except ValueError:      # Cloudflare's own limit answers in HTML
                wait = float(response.headers.get("retry-after") or 5)
            await asyncio.sleep(min(wait, WAIT_MAX_S))
            continue
        if response.status_code == 401:
            raise DiscordError("discord_token_invalid")
        if response.status_code in (403, 404):
            raise NoAccess()
        if response.status_code >= 400:
            raise DiscordError("discord_failed")
        # The last request this bucket allows for now: wait before the next one rather than after a 429.
        if response.headers.get("x-ratelimit-remaining") == "0":
            await asyncio.sleep(min(float(response.headers.get("x-ratelimit-reset-after") or 1), WAIT_MAX_S))
        try:
            return response.json()
        except ValueError:
            raise DiscordError("discord_failed") from None
    raise DiscordError("discord_unreachable")


async def identify(http: httpx.AsyncClient) -> dict:
    """The bot, its application, who owns it, and whether the Message Content intent is on."""
    try:
        me = await rest(http, "/users/@me")
        app = await rest(http, "/applications/@me")
    except NoAccess:
        raise DiscordError("discord_token_invalid") from None
    team = app.get("team") or {}
    owner = str(team.get("owner_user_id") or (app.get("owner") or {}).get("id") or "")
    return {"bot": {"id": str(me["id"]), "name": plain_name(me.get("global_name"), me.get("username"), str(me["id"]))},
            "app": str(app.get("id") or me["id"]), "owner": owner,
            "content": bool(int(app.get("flags") or 0) & CONTENT_FLAGS)}


def permissions(guild: str, bot: str, member_roles: list, roles: list, overwrites: list) -> int:
    """What the bot may do in one channel: its roles, then the channel's overwrites in Discord's order."""
    by_id = {str(r["id"]): int(r.get("permissions") or 0) for r in roles}
    allowed = by_id.get(guild, 0)
    mine = {str(r) for r in member_roles}
    for role in mine:
        allowed |= by_id.get(role, 0)
    if allowed & ADMINISTRATOR:
        return ~0
    by_target = {str(o["id"]): o for o in overwrites}

    def apply(value: int, allow: int, deny: int) -> int:
        return (value & ~deny) | allow

    if guild in by_target:
        o = by_target[guild]
        allowed = apply(allowed, int(o.get("allow") or 0), int(o.get("deny") or 0))
    allow = deny = 0
    for o in overwrites:
        if int(o.get("type", 0)) == 0 and str(o["id"]) in mine:
            allow |= int(o.get("allow") or 0)
            deny |= int(o.get("deny") or 0)
    allowed = apply(allowed, allow, deny)
    if bot in by_target and int(by_target[bot].get("type", 1)) == 1:
        o = by_target[bot]
        allowed = apply(allowed, int(o.get("allow") or 0), int(o.get("deny") or 0))
    return allowed


async def servers(http: httpx.AsyncClient, bot: str) -> list[dict]:
    """The servers the bot is in, each with the text channels it can read."""
    found = []
    try:
        guilds = await rest(http, "/users/@me/guilds")
    except NoAccess:
        raise DiscordError("discord_failed") from None
    for guild in guilds:
        gid = str(guild["id"])
        try:
            roles = await rest(http, f"/guilds/{gid}/roles")
            member = await rest(http, f"/guilds/{gid}/members/{bot}")
            channels = await rest(http, f"/guilds/{gid}/channels")
        except NoAccess:
            continue
        readable = [c for c in channels if c.get("type") in TEXT_CHANNELS
                    and permissions(gid, bot, member.get("roles") or [], roles, c.get("permission_overwrites") or [])
                    & (VIEW_CHANNEL | READ_HISTORY) == VIEW_CHANNEL | READ_HISTORY]
        readable.sort(key=lambda c: (int(c.get("position") or 0), int(c["id"])))
        found.append({"id": gid, "name": str(guild.get("name") or gid)[:100],
                      "channels": [{"id": str(c["id"]), "name": str(c.get("name") or c["id"])[:100]}
                                   for c in readable]})
    return found


def merge_servers(state: dict, found: list[dict], now: float) -> None:
    """The servers as found now; a channel seen for the first time is off until the person turns it on."""
    known = state["channels"]
    state["channels"] = {c["id"]: known.get(c["id"]) or {"on": False} for s in found for c in s["channels"]}
    state["servers"] = found
    state["synced"] = int(now)


async def new_messages(http: httpx.AsyncClient, channel: str, after: str, now: float) -> tuple[list[dict], str]:
    """The channel's messages since `after`, oldest first, and where the next read starts.
    With no `after` yet: its last messages from the last FIRST_DAYS."""
    if not after:
        page = await rest(http, f"/channels/{channel}/messages", {"limit": PAGE})
        floor = snowflake_at(now - FIRST_DAYS * 86400)
        newest = max((int(m["id"]) for m in page), default=snowflake_at(now))
        return sorted((m for m in page if int(m["id"]) > floor), key=lambda m: int(m["id"])), str(newest)
    got: list[dict] = []
    for _ in range(PAGES_MAX):
        page = sorted(await rest(http, f"/channels/{channel}/messages", {"after": after, "limit": PAGE}),
                      key=lambda m: int(m["id"]))
        got.extend(page)
        if page:
            after = str(page[-1]["id"])
        if len(page) < PAGE:
            break
    return got, after


# ------------------------------------------------------------------- messages --

def speaker(author: dict) -> str:
    return plain_name(author.get("global_name"), author.get("username"), str(author.get("id") or ""))


def _mentions(message: dict, bot: str) -> bool:
    return any(str(m.get("id")) == bot for m in message.get("mentions") or [])


def empty(message: dict, bot: str) -> bool:
    """A person's message that came back with nothing in it, as Discord sends them without the intent."""
    return (message.get("type", 0) in (0, 19) and not (message.get("author") or {}).get("bot")
            and not _mentions(message, bot)
            and not any(message.get(k) for k in ("content", "attachments", "embeds", "sticker_items",
                                                 "message_snapshots", "poll", "components")))


def words(message: dict, channels: dict[str, str]) -> str:
    """What one message says, on one line: its words with mentions named, else what it carries."""
    body = message
    if not message.get("content") and message.get("message_snapshots"):
        body = (message["message_snapshots"][0] or {}).get("message") or {}
    names = {str(m.get("id")): speaker(m) for m in body.get("mentions") or [] if isinstance(m, dict)}

    def name(match: re.Match) -> str:
        kind, ident, emoji = match.groups()
        if emoji:
            return f":{emoji}:"
        if kind == "#":
            return "#" + channels.get(ident, ident)
        return "@" + (names.get(ident, "") if kind != "@&" else "")

    parts = [_TAG.sub(name, str(body.get("content") or ""))]
    if not parts[0].strip():
        parts += [str(e.get("title") or e.get("description") or "") for e in body.get("embeds") or []]
    # A file is named as one, never by its name.
    parts += ["[file]" for _ in body.get("attachments") or []]
    parts += [str(s.get("name") or "") for s in body.get("sticker_items") or []]
    return " ".join(" ".join(parts).split())[:LINE_MAX]


def stretches(current: Optional[dict], messages: list[dict], *, bot: str, owner: str,
              channels: dict[str, str]) -> tuple[list[dict], Optional[dict]]:
    """The stretches `messages` (oldest first) add to or begin, and the one still open after them.
    `current` is the stretch left open by the last look; it goes on when they follow it closely."""
    touched: list[dict] = []
    for message in messages:
        author = message.get("author") or {}
        if str(author.get("id")) == bot or message.get("type", 0) not in SPOKEN:
            continue
        line = words(message, channels)
        if not line:
            continue
        at = moment(message["id"])
        if current is None or at - current["end"] > GAP_S or at - current["start"] > SPAN_MAX_S:
            current = {"first": str(message["id"]), "start": at, "end": at, "lines": [], "names": [],
                       "count": 0, "others": False, "mentioned": False}
        if not touched or touched[-1] is not current:
            touched.append(current)
        who = speaker(author)
        current["end"] = at
        current["count"] += 1
        if len(current["lines"]) < LINES_MAX:
            current["lines"].append(f"{who}: {line}")
        if who not in current["names"]:
            current["names"].append(who)
        if str(author.get("id")) != owner:
            current["others"] = True
            quoted = (message.get("referenced_message") or {}).get("author") or {}
            if owner and (_mentions(message, owner) or str(quoted.get("id")) == owner):
                current["mentioned"] = True
    return touched, current


def to_item(stretch: dict, guild: str, server: str, channel: str, channel_name: str, now: float) -> Item:
    start = datetime.fromtimestamp(stretch["start"], timezone.utc)
    return Item(url=jump(guild, channel, stretch["first"]), site=f"Discord · {server}"[:80], kind="post",
                title=f"#{channel_name} · {server}"[:200], author=", ".join(stretch["names"][:3])[:120],
                description=" · ".join(stretch["lines"])[:EXCERPT_MAX], published=start.isoformat(),
                # Found when it was said, so the feed's freshness follows the talk; a clock ahead counts as now.
                seen_at=min(int(stretch["end"]), int(now)), fits=stretch["mentioned"], why="")


# ------------------------------------------------------------------------ looks --

class Looks:
    """A look soon after start, then every LOOK_EVERY_S, and at once when asked.
    The token and the runtime are read again for each look, so a change counts."""

    def __init__(self, token: Callable[[], str], runtime: Callable[[], Path], config: Callable[[], dict]):
        self.token, self.runtime, self.config = token, runtime, config
        self.running = False
        self._wake = asyncio.Event()
        # A look asked for by a page waits for the loop's, so two never move the same channels.
        self._one = asyncio.Lock()

    def ask(self) -> None:
        self._wake.set()

    @property
    def busy(self) -> bool:
        return self.running or self._wake.is_set()

    async def sync(self, http: httpx.AsyncClient, bot: str) -> dict:
        found = await servers(http, bot)
        now = time.time()

        def put(state: dict) -> None:
            if state["bot"]["id"] == bot:
                merge_servers(state, found, now)

        return await asyncio.to_thread(change_state, self.runtime(), put)

    async def look(self) -> int:
        """Read every channel that is on; how many stretches were kept or grew."""
        async with self._one:
            return await self._look()

    async def _look(self) -> int:
        token, runtime = self.token(), self.runtime()
        state = await asyncio.to_thread(load_state, runtime)
        bot = state["bot"]["id"]
        if not token or not bot:
            return 0
        now = time.time()
        try:
            async with client(token) as http:
                known = await identify(http)
                if known["bot"]["id"] != bot:
                    raise DiscordError("discord_token_invalid")
                if not known["content"]:
                    raise DiscordError("discord_intent_missing")
                if now - state["synced"] > SERVERS_EVERY_S:
                    state = await self.sync(http, bot)
                read: dict[str, tuple[list, str]] = {}
                for cid, record in state["channels"].items():
                    if not record.get("on"):
                        continue
                    try:
                        read[cid] = await new_messages(http, cid, str(record.get("after") or ""), now)
                    except NoAccess:
                        logger.info("discord: a channel could not be read")
        except DiscordError as error:
            logger.info("discord: a look failed (%s)", error)
            await asyncio.to_thread(change_state, runtime, lambda s, code=str(error): s.update(error=code)
                                    if s["bot"]["id"] == bot else None)
            return 0
        every = [m for messages, _ in read.values() for m in messages]
        blank = sum(1 for m in every if empty(m, bot))
        spoken = sum(1 for m in every if not empty(m, bot) and not (m.get("author") or {}).get("bot")
                     and m.get("type", 0) in (0, 19) and not _mentions(m, bot))
        if blank >= EMPTY_MIN and not spoken:
            # Nothing is moved on, so these are read again once the intent is back.
            await asyncio.to_thread(change_state, runtime, lambda s: s.update(error="discord_intent_missing")
                                    if s["bot"]["id"] == bot else None)
            return 0
        where = {c["id"]: (s["id"], s["name"], c["name"]) for s in state["servers"] for c in s["channels"]}
        names = {cid: name for cid, (_, _, name) in where.items()}
        items, moved = [], {}
        for cid, (messages, after) in read.items():
            touched, still = stretches(state["channels"][cid].get("open"), messages, bot=bot,
                                       owner=known["owner"], channels=names)
            guild, server, channel_name = where[cid]
            items += [to_item(s, guild, server, cid, channel_name, now) for s in touched if s["others"]]
            moved[cid] = (after, still)

        values = await asyncio.to_thread(self.config)
        await asyncio.to_thread(privacy.keep, runtime, values, items, "message")

        def record(state: dict) -> None:
            if state["bot"]["id"] != bot:
                return          # forgotten or replaced while this look read
            for cid, (after, still) in moved.items():
                if cid in state["channels"]:
                    state["channels"][cid].update(after=after, open=still)
            state.update(last=int(now), error="", owner=known["owner"])

        await asyncio.to_thread(change_state, runtime, record)
        logger.info("discord: a look at %d channels kept %d stretches", len(read), len(items))
        return len(items)

    async def _wait(self, seconds: float) -> None:
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._wake.wait(), seconds)
        self._wake.clear()

    async def loop(self) -> None:
        await self._wait(FIRST_LOOK_S)
        while True:
            await quiet.wait()
            self.running = True
            try:
                await self.look()
            except Exception:
                logger.exception("discord: a look failed")
            finally:
                self.running = False
            await self._wait(LOOK_EVERY_S)


# The Discord panel and the accounts panel read the same bot: one Looks per home serves both.
_shared: "weakref.WeakKeyDictionary[object, Looks]" = weakref.WeakKeyDictionary()


def looks_for(workspace) -> Looks:
    if workspace not in _shared:
        _shared[workspace] = Looks(lambda: workspace.config().get(ENV_KEY, ""), workspace._runtime, workspace.config)
    return _shared[workspace]
