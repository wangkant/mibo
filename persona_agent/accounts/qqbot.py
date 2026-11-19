"""QQ as a source, read through an official QQ bot the person makes by a scan.

Nothing logs in as the person. The page shows QQ's scan-to-bind code (the flow
in direct/qq.py): the person scans it with mobile QQ and confirms, QQ makes a
bot or picks one of theirs, and the app gets its AppID and AppSecret by
itself. The AppID and AppSecret are kept in the home's .env as QQ_READ_APPID and
QQ_READ_SECRET; the groups seen, which are on, and the stretches still open, in
`<runtime>/accounts/qq.json`.

The bot listens on QQ's v2 gateway with GROUP_AND_C2C_EVENT: every message of
a group whose owner set the bot to 获取群内全部消息, the @-mentions of it in
other groups, and the messages sent to it privately. QQ keeps no history for
bots, so only what arrives while the app runs is heard. A look turns what was
heard into items: a stretch of one group's messages less than an hour apart is
one item, as Discord's are; a stretch that mentions the owner, or anything sent
to the bot privately, fits the person. Nothing heard here goes to a model or
anywhere but the library on this computer.
"""
from __future__ import annotations

import asyncio
import base64
import io
import logging
import os
import re
import time
from datetime import datetime, timezone
from urllib.parse import quote

import httpx

from ..direct import qq
from ..direct.base import Refused
from ..library import Item, item_id
from .base import AccountError, Connector, iso

logger = logging.getLogger("agent.accounts.qq")

ENV_APPID, ENV_SECRET = "QQ_READ_APPID", "QQ_READ_SECRET"
TIMEOUT_S = 20
# Messages further apart than this start a new stretch; a stretch is never longer than SPAN_MAX_S.
GAP_S = 60 * 60
SPAN_MAX_S = 6 * 60 * 60
LINES_MAX = 8
LINE_MAX = 200
EXCERPT_MAX = 600
# What is heard between looks waits in memory; a group louder than this keeps its latest.
HEARD_MAX = 2000
OPEN_URL = "https://im.qq.com/"
# Why the gateway turned the bot away, as the page's codes.
REFUSED = {"app_rejected": "qq_rejected", "bot_offline": "qq_offline", "bot_banned": "qq_banned"}
_MENTION = re.compile(r"<@!?([\w-]+)>")
_MEDIA = {"photo": "[图片]", "voice": "[语音]", "video": "[视频]", "file": "[文件]"}


def qr_image(content: str) -> str:
    """`content` as a QR code, a PNG data: URL."""
    import qrcode

    image = io.BytesIO()
    qrcode.make(content).save(image, format="PNG")
    return "data:image/png;base64," + base64.b64encode(image.getvalue()).decode()


class Reader(qq.QQ):
    """The gateway client of direct/qq.py, keeping what a source needs: who is
    mentioned, the sender's union id, the groups the bot joins and leaves."""

    def __init__(self, values: dict, *, client=None, connect=None, joined=None):
        super().__init__(values, client=client, connect=connect)
        self.bot_name = ""
        self.joined = joined

    async def _dispatch(self, name: str, data: dict, on_event, connected) -> None:
        if name == "READY":
            self.bot_name = str((data.get("user") or {}).get("username") or "")
        if name in ("GROUP_ADD_ROBOT", "GROUP_DEL_ROBOT") and data.get("group_openid"):
            self.joined(str(data["group_openid"]), name == "GROUP_ADD_ROBOT")
            return
        await super()._dispatch(name, data, on_event, connected)

    def event(self, name: str, data: dict):
        event, target = super().event(name, data)
        if event:
            author = data.get("author") or {}
            event["union"] = str(author.get("union_openid") or "")
            event["mentions"] = sorted({str(m[k]) for m in data.get("mentions") or [] if isinstance(m, dict)
                                        for k in ("member_openid", "union_openid", "user_openid", "id") if m.get(k)}
                                       | set(_MENTION.findall(event["text"])))
        return event, target


