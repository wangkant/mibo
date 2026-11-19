"""The person's own Matrix account as a source, read over the Client-Server API.

The person gives their homeserver, their user and their password, used once to
sign in and never kept; a server that signs in only through a web page (SSO) is
signed in to in the system browser, which comes back to a listener on this
computer. The access token is kept in the home's .env as MATRIX_READ_TOKEN; the
server, the joined rooms and where /sync stopped, in
`<runtime>/accounts/matrix.json`.

There is no crypto library here, so only rooms without end-to-end encryption
can be read; encrypted ones are not offered. A look runs one /sync from where
the last stopped and keeps each stretch of messages less than an hour apart in
a room that is on as one library item, as Discord's are. A stretch that
mentions the person, or one in a direct chat, fits them.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import secrets
import time
from typing import Optional
from urllib.parse import quote

import httpx

from ..direct.matrix import FIRST_FILTER, SYNC_FILTER, _retry_after, localpart, plain_text, secure_base
from .base import AccountError, Connector, Loopback, iso
from .slack import grow, stretch_item

logger = logging.getLogger("agent.accounts.matrix")

ENV_KEY = "MATRIX_READ_TOKEN"
CLIENT = "/_matrix/client/v3"
DEFAULT_SERVER = "matrix.org"
TIMEOUT_S = 30
SIGN_IN_S = 10 * 60
NAMES_MAX = 1000
SPOKEN = ("m.room.message", "m.sticker")
SIGNED_OUT = ("M_UNKNOWN_TOKEN", "M_MISSING_TOKEN", "M_USER_DEACTIVATED")

FIELDS = [{"key": "homeserver", "label": ("Homeserver", "服务器"), "secret": False,
           "help": ("Where your account lives; matrix.org if you are not sure.",
                    "你的账号所在的服务器；不确定就填 matrix.org。")},
          {"key": "user", "label": ("User name", "用户名"), "secret": False,
           "help": ("Your Matrix ID, for example @you:matrix.org, or just the name before the colon.",
                    "你的 Matrix ID，例如 @you:matrix.org，也可以只填冒号前的名字。")},
          {"key": "password", "label": ("Password", "密码"), "secret": True,
           "help": ("Used once to sign in and never kept. Leave it empty if your server signs in through a web page.",
                    "只用来登录一次，不会保存。如果你的服务器在网页上登录，就留空。")}]


def server_of(user: str) -> str:
    return user.split(":", 1)[1] if user.startswith("@") and ":" in user else ""


def address(text: str) -> str:
    text = text.strip().rstrip("/")
    return text if "://" in text else f"https://{text}"


class Matrix(Connector):
    key = "matrix"
    private = "message"
    name = ("Matrix", "Matrix")
    how = "fields"
    warn = None
    reads = ("The rooms you switch on, if they are not end-to-end encrypted; encrypted rooms cannot be read "
             "and are not offered. It never posts.",
             "你打开的、未开启端到端加密的房间；加密的房间读不了，也不会列出。它从不发言。")

    def __init__(self, workspace):
        super().__init__(workspace)
        self._signing: Optional[asyncio.Task] = None
        self._loop: Optional[Loopback] = None

    def state(self) -> dict:
        return {"base": "", "user_id": "", "display": "", "since": "", "rooms": {}, "direct": [], "names": {},
                "last": 0, "error": "", **self.load()}

    # -- signing in

    async def start(self, values: dict) -> dict:
        user = str(values.get("user") or "").strip()
        if not user:
            return {"fields": FIELDS, "link": ""}
        base = address(str(values.get("homeserver") or "") or server_of(user) or DEFAULT_SERVER)
        if not secure_base(base) or len(base) > 300:
            raise AccountError("matrix_homeserver_invalid")
        await self.close()
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as http:
            base = await self._discover(http, base)
            try:
                flows = (await http.get(base + CLIENT + "/login")).json()
            except httpx.HTTPError:
                raise AccountError("matrix_unreachable") from None
            except ValueError:
                raise AccountError("matrix_homeserver_invalid") from None
            if not isinstance(flows, dict):
                raise AccountError("matrix_homeserver_invalid")
            kinds = {str(f.get("type")) for f in flows.get("flows") or [] if isinstance(f, dict)}
            password = str(values.get("password") or "")
            if password and "m.login.password" in kinds:
                await self._login(http, base, {"type": "m.login.password", "password": password,
                                               "identifier": {"type": "m.id.user", "user": user}})
                return {"done": True}
        if "m.login.sso" not in kinds:
            raise AccountError("matrix_password_missing" if "m.login.password" in kinds else "matrix_login_unsupported")
        # A path no other program on this computer can guess, so only this sign-in comes back to it.
        self._loop = await Loopback(f"/matrix/{secrets.token_urlsafe(16)}").open()
        # The server adds loginToken to this address; "code" makes the listener's page say it worked.
        back = self._loop.redirect + "?code=sso"
        self._signing = asyncio.create_task(self._sso(self._loop, base))
        return {"browser": f"{base}{CLIENT}/login/sso/redirect?redirectUrl={quote(back, safe='')}"}

    async def _discover(self, http: httpx.AsyncClient, base: str) -> str:
        """A server name like https://matrix.org may serve its API elsewhere."""
        with contextlib.suppress(httpx.HTTPError, ValueError, AttributeError):
            found = (await http.get(base + "/.well-known/matrix/client", follow_redirects=True)).json()
            found = str((found.get("m.homeserver") or {}).get("base_url") or "").strip().rstrip("/")
            if found and secure_base(found):
                return found
        return base

    async def _sso(self, loop: Loopback, base: str) -> None:
        query = await loop.wait(SIGN_IN_S)
        if not query.get("loginToken"):
            raise AccountError("matrix_denied")
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as http:
            await self._login(http, base, {"type": "m.login.token", "token": query["loginToken"]})

    async def _login(self, http: httpx.AsyncClient, base: str, body: dict) -> None:
        """POST /login once; the token is kept, the password never is."""
        try:
            response = await http.post(base + CLIENT + "/login",
                                       json={**body, "initial_device_display_name": "personagent (read only)"})
            answer = response.json()
        except httpx.HTTPError:
            raise AccountError("matrix_unreachable") from None
        except ValueError:
            raise AccountError("matrix_homeserver_invalid") from None
        if response.status_code in (400, 401, 403):
            raise AccountError("matrix_login_rejected")
        if response.status_code >= 400 or not answer.get("access_token"):
            raise AccountError("matrix_failed")
        token, user_id = str(answer["access_token"]), str(answer.get("user_id") or "")
        await asyncio.to_thread(self.keep_env, {ENV_KEY: token})

        def put(state: dict) -> None:
            if state.get("user_id") != user_id:
                state.clear()       # another account: what the last one read does not carry over
            state.update(base=base, user_id=user_id, error="")

        self.change(put)

    async def poll(self) -> dict:
        task = self._signing
        if task is None:
            connected = self.view()["connected"]
            return {"state": "done" if connected else "expired", "error": "" if connected else "matrix_expired"}
        if not task.done():
            return {"state": "pending", "error": ""}
        self._signing = None
        if task.cancelled() or isinstance(task.exception(), asyncio.TimeoutError):
            return {"state": "expired", "error": "matrix_expired"}
        if task.exception() is not None:
            error = task.exception()
            return {"state": "failed", "error": str(error) if isinstance(error, AccountError) else "matrix_failed"}
        return {"state": "done", "error": ""}

    async def close(self) -> None:
        if self._signing is not None:
            self._signing.cancel()
            self._signing = None
        if self._loop is not None:
            self._loop.close()
            self._loop = None

    # -- the Client-Server API

    async def _call(self, http: httpx.AsyncClient, method: str, path: str, **kwargs) -> dict:
        """One call, waiting out M_LIMIT_EXCEEDED; the token rides in a header, never in a log."""
        state = self.state()
        for _ in range(3):
            try:
                response = await http.request(method, state["base"] + CLIENT + path,
                                              headers={"Authorization": f"Bearer {self.env(ENV_KEY)}"}, **kwargs)
                answer = response.json() if response.content else {}
            except httpx.HTTPError:
                raise AccountError("matrix_unreachable") from None
            except ValueError:
                raise AccountError("matrix_failed") from None
            code = str(answer.get("errcode") or "")
            if response.status_code == 429 or code == "M_LIMIT_EXCEEDED":
                await asyncio.sleep(_retry_after(response, answer))
                continue
            if response.status_code == 401 or code in SIGNED_OUT:
                raise AccountError("matrix_signed_out")
            if response.status_code >= 400:
                raise AccountError("matrix_failed")
            return answer
        raise AccountError("matrix_unreachable")

    # -- looks

    async def look(self) -> int:
        state = self.state()
        if not self.view()["connected"]:
            return 0
        now = time.time()
        params = {"timeout": 0, "filter": SYNC_FILTER if state["since"] else FIRST_FILTER}
        if state["since"]:
            params["since"] = state["since"]
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_S) as http:
                if not state["display"]:
                    with contextlib.suppress(AccountError):
                        got = await self._call(http, "GET", f"/profile/{quote(state['user_id'], safe='')}/displayname")
                        state["display"] = str(got.get("displayname") or "")
                batch = await self._call(http, "GET", "/sync", params=params)
        except AccountError as error:
            logger.info("matrix: a look failed (%s)", error)
            self.change(lambda s, code=str(error): s.update(error=code))
            return 0
        me = state["user_id"]
        rooms, names = state["rooms"], dict(state["names"])
        direct = set(state["direct"])
        for event in (batch.get("account_data") or {}).get("events") or []:
            if event.get("type") == "m.direct":
                direct = {r for ids in (event.get("content") or {}).values() if isinstance(ids, list) for r in ids}
        joined = (batch.get("rooms") or {}).get("join") or {}
        for rid in (batch.get("rooms") or {}).get("leave") or {}:
            rooms.pop(rid, None)
        said: dict[str, list[dict]] = {}
        first = not state["since"]
        for rid, room in joined.items():
            record = rooms.setdefault(rid, {"on": False})
            heroes = (room.get("summary") or {}).get("m.heroes")
            if heroes:
                record["heroes"] = [str(h) for h in heroes[:5]]
            timeline = (room.get("timeline") or {}).get("events") or []
            for event in ((room.get("state") or {}).get("events") or []) + timeline:
                self._state_event(record, names, event)
            if first or not record["on"] or record.get("encrypted"):
                continue
            said[rid] = [m for m in (self._message(e, me, state["display"], names, rid in direct) for e in timeline) if m]
        items, opened = [], {}
        for rid, messages in said.items():
            touched, opened[rid] = grow(rooms[rid].get("open"), messages)
            label = self.label(rooms[rid], names)
            items += [stretch_item(s, f"https://matrix.to/#/{rid}/{s['first']}", f"Matrix · {label}",
                                   label, now) for s in touched if s["others"]]
        await asyncio.to_thread(self.keep_items, items)
        since = str(batch.get("next_batch") or state["since"])

        def put(s: dict) -> None:
            if s.get("user_id") != me:
                return          # signed out or replaced while this look read
            for rid, still in opened.items():
                rooms[rid]["open"] = still
            # The person's choices made while this look read are kept.
            for rid, record in rooms.items():
                record["on"] = bool((s.get("rooms") or {}).get(rid, {}).get("on"))
            s.update(rooms=rooms, names=dict(list(names.items())[-NAMES_MAX:]), direct=sorted(direct), since=since,
                     display=state["display"], last=int(now), error="")

        self.change(put)
        logger.info("matrix: a look at %d rooms kept %d stretches", len(said), len(items))
        return len(items)

    @staticmethod
    def _state_event(record: dict, names: dict, event: dict) -> None:
        kind, content = event.get("type"), event.get("content") or {}
        if "state_key" not in event:
            return
        if kind == "m.room.name":
            record["name"] = str(content.get("name") or "")[:100]
        elif kind == "m.room.canonical_alias":
            record["alias"] = str(content.get("alias") or "")[:100]
        elif kind == "m.room.encryption":
            record["encrypted"] = True
        elif kind == "m.room.member" and content.get("displayname"):
            names[str(event["state_key"])] = str(content["displayname"])[:80]

    @staticmethod
    def _message(event: dict, me: str, display: str, names: dict, direct: bool) -> Optional[dict]:
        content = event.get("content") or {}
        if event.get("type") not in SPOKEN or "state_key" in event or not content:
            return None
        if (content.get("m.relates_to") or {}).get("rel_type") == "m.replace":
            return None     # an edit; the first version was kept
        line = plain_text(str(event["type"]), content)
        if not line:
            return None
        sender = str(event.get("sender") or "")
        body = str(content.get("body") or "").lower()
        called = [n.lower() for n in (display, localpart(me)) if n]
        mentions = (me in ((content.get("m.mentions") or {}).get("user_ids") or [])
                    or any(re.search(rf"(?<!\w){re.escape(n)}(?!\w)", body) for n in called))
        return {"id": str(event.get("event_id") or ""), "at": int(event.get("origin_server_ts") or 0) / 1000,
                "who": names.get(sender) or (display if sender == me else "") or localpart(sender), "line": " ".join(line.split()),
                "mine": sender == me, "mentions": direct or mentions}

    @staticmethod
    def label(record: dict, names: dict) -> str:
        heroes = ", ".join(names.get(h) or localpart(h) for h in record.get("heroes") or [])
        return record.get("name") or record.get("alias") or heroes or "Matrix"

    def view(self) -> dict:
        state = self.state()
        connected = bool(self.env(ENV_KEY) and state["user_id"])
        names = state["names"]
        return {"connected": connected, "account": state["user_id"] if connected else "",
                "last": iso(state["last"]) if connected else "", "problem": state["error"] if connected else "",
                "ready": True,
                "choices": [{"id": rid, "name": self.label(r, names), "on": r.get("on") is True}
                            for rid, r in state["rooms"].items() if not r.get("encrypted")] if connected else []}

    async def choose(self, on: list[str]) -> None:
        chosen = set(on)

        def turn(state: dict) -> None:
            for rid, record in (state.get("rooms") or {}).items():
                record["on"] = rid in chosen and not record.get("encrypted")

        self.change(turn)

    async def revoke(self) -> None:
        await self.close()
        if self.view()["connected"]:
            with contextlib.suppress(AccountError):
                async with httpx.AsyncClient(timeout=TIMEOUT_S) as http:
                    await self._call(http, "POST", "/logout", json={})
        # What it already brought stays in the feed, like the mail's.
        await asyncio.to_thread(self.keep_env, {ENV_KEY: ""})
        self.forget()
