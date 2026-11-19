"""The accounts panel: every account the person can connect (see accounts/),
one way to connect them, and the loop that reads the connected ones.

The page lists them with GET /api/accounts, starts one with
/api/accounts/start (again with the fields filled, when it asks for some),
polls until it is done, then switches its channels with /choose. A link to
open in the system browser is opened here, on this computer; when it cannot
be (the page is on another device, or no browser starts), the connector is
asked again with values["browser"] = False and may hand back a device code.

The lifespan starts `app.state.accounts.loop()` and cancels it with its other
tasks: each connected account is looked at every few minutes (its connector's
`every`), at once when it is connected or asked, one look per account at a time.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
import webbrowser

from fastapi import Request

from .. import quiet
from ..accounts import CONNECTORS, AccountError, Connector

logger = logging.getLogger("agent.accounts")

# A look soon after the app starts; then the loop sleeps until the next account is due, at least this long.
FIRST_LOOK_S = 20
TICK_S = 15
CHOICES_MAX = 2000
_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}")


class _Codes(frozenset):
    """Every connector's codes: the ones named here, and any short snake_case
    code that starts with a connector's key, as base.py has them."""

    def __contains__(self, code) -> bool:
        return isinstance(code, str) and (frozenset.__contains__(self, code) or (
            bool(_CODE.fullmatch(code)) and any(code.startswith(c.key + "_") for c in CONNECTORS)))


ERRORS: frozenset[str] = _Codes({"accounts_unknown", "accounts_invalid"} | {
    f"{c.key}_{what}" for c in CONNECTORS
    for what in ("invalid", "not_ready", "not_connected", "denied", "expired", "unreachable", "failed",
                 "limited")})


def open_browser(url: str) -> bool:
    try:
        return bool(webbrowser.open(url))
    except Exception:
        return False