def words(event: dict, owner_ids: set[str]) -> str:
    """What one message says, on one line: its words with mentions shown, and what it carries."""
    text = _MENTION.sub(lambda m: "@我" if m.group(1) in owner_ids else "@", event["text"])
    parts = [text]
    for segment in event["segments"][1 if event["text"] else 0:]:
        if segment["type"] == "image":
            parts.append(_MEDIA["photo"])
        elif segment["type"] == "media":
            name = f" {segment['name']}" if segment.get("name") else ""
            parts.append(_MEDIA.get(segment.get("kind"), "[文件]") + name)
    return " ".join(" ".join(parts).split())[:LINE_MAX]


def stretches(current: dict | None, heard: list[dict], *, private: bool, owner_ids: set[str]):
    """The stretches `heard` (oldest first) adds to or begins, and the one still open after them.
    `current` is the stretch left open by the last look; it goes on when they follow it closely."""
    touched: list[dict] = []
    for event in heard:
        line = words(event, owner_ids)
        if not line:
            continue
        at = float(event["sent_at"])
        if current is None or at - current["end"] > GAP_S or at - current["start"] > SPAN_MAX_S:
            current = {"first": event["message_id"], "start": at, "end": at, "lines": [], "names": [],
                       "count": 0, "others": private, "mentioned": private}
        if not touched or touched[-1] is not current:
            touched.append(current)
        mine = event["sender_id"] in owner_ids or bool(event["union"] and event["union"] in owner_ids)
        stranger = "QQ 用户" if private else f"群友{event['sender_id'][-4:]}"
        who = "我" if mine else event["sender_name"] or stranger
        current["end"] = max(current["end"], at)
        current["count"] += 1
        if len(current["lines"]) < LINES_MAX:
            current["lines"].append(f"{who}: {line}")
        if who not in current["names"]:
            current["names"].append(who)
        if not mine:
            current["others"] = True
            if owner_ids & set(event["mentions"]):
                current["mentioned"] = True
    return touched, current


def group_name(gid: str) -> str:
    # QQ tells a bot no group's name, only an id of its own for it.
    return f"QQ 群 {gid[-6:].upper()}"


def to_item(stretch: dict, scene: str, ident: str, now: float) -> Item:
    start = datetime.fromtimestamp(stretch["start"], timezone.utc)
    where = group_name(ident) if scene == "group" else "QQ 私聊"
    first = stretch["first"]
    return Item(url=f"{OPEN_URL}#qq-{item_id(f'{scene}:{ident}:{first}')}", site=f"QQ · {where}"[:80],
                kind="post", title=(where if scene == "group" else "发给 QQ 机器人的消息")[:200],
                author=", ".join(stretch["names"][:3])[:120], description=" · ".join(stretch["lines"])[:EXCERPT_MAX],
                published=start.isoformat(),
                # Found when it was said, so the feed's freshness follows the talk; a clock ahead counts as now.
                seen_at=min(int(stretch["end"]), int(now)), fits=stretch["mentioned"], why="")


