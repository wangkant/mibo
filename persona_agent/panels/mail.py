"""The mail panel: the person's own mailboxes the character reads, read-only,
and whether personal letters count.

The looks run in the page server (see `mailbox.Looks`), with no model and no
character service. The lifespan starts `app.state.mail.loop()` and cancels it
with its other tasks; the open connections are broken among the closers.
The page is shown each mailbox's address, never its secret.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

from fastapi import Request

from .. import langs, mailbox

ERRORS: frozenset[str] = frozenset({"mail_invalid", "mail_unknown", "mail_exists", "mail_login_failed",
                                    "mail_unreachable", "mail_refused", "mail_failed"})


def _when(at) -> str:
    return datetime.fromtimestamp(at).astimezone().isoformat(timespec="seconds") if isinstance(at, int) and at else ""


class Mail:
    def __init__(self, workspace):
        self.ws = workspace
        # The language the page last named; the provider names and steps follow it.
        self.page_lang = ""
        self.looks = mailbox.Looks(self.home, self.runtime)

    def home(self) -> Path:
        return self.ws.home

    def runtime(self) -> Path:
        return self.ws._runtime()

    def heard(self, lang) -> None:
        self.page_lang = langs.normalize(lang) or self.page_lang

    def _zh(self) -> int:
        lang = self.page_lang or langs.normalize(self.ws.config().get("AGENT_LANG")) or "en"
        return 1 if lang in ("zh", "zh-TW") else 0

    def view(self) -> dict:
        zh = self._zh()
        state = mailbox.load_state(self.runtime())

        def shown(account: dict) -> dict:
            last = state["last"].get(account["key"], {})
            return {"key": account["key"], "address": account["address"], "provider": account["provider"],
                    "on": account.get("on", True) is not False, "at": _when(last.get("at")),
                    "count": int(last.get("count") or 0), "error": str(last.get("error") or "")}

        # `code` opens the page where the provider makes the code; `domains` pick the provider from the address.
        providers = [{"key": p.key, "name": p.name[zh], "secret": p.secret[zh], "help": p.help[zh],
                      "steps": list(p.steps[zh]), "host": p.host, "code": p.code, "domains": list(p.domains)}
                     for p in mailbox.PROVIDERS.values()]
        return {"accounts": [shown(a) for a in mailbox.load_accounts(self.home())],
                "providers": providers, "letters": state["letters"], "running": self.looks.busy}

    async def add(self, payload: dict) -> dict:
        # With no provider the address picks one, so QQ, Foxmail, 163 and 126 need only the address and the code.
        account = mailbox.new_account(payload.get("provider"), payload.get("address"),
                                      payload.get("secret"), payload.get("host"))
        if any(a["key"] == account["key"] for a in await asyncio.to_thread(mailbox.load_accounts, self.home())):
            raise ValueError("mail_exists")
        # Kept only once the provider has taken the secret.
        await asyncio.to_thread(mailbox.check, account)

        def put(accounts: list[dict]) -> None:
            accounts[:] = [a for a in accounts if a["key"] != account["key"]] + [account]

        await asyncio.to_thread(mailbox.change_accounts, self.home(), put)
        # A mailbox just added is read now, not half an hour from now.
        self.looks.ask(even_if_running=True)
        return await asyncio.to_thread(self.view)

    def _known(self, key) -> None:
        if key not in {a["key"] for a in mailbox.load_accounts(self.home())}:
            raise ValueError("mail_unknown")

    def remove(self, payload: dict) -> dict:
        key = payload.get("key")
        self._known(key)

        def drop(accounts: list[dict]) -> None:
            accounts[:] = [a for a in accounts if a["key"] != key]

        # What it already brought stays in the feed, like a walk's finds.
        mailbox.change_accounts(self.home(), drop)
        mailbox.change_state(self.runtime(), lambda state: state["last"].pop(key, None))
        return self.view()

    def toggle(self, payload: dict) -> dict:
        key, on = payload.get("key"), payload.get("on")
        if not isinstance(on, bool):
            raise ValueError("mail_invalid")
        self._known(key)

        def turn(accounts: list[dict]) -> None:
            for account in accounts:
                if account["key"] == key:
                    account["on"] = on

        mailbox.change_accounts(self.home(), turn)
        return self.view()

    def options(self, payload: dict) -> dict:
        letters = payload.get("letters")
        if not isinstance(letters, bool):
            raise ValueError("mail_invalid")
        mailbox.change_state(self.runtime(), lambda state: state.update(letters=letters))
        return self.view()


def mount(app, workspace, body) -> None:
    panel = Mail(workspace)
    app.state.mail = panel.looks
    app.state.closers.append(panel.looks.close)

    async def read(request: Request) -> dict:
        payload = await body(request)
        panel.heard(payload.get("lang"))
        return payload

    @app.get("/api/mail")
    async def mail_view(lang: str = ""):
        panel.heard(lang)
        return await asyncio.to_thread(panel.view)

    @app.post("/api/mail/add")
    async def mail_add(request: Request):
        return await panel.add(await read(request))

    @app.post("/api/mail/remove")
    async def mail_remove(request: Request):
        return await asyncio.to_thread(panel.remove, await read(request))

    # A look is asked for here, on the event loop: the wake-up is not for worker threads.
    @app.post("/api/mail/toggle")
    async def mail_toggle(request: Request):
        payload = await read(request)
        view = await asyncio.to_thread(panel.toggle, payload)
        if payload["on"]:
            panel.looks.ask(even_if_running=True)
        return view

    @app.post("/api/mail/options")
    async def mail_options(request: Request):
        payload = await read(request)
        view = await asyncio.to_thread(panel.options, payload)
        if payload["letters"]:
            panel.looks.ask(even_if_running=True)
        return view

    @app.post("/api/mail/refresh")
    async def mail_refresh(request: Request):
        await read(request)
        panel.looks.ask()
        return {"ok": True}
