"""Discord through a bot the person makes, as accounts_discord.py reads it.

The same token in .env and the same `<runtime>/discord.json`, so a bot
connected on the Discord panel shows here too. What this adds is fewer clicks:
the portal opens where the next step is, and once the token is in, the app
opens the bot's invite itself and waits until the bot is in a server.
"""
from __future__ import annotations

import asyncio
import time

from .. import accounts_discord as dc
from .base import Connector, iso

# While the page waits for the invite, Discord is asked at most this often.
ASK_EVERY_S = 3

FIELD_LABEL = ("Bot token", "机器人令牌")
STEPS = ("The link opens the Discord Developer Portal: choose New Application, any name will do. On its Bot "
         "page turn on Message Content Intent, save, then choose Reset Token and paste the token here. It stays "
         "on this computer. Then the app opens the bot's invite for you: pick each server to read.",
         "链接会打开 Discord 开发者门户：点 New Application 新建一个应用，名字随意。在它的 Bot 页面打开 "
         "Message Content Intent 并保存，再点 Reset Token，把令牌粘贴到这里。令牌只保存在这台电脑上。"
         "之后应用会替你打开机器人的邀请页：选上每个想让角色读的服务器。")
INTENT_OFF = ("Message Content Intent is still off for this bot. The link opens its Bot page: turn it on, save, "
              "then paste the token again.",
              "这个机器人的 Message Content Intent 还没打开。链接会打开它的 Bot 页面：打开它并保存，然后再粘贴一次令牌。")


class DiscordBot(Connector):
    key = "discord"
    name = ("Discord", "Discord")
    how = "paste"
    reads = ("Only the channels you switch on, in servers you add your own read-only bot to; never your direct "
             "messages, and it never signs in as you.",
             "只读你把自己的只读机器人加进去的服务器里、你打开的频道；不读你的私信，也从不以你的身份登录。")
    errors = frozenset({"discord_invalid", "discord_not_connected", "discord_token_invalid",
                        "discord_intent_missing", "discord_unreachable", "discord_failed"})
    every = dc.LOOK_EVERY_S
    # The Discord panel's loop reads it (app.state.discord.loop()), through the same Looks.
    own_loop = True

    def __init__(self, workspace):
        super().__init__(workspace)
        self.looks = dc.looks_for(workspace)
        self._asked = 0.0

    def token(self) -> str:
        return self.env(dc.ENV_KEY)

    def wake(self) -> None:
        self.looks.ask()

    @staticmethod
    def _ask(link: str, words: tuple[str, str], error: str = "") -> dict:
        return {"fields": [{"key": "token", "label": FIELD_LABEL, "secret": True, "help": words}], "link": link,
                **({"error": error} if error else {})}

    async def start(self, values: dict) -> dict:
        if not str(values.get("token") or "").strip():
            return self._ask(dc.PORTAL, STEPS)
        token = dc.clean_token(values["token"])
        async with dc.client(token) as http:
            known = await dc.identify(http)
            if not known["content"]:
                # Straight to the page with the switch on it.
                return self._ask(dc.bot_page(known["app"]), INTENT_OFF, "discord_intent_missing")
            found = await dc.servers(http, known["bot"]["id"])
        # Kept only once Discord has taken the token.
        await asyncio.to_thread(self.keep_env, {dc.ENV_KEY: token})
        now = time.time()

        def put(state: dict) -> None:
            if state["bot"]["id"] != known["bot"]["id"]:
                # Another bot: what the last one read does not carry over.
                state.update(dc.blank_state())
            state.update(bot=known["bot"], app=known["app"], owner=known["owner"], error="")
            dc.merge_servers(state, found, now)

        await asyncio.to_thread(dc.change_state, self.runtime(), put)
        return {"done": True} if found else {"browser": dc.invite(known["app"])}

    async def poll(self) -> dict:
        state = await asyncio.to_thread(dc.load_state, self.runtime())
        bot = state["bot"]["id"]
        if not (self.token() and bot):
            return {"state": "failed", "error": "discord_not_connected"}
        if state["servers"]:
            return {"state": "done", "error": ""}
        if time.monotonic() - self._asked < ASK_EVERY_S:
            return {"state": "pending", "error": ""}
        self._asked = time.monotonic()
        try:
            async with dc.client(self.token()) as http:
                state = await self.looks.sync(http, bot)
        except dc.DiscordError as error:
            return {"state": "failed", "error": str(error)}
        return {"state": "done" if state["servers"] else "pending", "error": ""}

    async def look(self) -> int:
        return await self.looks.look()

    def view(self) -> dict:
        state = dc.load_state(self.runtime())
        if not (self.token() and state["bot"]["id"]):
            return {"connected": False, "account": "", "last": "", "problem": "", "ready": True, "choices": [],
                    "invite": ""}
        channels = state["channels"]
        return {"connected": True, "account": state["bot"]["name"], "last": iso(state["last"]),
                "problem": state["error"], "ready": True,
                "choices": [{"id": c["id"], "name": f"{s['name']} · #{c['name']}",
                             "on": channels.get(c["id"], {}).get("on") is True}
                            for s in state["servers"] for c in s["channels"]],
                # To add the bot to another server later.
                "invite": dc.invite(state["app"])}

    async def choose(self, on: list[str]) -> None:
        if not await asyncio.to_thread(lambda: self.view()["connected"]):
            raise dc.DiscordError("discord_not_connected")
        chosen = set(on)

        def turn(state: dict) -> None:
            for cid, record in state["channels"].items():
                record["on"] = cid in chosen

        await asyncio.to_thread(dc.change_state, self.runtime(), turn)

    async def revoke(self) -> None:
        # What it already brought stays in the feed, like the mail's.
        await asyncio.to_thread(self.keep_env, {dc.ENV_KEY: ""})
        await asyncio.to_thread(dc.forget, self.runtime())
