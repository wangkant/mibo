"""The person's Slack as a source, signed in through the system browser.

OAuth v2 with PKCE and no client secret: the browser comes back to a listener
on this computer and the app gets a user token with read scopes only. The token
(and its refresh token, when Slack rotates them) is kept in the home's .env;
the workspace, the conversations and where each was last read in
`<runtime>/accounts/slack.json`.

Apps outside the Slack Marketplace may call conversations.history once a
minute, 15 messages at a time. So the loop looks every minute, and each look
reads the one conversation that is on and was read longest ago. A stretch of
messages less than an hour apart becomes one library item, as Discord's do;
one that mentions the person, or a direct message, fits them.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import html
import logging
import re
import secrets
import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlencode

import httpx

from ..library import Item
from .base import AccountError, Connector, Loopback, iso

logger = logging.getLogger("agent.accounts.slack")

# Registered by the app's author, with http://localhost:SLACK_PORT/slack as its redirect URL and PKCE on.
SLACK_CLIENT_ID = ""
ENV_ID = "PERSONAGENT_SLACK_CLIENT_ID"
ENV_KEY = "SLACK_READ_TOKEN"
ENV_REFRESH = "SLACK_READ_REFRESH"
SLACK_PORT = 53134
AUTHORIZE = "https://slack.com/oauth/v2/authorize"
API = "https://slack.com/api/"
SCOPES = ("channels:history", "groups:history", "im:history", "mpim:history",
          "channels:read", "groups:read", "im:read", "mpim:read", "users:read")
TIMEOUT_S = 20
SIGN_IN_S = 10 * 60
# The limit Slack sets on conversations.history for apps outside its Marketplace.
HISTORY_EVERY_S = 60
HISTORY_LIMIT = 15
# A gap is paged back at most this many calls; past that its oldest messages are left.
GAP_PAGES = 8
CHANNELS_EVERY_S = 30 * 60
CHANNEL_PAGES = 5
FIRST_DAYS = 2
NAMES_MAX = 500
WAIT_MAX_S = 60
# Messages further apart than this start a new stretch; a stretch is never longer than SPAN_MAX_S.
GAP_S = 60 * 60
SPAN_MAX_S = 6 * 60 * 60
LINES_MAX = 8
LINE_MAX = 200
EXCERPT_MAX = 600
SPOKEN = (None, "thread_broadcast", "file_share", "bot_message", "me_message")
SIGNED_OUT = {"invalid_auth", "not_authed", "token_revoked", "token_expired", "account_inactive"}
_TAG = re.compile(r"<([@#!])([^>|]+)(?:\|([^>]*))?>|<([^>|]+)\|([^>]*)>|<([^>]+)>")

# When conversations.history was last called, for every look in this process.
_history_at = 0.0


def grow(current: Optional[dict], messages: list[dict]) -> tuple[list[dict], Optional[dict]]:
    """The stretches `messages` add to or begin, and the one still open after them, as Discord's.
    Each message is {"id", "at", "who", "line", "mine", "mentions"}, oldest first; matrix.py uses this too."""
    touched: list[dict] = []
    for m in messages:
        if current is None or m["at"] - current["end"] > GAP_S or m["at"] - current["start"] > SPAN_MAX_S:
            current = {"first": m["id"], "start": m["at"], "end": m["at"], "lines": [], "names": [],
                       "count": 0, "others": False, "mentioned": False}
        if not touched or touched[-1] is not current:
            touched.append(current)
        current["end"] = m["at"]
        current["count"] += 1
        if len(current["lines"]) < LINES_MAX:
            current["lines"].append(f"{m['who']}: {m['line'][:LINE_MAX]}")
        if m["who"] not in current["names"]:
            current["names"].append(m["who"])
        if not m["mine"]:
            current["others"] = True
            current["mentioned"] = current["mentioned"] or m["mentions"]
    return touched, current


def stretch_item(stretch: dict, url: str, site: str, title: str, now: float) -> Item:
    start = datetime.fromtimestamp(stretch["start"], timezone.utc)
    return Item(url=url, site=site[:80], kind="post", title=title[:200], author=", ".join(stretch["names"][:3])[:120],
                description=" · ".join(stretch["lines"])[:EXCERPT_MAX], published=start.isoformat(),
                # Found when it was said, so the feed's freshness follows the talk; a clock ahead counts as now.
                seen_at=min(int(stretch["end"]), int(now)), fits=stretch["mentioned"], why="")


def challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def plain(text: str, names: dict[str, str]) -> str:
    """Slack's markup as one line: <@U1> as @name, <#C1|general> as #general, <url|label> as label."""
    def name(match: re.Match) -> str:
        sign, ident, label, url, url_label, bare = match.groups()
        if sign == "@":
            return "@" + (label or names.get(ident, ident))
        if sign == "#":
            return "#" + (label or ident)
        if sign == "!":
            return "@" + (label or ident.split("^")[0])
        return url_label or url or bare
    return " ".join(html.unescape(_TAG.sub(name, text or "")).split())


