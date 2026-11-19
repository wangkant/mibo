"""WeChat through Tencent's own ClawBot (the iLink bot API, see direct/weixin.py).

The person scans a QR code with WeChat and gets a ClawBot chat of their own.
It reads only that chat: what the person sends or forwards there. Nothing
else in their WeChat, no other chat and no group, is reachable this way. Each
thing forwarded is one library item the character keeps for the person.

The bot token is kept in the home's .env as WECHAT_READ_TOKEN; the bot, the
person's id there and where the reading stopped, in `<runtime>/accounts/wechat.json`.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import logging
import re
import time
from datetime import datetime, timezone
from urllib.parse import quote, urlsplit

import httpx
import qrcode

from ..direct import weixin as ilink
from ..library import Item
from .base import AccountError, Connector, iso

logger = logging.getLogger("agent.accounts.wechat")

ENV_KEY = "WECHAT_READ_TOKEN"
# A poll waits this long for the QR code's state; the page asks again after.
STATUS_WAIT_S = 10
TITLE_MAX = 80
TEXT_MAX = 2000
_LINK = re.compile(r"https?://[^\s<>\"'，。、）)】]+")


def qr_png(content: str) -> str:
    image = io.BytesIO()
    qrcode.make(content).save(image, format="PNG")
    return "data:image/png;base64," + base64.b64encode(image.getvalue()).decode()


def digest(token: str) -> str:
    """Which login the state belongs to, without the token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


def said(message: dict) -> str:
    """What one message holds as text: its words, a voice note's transcript, a file's name, what it quotes."""
    parts = []
    for part in message.get("item_list") or []:
        quoted = ((part.get("ref_msg") or {}).get("message_item") or {}).get("text_item") or {}
        if quoted.get("text"):
            parts.append(str(quoted["text"]))
        kind = part.get("type")
        if kind == 1:
            parts.append(str((part.get("text_item") or {}).get("text") or ""))
        elif kind == 3:
            parts.append(str((part.get("voice_item") or {}).get("text") or ""))
        elif kind == 4:
            parts.append(str((part.get("file_item") or {}).get("file_name") or ""))
    return "\n".join(p.strip() for p in parts if p.strip())[:TEXT_MAX]


def to_items(message: dict, now: float) -> list[Item]:
    """One item per link the message carries, or one for the message itself."""
    text = said(message)
    if not text:
        return []
    sent = int(message.get("create_time_ms") or 0) // 1000
    seen = min(sent or int(now), int(now))
    published = datetime.fromtimestamp(seen, timezone.utc).isoformat()
    rest = " ".join(_LINK.sub(" ", text).split())
    links = list(dict.fromkeys(_LINK.findall(text)))
    if links:
        return [Item(url=link, site=urlsplit(link).hostname or "WeChat",
                     kind="article" if (urlsplit(link).hostname or "").endswith("mp.weixin.qq.com") else "page",
                     title=(rest or link)[:TITLE_MAX], description=rest, published=published,
                     seen_at=seen, fits=True, why="") for link in links]
    # Words with no address of their own: an address unique to the message, on WeChat's site.
    url = "https://weixin.qq.com/#" + quote(ilink.message_id(message), safe="")
    return [Item(url=url, site="微信 WeChat", kind="post", title=" ".join(text.split())[:TITLE_MAX],
                 description=text, text=text, published=published, seen_at=seen, fits=True, why="")]


