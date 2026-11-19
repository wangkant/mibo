"""The Discord panel: the person's own servers, read through a bot they add,
and which of their channels count.

The looks run in the page server (see `accounts_discord.Looks`), with no model
and no character service. The lifespan starts `app.state.discord.loop()` and
cancels it with its other tasks. The page is shown the bot's name, never its token.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime
from pathlib import Path

from fastapi import Request

from .. import accounts_discord as dc, langs
from .. import setup_wizard as sw

ERRORS: frozenset[str] = frozenset({"discord_invalid", "discord_not_connected", "discord_token_invalid",
                                    "discord_intent_missing", "discord_unreachable", "discord_failed"})

STEPS = (("Open the Discord Developer Portal and create a New Application; any name will do.",
          "On its Bot page, turn on Message Content Intent and save.",
          "On the same page, choose Reset Token, copy the token and paste it here. It stays on this computer.",
          "Open the invite link shown here and add the bot to each server you want read. "
          "It can only read, never post; adding a bot needs the Manage Server permission there."),
         ("打开 Discord 开发者门户，点 New Application 新建一个应用，名字随意。",
          "在它的 Bot 页面打开 Message Content Intent，然后保存。",
          "在同一页点 Reset Token，复制令牌并粘贴到这里。令牌只保存在这台电脑上。",
          "打开这里显示的邀请链接，把机器人加入每个想让角色读的服务器。"
          "它只能读，不会发言；加机器人需要你在那个服务器有“管理服务器”权限。"))


def _when(at) -> str:
    return datetime.fromtimestamp(at).astimezone().isoformat(timespec="seconds") if isinstance(at, int) and at else ""


class Discord:
    def __init__(self, workspace):
        self.ws = workspace
        # The language the page last named; the steps follow it.
        self.page_lang = ""
        self.looks = dc.looks_for(workspace)

    def token(self) -> str:
        return self.ws.config().get(dc.ENV_KEY, "")

    def runtime(self) -> Path:
        return self.ws._runtime()

    def heard(self, lang) -> None:
        self.page_lang = langs.normalize(lang) or self.page_lang

    def _zh(self) -> int:
        lang = self.page_lang or langs.normalize(self.ws.config().get("AGENT_LANG")) or "en"
        return 1 if lang in ("zh", "zh-TW") else 0

    def view(self) -> dict:
        state = dc.load_state(self.runtime())
        connected = bool(self.token() and state["bot"]["id"])
        channels = state["channels"]
        return {"connected": connected, "bot": state["bot"] if connected else None,
                "invite": dc.invite(state["app"]) if connected else "",
                "servers": [{"id": s["id"], "name": s["name"],
                             "channels": [{"id": c["id"], "name": c["name"],
                                           "on": channels.get(c["id"], {}).get("on") is True}
                                          for c in s["channels"]]}
                            for s in state["servers"]] if connected else [],
                "last": _when(state["last"]) if connected else "", "problem": state["error"] if connected else "",
                "running": self.looks.busy, "portal": dc.PORTAL, "steps": list(STEPS[self._zh()])}

    async def connect(self, payload: dict) -> dict:
        token = dc.clean_token(payload.get("token"))
        async with dc.client(token) as http:
            known = await dc.identify(http)
            if not known["content"]:
                raise dc.DiscordError("discord_intent_missing")
            found = await dc.servers(http, known["bot"]["id"])
        # Kept only once Discord has taken the token.
        await asyncio.to_thread(sw.write_env, self.ws.env, {dc.ENV_KEY: token})
        now = time.time()

        def put(state: dict) -> None:
            if state["bot"]["id"] != known["bot"]["id"]:
                # Another bot: what the last one read does not carry over.
                state.update(dc.blank_state())
            state.update(bot=known["bot"], app=known["app"], owner=known["owner"], error="")
            dc.merge_servers(state, found, now)

        await asyncio.to_thread(dc.change_state, self.runtime(), put)
        self.looks.ask()
        return await asyncio.to_thread(self.view)

    def _connected(self) -> dict:
        state = dc.load_state(self.runtime())
        if not (self.token() and state["bot"]["id"]):
            raise dc.DiscordError("discord_not_connected")
        return state

    def channels(self, payload: dict) -> dict:
        on = payload.get("on")
        if not isinstance(on, list) or not all(isinstance(c, str) for c in on):
            raise dc.DiscordError("discord_invalid")
        self._connected()
        chosen = set(on)

        def turn(state: dict) -> None:
            for cid, record in state["channels"].items():
                record["on"] = cid in chosen

        dc.change_state(self.runtime(), turn)
        return self.view()

    def remove(self) -> dict:
        # What it already brought stays in the feed, like the mail's.
        sw.write_env(self.ws.env, {dc.ENV_KEY: ""})
        dc.forget(self.runtime())
        return self.view()

    async def refresh(self) -> dict:
        state = await asyncio.to_thread(self._connected)
        async with dc.client(self.token()) as http:
            await self.looks.sync(http, state["bot"]["id"])
        self.looks.ask()
        return await asyncio.to_thread(self.view)


def mount(app, workspace, body) -> None:
    panel = Discord(workspace)
    app.state.discord = panel.looks

    async def read(request: Request) -> dict:
        payload = await body(request)
        panel.heard(payload.get("lang"))
        return payload

    @app.get("/api/discord")
    async def discord_view(lang: str = ""):
        panel.heard(lang)
        return await asyncio.to_thread(panel.view)

    @app.post("/api/discord/connect")
    async def discord_connect(request: Request):
        return await panel.connect(await read(request))

    # A look is asked for here, on the event loop: the wake-up is not for worker threads.
    @app.post("/api/discord/channels")
    async def discord_channels(request: Request):
        view = await asyncio.to_thread(panel.channels, await read(request))
        panel.looks.ask()
        return view

    @app.post("/api/discord/remove")
    async def discord_remove(request: Request):
        await read(request)
        return await asyncio.to_thread(panel.remove)

    @app.post("/api/discord/refresh")
    async def discord_refresh(request: Request):
        await read(request)
        return await panel.refresh()