class _Port(Loopback):
    """The loopback on the one port registered with Slack."""

    async def open(self) -> "Loopback":
        try:
            self._servers.append(await asyncio.start_server(self._answer, "127.0.0.1", SLACK_PORT))
        except OSError:
            raise AccountError("slack_port_busy") from None
        self.port = SLACK_PORT
        with contextlib.suppress(OSError):
            self._servers.append(await asyncio.start_server(self._answer, "::1", SLACK_PORT))
        return self


class Slack(Connector):
    key = "slack"
    private = "message"
    name = ("Slack", "Slack")
    how = "browser"
    warn = None
    reads = ("The channels and direct messages you switch on, in the workspace you sign in to; "
             "nothing is read until you switch a conversation on, and it never posts.",
             "你登录的工作区里你打开的频道和私信；不打开就什么都不读，也从不发言。")
    every = HISTORY_EVERY_S

    def __init__(self, workspace):
        super().__init__(workspace)
        self._signing: Optional[asyncio.Task] = None
        self._loop: Optional[Loopback] = None

    def state(self) -> dict:
        return {"user": "", "user_id": "", "team": "", "url": "", "expires": 0, "channels": {}, "names": {},
                "synced": 0, "last": 0, "error": "", **self.load()}

    def app(self) -> str:
        return self.client_id(SLACK_CLIENT_ID, ENV_ID)

    # -- signing in

    async def start(self, values: dict) -> dict:
        if not self.app():
            raise AccountError("slack_not_ready")
        await self.close()
        self._loop = await _Port("/slack").open()
        verifier, nonce = secrets.token_urlsafe(48), secrets.token_urlsafe(16)
        url = AUTHORIZE + "?" + urlencode({"client_id": self.app(), "scope": "", "user_scope": ",".join(SCOPES),
                                           "redirect_uri": self._loop.redirect, "state": nonce,
                                           "code_challenge": challenge(verifier), "code_challenge_method": "S256"})
        self._signing = asyncio.create_task(self._sign_in(self._loop, verifier, nonce))
        return {"browser": url}

    async def _sign_in(self, loop: Loopback, verifier: str, nonce: str) -> None:
        query = await loop.wait(SIGN_IN_S)
        if query.get("state") != nonce:
            raise AccountError("slack_failed")
        if query.get("error") or not query.get("code"):
            raise AccountError("slack_denied")
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as http:
            answer = await self._oauth(http, {"client_id": self.app(), "code": query["code"],
                                              "code_verifier": verifier, "redirect_uri": loop.redirect})
            user = answer.get("authed_user") or {}
            token = str(user.get("access_token") or "")
            if not token:
                raise AccountError("slack_failed")
            me = await self._call(http, token, "auth.test")
        await asyncio.to_thread(self.keep_env, {ENV_KEY: token, ENV_REFRESH: str(user.get("refresh_token") or "")})
        expires = int(time.time()) + int(user["expires_in"]) if user.get("expires_in") else 0

        def put(state: dict) -> None:
            if state.get("user_id") != me.get("user_id") or state.get("url") != me.get("url"):
                state.clear()       # another account: what the last one read does not carry over
            state.update(user=str(me.get("user") or ""), user_id=str(me.get("user_id") or ""),
                         team=str(me.get("team") or "Slack"), url=str(me.get("url") or ""), expires=expires, error="")

        self.change(put)
        with contextlib.suppress(AccountError):
            await self._sync()

    async def poll(self) -> dict:
        task = self._signing
        if task is None:
            connected = self.view()["connected"]
            return {"state": "done" if connected else "expired", "error": "" if connected else "slack_expired"}
        if not task.done():
            return {"state": "pending", "error": ""}
        self._signing = None
        if task.cancelled() or isinstance(task.exception(), asyncio.TimeoutError):
            return {"state": "expired", "error": "slack_expired"}
        if task.exception() is not None:
            error = task.exception()
            return {"state": "failed", "error": str(error) if isinstance(error, AccountError) else "slack_failed"}
        return {"state": "done", "error": ""}

    async def close(self) -> None:
        if self._signing is not None:
            self._signing.cancel()
            self._signing = None
        if self._loop is not None:
            self._loop.close()
            self._loop = None

    # -- the Web API

    async def _oauth(self, http: httpx.AsyncClient, data: dict) -> dict:
        try:
            answer = (await http.post(API + "oauth.v2.access", data=data)).json()
        except (httpx.HTTPError, ValueError):
            raise AccountError("slack_unreachable") from None
        if not answer.get("ok"):
            raise AccountError("slack_signed_out" if answer.get("error") in ("invalid_refresh_token", "invalid_grant")
                               else "slack_failed")
        return answer

    async def _call(self, http: httpx.AsyncClient, token: str, method: str, **params) -> dict:
        """One Web API call, waiting out a 429; the token rides in a header, never in a log."""
        for _ in range(3):
            try:
                response = await http.post(API + method, data=params, headers={"Authorization": f"Bearer {token}"})
            except httpx.HTTPError:
                raise AccountError("slack_unreachable") from None
            if response.status_code == 429:
                await asyncio.sleep(min(float(response.headers.get("retry-after") or 5), WAIT_MAX_S))
                continue
            try:
                answer = response.json()
            except ValueError:
                raise AccountError("slack_failed") from None
            if answer.get("ok"):
                return answer
            error = str(answer.get("error") or "")
            if error in SIGNED_OUT:
                raise AccountError("slack_signed_out")
            raise AccountError(f"slack_api_{error}" if error in ("channel_not_found", "not_in_channel")
                               else "slack_failed")
        raise AccountError("slack_unreachable")

    async def _token(self, http: httpx.AsyncClient) -> str:
        """The token, renewed first when Slack rotates it and it ends within ten minutes."""
        state = self.state()
        refresh = self.env(ENV_REFRESH)
        if not refresh or not state["expires"] or time.time() < state["expires"] - 600:
            return self.env(ENV_KEY)
        answer = await self._oauth(http, {"client_id": self.app(), "grant_type": "refresh_token",
                                          "refresh_token": refresh})
        got = answer.get("authed_user") if not answer.get("access_token") else answer
        token = str(got["access_token"])
        # Each refresh token is good once: the new one replaces it.
        await asyncio.to_thread(self.keep_env, {ENV_KEY: token, ENV_REFRESH: str(got.get("refresh_token") or refresh)})
        self.change(lambda s: s.update(expires=int(time.time()) + int(got.get("expires_in") or 43200)))
        return token

    async def _names(self, http: httpx.AsyncClient, token: str, ids: set[str]) -> dict[str, str]:
        """Display names for these user ids, asked of Slack only once each."""
        names = dict(self.state()["names"])
        for uid in sorted(i for i in ids if i and i not in names):
            try:
                user = (await self._call(http, token, "users.info", user=uid)).get("user") or {}
            except AccountError as error:
                if str(error) != "slack_failed":
                    raise
                user = {}
            profile = user.get("profile") or {}
            names[uid] = str(profile.get("display_name") or profile.get("real_name") or user.get("name") or uid)[:80]
        kept = dict(list(names.items())[-NAMES_MAX:])
        self.change(lambda s: s.update(names=kept))
        return kept

    async def _sync(self, http: Optional[httpx.AsyncClient] = None) -> None:
        """The conversations the person is in; one seen for the first time is off until they turn it on."""
        async with contextlib.AsyncExitStack() as stack:
            if http is None:
                http = await stack.enter_async_context(httpx.AsyncClient(timeout=TIMEOUT_S))
            token = await self._token(http)
            found, cursor = [], ""
            for _ in range(CHANNEL_PAGES):
                answer = await self._call(http, token, "users.conversations", limit=200, exclude_archived="true",
                                          types="public_channel,private_channel,mpim,im", cursor=cursor)
                found += answer.get("channels") or []
                cursor = (answer.get("response_metadata") or {}).get("next_cursor") or ""
                if not cursor:
                    break
            names = await self._names(http, token, {str(c.get("user") or "") for c in found if c.get("is_im")})

        def label(c: dict) -> str:
            if c.get("is_im"):
                return "@" + names.get(str(c.get("user")), str(c.get("user")))
            if c.get("is_mpim"):
                return ", ".join(str(c.get("name") or "").removeprefix("mpdm-").rsplit("-", 1)[0].split("--"))
            return "#" + str(c.get("name") or c["id"])

        def put(state: dict) -> None:
            known = state.get("channels") or {}
            state["channels"] = {c["id"]: {**(known.get(c["id"]) or {"on": False}), "name": label(c)[:100],
                                           "im": bool(c.get("is_im"))} for c in found}
            state["synced"] = int(time.time())

        self.change(put)

    # -- looks

    async def look(self) -> int:
        global _history_at
        state = self.state()
        if not self.view()["connected"]:
            return 0
        now = time.time()
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_S) as http:
                if now - state["synced"] > CHANNELS_EVERY_S:
                    await self._sync(http)
                    state = self.state()
                on = [cid for cid, record in state["channels"].items() if record.get("on")]
                if not on or now - _history_at < HISTORY_EVERY_S:
                    self.change(lambda s: s.update(last=int(now), error=""))
                    return 0
                # One still paging back through a gap goes first, then the one read longest ago.
                cid = min(on, key=lambda c: (not state["channels"][c].get("back"), state["channels"][c].get("read", 0)))
                record = state["channels"][cid]
                after = str(record.get("after") or f"{now - FIRST_DAYS * 86400:.6f}")
                token = await self._token(http)
                _history_at = time.time()
                bounds = {"latest": record["back"]} if record.get("back") else {}
                try:
                    answer = await self._call(http, token, "conversations.history", channel=cid, oldest=after,
                                              limit=HISTORY_LIMIT, **bounds)
                except AccountError as error:
                    if not str(error).startswith("slack_api_"):
                        raise
                    # Left or removed since: the next look reads another one first, and a gap it paged is dropped.
                    def left(s: dict) -> None:
                        if cid in s["channels"]:
                            for done in ("back", "held", "top", "pages"):
                                s["channels"][cid].pop(done, None)
                            s["channels"][cid].update(read=int(now))

                    self.change(left)
                    return 0
                messages = sorted(answer.get("messages") or [], key=lambda m: float(m["ts"]))
                spoken = [m for m in messages if m.get("subtype") in SPOKEN]
                mentioned = {u for m in spoken for u in re.findall(r"<@([UW][A-Z0-9]+)", m.get("text") or "")}
                names = await self._names(http, token, {str(m.get("user") or "") for m in spoken} | mentioned)
        except AccountError as error:
            logger.info("slack: a look failed (%s)", error)
            self.change(lambda s, code=str(error): s.update(error=code))
            return 0
        me = state["user_id"]
        said = []
        for m in spoken:
            # A file is named as one, never by its name.
            line = plain(m.get("text") or "", names) or " ".join("[file]" for _ in m.get("files") or [])
            if not line.strip():
                continue
            uid = str(m.get("user") or "")
            who = names.get(uid) or str(m.get("username") or (m.get("bot_profile") or {}).get("name") or uid)
            said.append({"id": m["ts"], "at": float(m["ts"]), "who": who, "line": line, "mine": uid == me,
                         "mentions": record.get("im", False) or f"<@{me}>" in (m.get("text") or "")})
        # Slack answers the newest HISTORY_LIMIT after `after`. When more wait below them, the next
        # looks of this channel page back to `after` first, holding what they read, so none is skipped.
        # The first read of a channel keeps only the newest.
        held = said + record.get("held", [])
        top = record.get("top") or (messages[-1]["ts"] if messages else after)
        pages = record.get("pages", 0) + 1
        if answer.get("has_more") and messages and record.get("after") and pages < GAP_PAGES:
            back = messages[0]["ts"]

            def hold(s: dict) -> None:
                if cid in s.get("channels", {}):
                    s["channels"][cid].update(back=back, held=held, top=top, pages=pages, read=int(now))
                s.update(last=int(now), error="")

            self.change(hold)
            return 0
        if answer.get("has_more") and record.get("after"):
            logger.info("slack: %s had more than %d new messages; the older ones were left", record["name"],
                        len(held))
        touched, still = grow(record.get("open"), held)
        items = [stretch_item(s, f"{state['url']}archives/{cid}/p{s['first'].replace('.', '')}",
                              f"Slack · {state['team']}", f"{record['name']} · {state['team']}", now)
                 for s in touched if s["others"]]
        await asyncio.to_thread(self.keep_items, items)

        def put(s: dict) -> None:
            if cid in s.get("channels", {}):
                channel = s["channels"][cid]
                for done in ("back", "held", "top", "pages"):
                    channel.pop(done, None)
                channel.update(after=top, open=still, read=int(now))
            s.update(last=int(now), error="")

        self.change(put)
        logger.info("slack: a look kept %d stretches", len(items))
        return len(items)

    def view(self) -> dict:
        state = self.state()
        connected = bool(self.env(ENV_KEY) and state["user_id"])
        return {"connected": connected, "account": f"{state['user']} · {state['team']}" if connected else "",
                "last": iso(state["last"]) if connected else "", "problem": state["error"] if connected else "",
                "ready": bool(self.app()),
                "choices": [{"id": cid, "name": r.get("name", cid), "on": r.get("on") is True}
                            for cid, r in state["channels"].items()] if connected else []}

    async def choose(self, on: list[str]) -> None:
        chosen = set(on)

        def turn(state: dict) -> None:
            for cid, record in (state.get("channels") or {}).items():
                record["on"] = cid in chosen

        self.change(turn)

    async def revoke(self) -> None:
        await self.close()
        token = self.env(ENV_KEY)
        if token:
            with contextlib.suppress(AccountError):
                async with httpx.AsyncClient(timeout=TIMEOUT_S) as http:
                    await self._call(http, token, "auth.revoke")
        # What it already brought stays in the feed, like the mail's.
        await asyncio.to_thread(self.keep_env, {ENV_KEY: "", ENV_REFRESH: ""})
        self.forget()