class WeChat(Connector):
    key = "wechat"
    name = ("WeChat", "微信")
    how = "qr"
    warn = ("This connects WeChat's own ClawBot, a chat Tencent gives you inside WeChat. personagent reads only "
            "what you send or forward to that chat, never your other chats, groups or contacts. "
            "WeChat may pause the ClawBot for an hour at a time.",
            "这会接入微信官方的 ClawBot：腾讯在你的微信里给你的一个对话。personagent 只读你发给或转发到这个对话的内容，"
            "读不到你的其他聊天、群和联系人。微信有时会把 ClawBot 暂停一小时。")
    reads = ("Only what you send or forward to its ClawBot chat: words, links, voice transcripts and file "
             "names; not pictures or videos, and nothing else in your WeChat.",
             "只读你发给或转发到它的 ClawBot 对话的内容：文字、链接、语音转写和文件名；"
             "读不到图片和视频，也读不到微信里的其他东西。")
    errors = frozenset({"wechat_expired", "wechat_no_qr", "wechat_verify_needed", "wechat_blocked",
                        "wechat_unreachable", "wechat_session_expired", "wechat_paused", "wechat_failed"})

    def __init__(self, workspace):
        super().__init__(workspace)
        # The QR code being shown: its ticket, where its state is asked, when it runs out.
        self._qr = ""
        self._base = ilink.API
        self._deadline = 0.0

    def http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=ilink.CALL_TIMEOUT_S)

    # -- connecting

    async def start(self, values: dict) -> dict:
        try:
            async with self.http() as http:
                response = await http.post(f"{ilink.API}/ilink/bot/get_bot_qrcode?bot_type=3",
                                           headers=ilink.post_headers(), json={"local_token_list": []})
                response.raise_for_status()
                issued = response.json()
        except (httpx.HTTPError, ValueError):
            raise AccountError("wechat_unreachable") from None
        ticket, content = str(issued.get("qrcode") or ""), str(issued.get("qrcode_img_content") or "")
        if not ticket or not content:
            raise AccountError("wechat_no_qr")
        self._qr, self._base = ticket, ilink.API
        self._deadline = time.monotonic() + ilink.QR_TTL_S
        return {"qr": qr_png(content)}

    async def poll(self) -> dict:
        if not self._qr or time.monotonic() > self._deadline:
            self._qr = ""
            return {"state": "expired", "error": "wechat_expired"}
        try:
            async with self.http() as http:
                answer = (await http.get(f"{self._base}/ilink/bot/get_qrcode_status?qrcode={quote(self._qr)}",
                                         headers=ilink.app_headers(), timeout=STATUS_WAIT_S)).json()
        except (httpx.HTTPError, ValueError):
            answer = {"status": "wait"}     # a long poll that ran out: nothing yet
        status = str(answer.get("status") or "wait")
        if status == "confirmed":
            if not answer.get("bot_token"):
                return {"state": "failed", "error": "wechat_failed"}
            await self._keep(answer)
            return {"state": "done", "error": ""}
        if status == "expired":
            self._qr = ""
            return {"state": "expired", "error": "wechat_expired"}
        if "need_verifycode" in status:
            return {"state": "failed", "error": "wechat_verify_needed"}
        if status in ("verify_code_blocked", "binded_redirect"):
            return {"state": "failed", "error": "wechat_blocked"}
        if status == "scaned_but_redirect" and answer.get("redirect_host"):
            self._base = "https://" + str(answer["redirect_host"]).strip("/")
        return {"state": "scanned" if status.startswith("scaned") else "pending", "error": ""}

    async def _keep(self, answer: dict) -> None:
        token = str(answer["bot_token"])
        base = str(answer.get("baseurl") or ilink.API).rstrip("/")
        self._qr = ""
        await asyncio.to_thread(self.keep_env, {ENV_KEY: token})

        def put(state: dict) -> None:
            state.clear()
            state.update(owner=digest(token), bot=str(answer.get("ilink_bot_id") or ""),
                         user=str(answer.get("ilink_user_id") or ""), base=base, cursor="", last=0, error="")

        await asyncio.to_thread(self.change, put)
        try:
            await self._call(token, base, "msg/notifystart", {})
        except AccountError as error:
            logger.info("wechat: notifystart failed (%s)", error)

    # -- reading

    async def _call(self, token: str, base: str, path: str, body: dict, timeout: float = ilink.CALL_TIMEOUT_S,
                    long_poll: bool = False) -> dict:
        try:
            async with self.http() as http:
                response = await http.post(f"{base}/ilink/bot/{path}", headers=ilink.post_headers(token),
                                           json={**body, "base_info": ilink.base_info()}, timeout=timeout)
        except httpx.ReadTimeout:
            if long_poll:
                return {"ret": 0}       # a long poll that ran out is an empty answer
            raise AccountError("wechat_unreachable") from None
        except httpx.HTTPError:
            raise AccountError("wechat_unreachable") from None
        if response.status_code in (401, 403):
            raise AccountError("wechat_session_expired")
        if response.status_code >= 400:
            raise AccountError("wechat_failed")
        try:
            answer = response.json()
        except ValueError:
            raise AccountError("wechat_failed") from None
        if ilink.STALE_SESSION in (answer.get("ret"), answer.get("errcode")):
            raise AccountError("wechat_paused")
        if answer.get("ret") not in (0, None) or answer.get("errcode") not in (0, None):
            raise AccountError("wechat_failed")
        return answer

    def _state(self) -> dict:
        """The saved state when it belongs to the token in .env, else {}."""
        token = self.env(ENV_KEY)
        state = self.load()
        return state if token and state.get("owner") == digest(token) else {}

    async def look(self) -> int:
        token = self.env(ENV_KEY)
        state = await asyncio.to_thread(self._state)
        if not state:
            return 0
        owner = state["owner"]
        try:
            answer = await self._call(token, state["base"], "getupdates", {"get_updates_buf": state["cursor"]},
                                      ilink.POLL_TIMEOUT_S + 10, long_poll=True)
        except AccountError as error:
            code = str(error)
            logger.info("wechat: a look failed (%s)", code)
            await asyncio.to_thread(self.change, lambda s: s.update(error=code) if s.get("owner") == owner else None)
            return 0
        now = time.time()
        items = [item for message in answer.get("msgs") or []
                 # The person's own messages to the ClawBot, outside any group.
                 if isinstance(message, dict) and message.get("message_type") == 1 and not message.get("group_id")
                 and (not state["user"] or str(message.get("from_user_id") or "") == state["user"])
                 for item in to_items(message, now)]
        kept = await asyncio.to_thread(self.keep_items, items)

        def record(saved: dict) -> None:
            if saved.get("owner") != owner:
                return          # revoked or replaced while this look read
            saved.update(cursor=str(answer.get("get_updates_buf") or saved["cursor"]), last=int(now), error="")

        await asyncio.to_thread(self.change, record)
        logger.info("wechat: a look kept %d forwarded things", kept)
        return kept

    def view(self) -> dict:
        state = self._state()
        return {"connected": bool(state), "account": state.get("user", ""), "last": iso(state.get("last")),
                "problem": state.get("error", ""), "ready": True, "choices": []}

    async def revoke(self) -> None:
        token = self.env(ENV_KEY)
        state = await asyncio.to_thread(self._state)
        if state:
            try:
                await self._call(token, state["base"], "msg/notifystop", {})
            except AccountError:
                pass            # the token is forgotten here either way
        await asyncio.to_thread(self.keep_env, {ENV_KEY: ""})
        await asyncio.to_thread(self.forget)
        self._qr = ""