class QQBot(Connector):
    key = "qq"
    private = "message"
    name = ("QQ", "QQ")
    how = "qr"
    warn = None
    reads = (("Only the groups that added the bot and whose owner set it to receive all group messages, "
              "the @-mentions of it elsewhere, and what is sent to it privately, while personagent is running; "
              "until QQ certifies the bot it can join only groups you own."),
             ("只读拉了它、并且群主设置了获取群内全部消息的群，以及发给它的消息，且只在 personagent 开着时收得到；"
              "机器人通过认证之前，QQ 只允许它加入你担任群主的群。"))
    errors = ("qq_invalid", "qq_expired", "qq_failed", "qq_unreachable", "qq_rejected", "qq_offline", "qq_banned",
              "qq_refused")

    def __init__(self, workspace):
        super().__init__(workspace)
        self._bind: dict = {}
        self._heard: list[tuple[str, str, dict]] = []
        self._listening: asyncio.Task | None = None

    # -- where things are kept

    def load(self) -> dict:
        # Every field there, so `change` edits a whole state.
        return {"appid": "", "bot": "", "owner": "", "union": "", "members": {}, "groups": {}, "open": {},
                "last": 0, "error": "", **super().load()}

    state = load

    def client(self) -> httpx.AsyncClient:
        """Tests hand a stand-in transport in here."""
        return httpx.AsyncClient(timeout=TIMEOUT_S)

    # Tests put a stand-in gateway here: an async function from the URL to a socket.
    socket = None

    def connected(self) -> bool:
        return bool(self.env(ENV_SECRET) and self.state()["appid"])

    # -- the scan

    async def start(self, values: dict) -> dict:
        # The portal unseals the secret with this key; the module is checked before a bot is lost to it.
        import cryptography.hazmat.primitives.ciphers.aead  # noqa: F401

        key = base64.b64encode(os.urandom(32)).decode()
        try:
            async with self.client() as http:
                task = str((await qq._portal(http, "/lite/create_bind_task", {"key": key})).get("task_id") or "")
        except qq.BindFailed:
            raise AccountError("qq_failed") from None
        except (httpx.HTTPError, ValueError):
            raise AccountError("qq_unreachable") from None
        if not task:
            raise AccountError("qq_failed")
        now = time.monotonic()
        self._bind = {"key": key, "task": task, "until": now + qq.BIND_TTL_S, "next": now + qq.BIND_POLL_S}
        return {"qr": await asyncio.to_thread(qr_image, qq.BIND_PAGE.format(task=quote(task)))}

    async def poll(self) -> dict:
        bind, now = self._bind, time.monotonic()
        if not bind:
            return {"state": "done", "error": ""} if self.connected() else {"state": "expired", "error": "qq_expired"}
        if now > bind["until"]:
            self._bind = {}
            return {"state": "expired", "error": "qq_expired"}
        if now < bind["next"]:
            return {"state": "pending", "error": ""}
        bind["next"] = now + qq.BIND_POLL_S
        try:
            async with self.client() as http:
                result = await qq._portal(http, "/lite/poll_bind_result", {"task_id": bind["task"]})
        except qq.BindFailed:
            self._bind = {}
            return {"state": "failed", "error": "qq_failed"}
        except (httpx.HTTPError, ValueError):
            return {"state": "pending", "error": ""}   # one lost poll; the deadline still holds
        if result.get("status") == 3:
            self._bind = {}
            return {"state": "expired", "error": "qq_expired"}
        if result.get("status") != 2:
            return {"state": "pending", "error": ""}
        self._bind = {}
        appid, sealed = str(result.get("bot_appid") or ""), str(result.get("bot_encrypt_secret") or "")
        if not appid.strip("0") or not sealed:
            return {"state": "failed", "error": "qq_failed"}
        try:
            secret = qq._unseal(sealed, bind["key"])
        except qq.BindFailed:
            return {"state": "failed", "error": "qq_failed"}
        await self._keep(appid, secret, str(result.get("user_openid") or ""))
        return {"state": "done", "error": ""}

    async def _keep(self, appid: str, secret: str, owner: str) -> None:
        """Keep the bot QQ handed over, and start listening with it."""
        await self._stop()
        await asyncio.to_thread(self.keep_env, {ENV_APPID: appid, ENV_SECRET: secret})

        def put(state: dict) -> None:
            if state.get("appid") != appid:
                state.clear()       # another bot: what the last one heard does not carry over
            state.update(appid=appid, owner=owner or state.get("owner", ""), error="")

        await asyncio.to_thread(self.change, put)
        self._listen()

    # -- listening

    def _listen(self) -> None:
        """Have the gateway open, unless it is already."""
        if self._listening is None or self._listening.done():
            self._listening = asyncio.create_task(self._run())

    async def _run(self) -> None:
        reader = Reader({"appid": self.env(ENV_APPID), "secret": self.env(ENV_SECRET)}, client=self.client(),
                        connect=self.socket, joined=self._joined)

        def connected() -> None:
            self.change(lambda s: s.update(error="", bot=reader.bot_name or s.get("bot", "")))

        try:
            await reader.run(self._hear, connected)
        except Refused as refused:
            code = REFUSED.get(str(refused), "qq_refused")
            logger.info("qq: the gateway refused the bot (%s)", code)
            await asyncio.to_thread(self.change, lambda s: s.update(error=code))
        except ConnectionError:
            # QQ's token endpoint did not answer; the next look opens the gateway again.
            await asyncio.to_thread(self.change, lambda s: s.update(error="qq_unreachable"))
        finally:
            await reader.close()

    def _joined(self, gid: str, added: bool) -> None:
        def put(state: dict) -> None:
            if added:
                state["groups"].setdefault(gid, {"on": True})
            else:
                state["groups"].pop(gid, None)
                state["open"].pop(f"group:{gid}", None)

        self.change(put)

    async def _hear(self, event: dict, target: tuple[str, str]) -> None:
        scene, ident = target
        if scene == "group":
            groups = (await asyncio.to_thread(self.state))["groups"]
            if ident not in groups:
                # A group the bot was in before it was connected here: on, as the person put it there.
                await asyncio.to_thread(self._joined, ident, True)
            elif not groups[ident].get("on"):
                return
        self._heard.append((scene, ident, event))
        del self._heard[:-HEARD_MAX]

    async def _stop(self) -> None:
        if self._listening is not None:
            self._listening.cancel()
            await asyncio.gather(self._listening, return_exceptions=True)
            self._listening = None

    # -- looks

    async def look(self) -> int:
        """Turn what was heard since the last look into items; how many stretches were kept or grew."""
        if not self.connected():
            return 0
        self._listen()
        return await self._flush()

    async def _flush(self) -> int:
        heard, self._heard = self._heard, []
        if not heard:
            await asyncio.to_thread(self.change, lambda s: s.update(last=int(time.time())))
            return 0
        state, now = self.state(), time.time()
        appid = state["appid"]
        # The owner's private id comes with the scan (else: the first to write to the bot, as only
        # the owner can before QQ certifies it); their union id, from their first private message.
        owner = state["owner"] or next((e["sender_id"] for scene, _, e in heard if scene == "c2c"), "")
        union = state["union"] or next((e["union"] for scene, _, e in heard
                                        if scene == "c2c" and e["sender_id"] == owner and e["union"]), "")
        members = dict(state["members"])
        for scene, ident, event in heard:
            if scene == "group" and union and event["union"] == union:
                members[ident] = event["sender_id"]
        by_target: dict[tuple[str, str], list[dict]] = {}
        for scene, ident, event in heard:
            by_target.setdefault((scene, ident), []).append(event)
        items, still = [], {}
        for (scene, ident), events in by_target.items():
            events.sort(key=lambda e: e["sent_at"])
            owner_ids = {i for i in (owner, union, members.get(ident, "")) if i}
            touched, still[f"{scene}:{ident}"] = stretches(state["open"].get(f"{scene}:{ident}"), events,
                                                          private=scene == "c2c", owner_ids=owner_ids)
            items += [to_item(s, scene, ident, now) for s in touched if s["others"]]
        await asyncio.to_thread(self.keep_items, items)

        def record(s: dict) -> None:
            if s.get("appid") != appid:
                return          # forgotten or replaced while this look read
            s["open"].update(still)
            s.update(owner=owner, union=union, members=members, last=int(now))

        await asyncio.to_thread(self.change, record)
        logger.info("qq: a look kept %d stretches", len(items))
        return len(items)

    def view(self) -> dict:
        state = self.state()
        connected = bool(self.env(ENV_SECRET) and state["appid"])
        return {"connected": connected, "account": (state["bot"] or f"AppID {state['appid']}") if connected else "",
                "last": iso(state["last"]) if connected else "", "problem": state["error"] if connected else "",
                "ready": True,
                "choices": [{"id": gid, "name": group_name(gid), "on": g.get("on") is True}
                            for gid, g in state["groups"].items()] if connected else []}

    async def choose(self, on: list[str]) -> None:
        if not self.connected():
            raise AccountError("qq_invalid")
        chosen = set(on)

        def turn(state: dict) -> None:
            for gid, group in state["groups"].items():
                group["on"] = gid in chosen
                if gid not in chosen:
                    state["open"].pop(f"group:{gid}", None)

        await asyncio.to_thread(self.change, turn)
        self._heard = [h for h in self._heard if h[0] != "group" or h[1] in chosen]

    async def revoke(self) -> None:
        # What it already brought stays in the feed, like the mail's. The bot itself stays the person's, on QQ.
        self._bind, self._heard = {}, []
        await self._stop()
        await asyncio.to_thread(self.keep_env, {ENV_APPID: "", ENV_SECRET: ""})
        await asyncio.to_thread(self.forget)

    async def close(self) -> None:
        # The gateway closes first, then what it heard since the last look is kept.
        await self._stop()
        if self._heard and self.connected():
            await self._flush()