class Accounts:
    def __init__(self, workspace):
        self.ws = workspace
        self.connectors: dict[str, Connector] = {c.key: c(workspace) for c in CONNECTORS}
        self._locks = {key: asyncio.Lock() for key in self.connectors}
        self._due = {key: 0.0 for key in self.connectors}
        self._asked: set[str] = set()
        self._wake = asyncio.Event()
        self._looks: dict[str, asyncio.Task] = {}
        self._polled: dict[str, str] = {}

    def get(self, key) -> Connector:
        if not isinstance(key, str) or key not in self.connectors:
            raise AccountError("accounts_unknown")
        return self.connectors[key]

    def entry(self, connector: Connector) -> dict:
        return {"key": connector.key, "name": list(connector.name), "how": connector.how,
                "warn": list(connector.warn) if connector.warn else None, "reads": list(connector.reads),
                **connector.view()}

    def listing(self) -> dict:
        return {"accounts": [self.entry(c) for c in self.connectors.values()]}

    def ask(self, key: str) -> None:
        """Look at this account now (on the event loop)."""
        if self.connectors[key].own_loop:
            self.connectors[key].wake()
            return
        self._asked.add(key)
        self._wake.set()

    # -- the routes' work

    async def start(self, payload: dict, remote: bool) -> dict:
        connector = self.get(payload.get("key"))
        values = payload.get("values") if payload.get("values") is not None else {}
        if not isinstance(values, dict) or not all(isinstance(k, str) for k in values):
            raise AccountError("accounts_invalid")
        values = {**values, "browser": False} if remote else dict(values)
        self._polled.pop(connector.key, None)
        answer = await connector.start(values)
        if "browser" in answer and not remote:
            if await asyncio.to_thread(open_browser, answer["browser"]):
                return {**answer, "opened": True}
            # No browser here: the connector's other way in, if it has one.
            answer = await connector.start({**values, "browser": False})
        if answer.get("done"):
            self.ask(connector.key)
        return {**answer, "opened": False} if "browser" in answer else answer

    async def poll(self, key) -> dict:
        connector = self.get(key)
        answer = await connector.poll()
        # Several keep answering done once connected: a look only when it first turns done.
        if answer.get("state") == "done" and self._polled.get(connector.key) != "done":
            self.ask(connector.key)
        self._polled[connector.key] = answer.get("state")
        return answer

    async def choose(self, payload: dict) -> dict:
        connector = self.get(payload.get("key"))
        on = payload.get("on")
        if not isinstance(on, list) or len(on) > CHOICES_MAX or not all(isinstance(c, str) for c in on):
            raise AccountError("accounts_invalid")
        await connector.choose(on)
        self.ask(connector.key)
        return await asyncio.to_thread(self.entry, connector)

    async def refresh(self, payload: dict) -> dict:
        connector = self.get(payload.get("key"))
        if not (await asyncio.to_thread(connector.view))["connected"]:
            raise AccountError(f"{connector.key}_not_connected")
        count = await self._look(connector)
        return {**await asyncio.to_thread(self.entry, connector), "count": count}

    async def revoke(self, payload: dict) -> dict:
        connector = self.get(payload.get("key"))
        task = self._looks.get(connector.key)
        if task:
            task.cancel()
        # What it already brought stays in the feed.
        async with self._locks[connector.key]:
            await connector.revoke()
        return await asyncio.to_thread(self.entry, connector)

    # -- the looks

    async def _look(self, connector: Connector) -> int:
        async with self._locks[connector.key]:
            try:
                return await connector.look()
            finally:
                self._due[connector.key] = time.monotonic() + connector.every

    async def _look_quietly(self, connector: Connector) -> None:
        try:
            count = await self._look(connector)
            logger.info("accounts: %s kept %d", connector.key, count)
        except AccountError as error:
            logger.info("accounts: a look at %s failed (%s)", connector.key, error)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("accounts: a look at %s failed", connector.key)
        finally:
            self._looks.pop(connector.key, None)

    async def _wait(self, seconds: float) -> None:
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._wake.wait(), seconds)
        self._wake.clear()

    async def loop(self) -> None:
        try:
            await self._wait(FIRST_LOOK_S)
            while True:
                await quiet.wait()
                now = time.monotonic()
                for key, connector in self.connectors.items():
                    if connector.own_loop or key in self._looks or not (key in self._asked or now >= self._due[key]):
                        continue
                    self._asked.discard(key)
                    try:
                        connected = (await asyncio.to_thread(connector.view))["connected"]
                    except Exception:
                        logger.exception("accounts: %s could not say whether it is connected", key)
                        connected = False
                    if connected:
                        self._looks[key] = asyncio.create_task(self._look_quietly(connector))
                    else:
                        self._due[key] = now + connector.every
                # Asleep until the next one is due (one looking now: its own time after); a connect wakes it (ask).
                soon = min(now + c.every if key in self._looks else self._due[key]
                           for key, c in self.connectors.items() if not c.own_loop)
                await self._wait(max(TICK_S, soon - time.monotonic()))
        finally:
            looks = list(self._looks.values())
            for task in looks:
                task.cancel()
            # Ended before the connectors close, so a close never runs beside a look.
            await asyncio.gather(*looks, return_exceptions=True)
            for connector in self.connectors.values():
                with contextlib.suppress(Exception):
                    await connector.close()


def mount(app, workspace, body) -> None:
    accounts = Accounts(workspace)
    app.state.accounts = accounts

    @app.get("/api/accounts")
    async def accounts_list():
        return await asyncio.to_thread(accounts.listing)

    @app.post("/api/accounts/start")
    async def accounts_start(request: Request):
        return await accounts.start(await body(request), bool(getattr(request.state, "remote", False)))

    @app.get("/api/accounts/poll")
    async def accounts_poll(key: str = ""):
        return await accounts.poll(key)

    @app.post("/api/accounts/choose")
    async def accounts_choose(request: Request):
        return await accounts.choose(await body(request))

    @app.post("/api/accounts/refresh")
    async def accounts_refresh(request: Request):
        return await accounts.refresh(await body(request))

    @app.post("/api/accounts/revoke")
    async def accounts_revoke(request: Request):
        return await accounts.revoke(await body(request))
