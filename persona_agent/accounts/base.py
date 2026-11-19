"""What every account the person connects has in common.

A connector is made with the page's workspace. It says how it connects (`how`),
what it can read (`reads`) and, when that needs the person's say first, a
warning (`warn`). The page calls `start` until it answers {"done": true} or
something to show (a link, a code, a QR, fields to fill), then `poll` until the
state is no longer "pending" or "scanned". The accounts loop calls `look`.

Secrets and tokens are kept in `<home>/.env` (`keep_env`), everything else in
`<runtime>/accounts/<key>.json` (`load` / `change`). An error is an
AccountError whose text is a short code that starts with the key, such as
outlook_denied; the page explains it by that code.

`values["browser"]` is False when the system browser cannot be opened here
(the page is on another device, or no browser starts): a connector with
another way in (a device code) uses that one instead.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import parse_qs, urlsplit

from .. import privacy
from .. import setup_wizard as sw
from ..library import Item, Library
from ..storage import atomic_write_text

# How often the accounts loop looks at a connected account, unless a connector says otherwise.
LOOK_EVERY_S = 5 * 60


class AccountError(ValueError):
    """`str()` is the error code. A ValueError, so the page answers it by its code."""


def iso(at) -> str:
    """Seconds since 1970 as local ISO time; "" for none."""
    return datetime.fromtimestamp(at).astimezone().isoformat(timespec="seconds") if at else ""


def utc_iso(at: float) -> str:
    return datetime.fromtimestamp(at, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# Each connector's state file is written from the page's worker threads and from the looks.
_locks: dict[str, threading.Lock] = {}
_locks_lock = threading.Lock()


def _lock(key: str) -> threading.Lock:
    with _locks_lock:
        return _locks.setdefault(key, threading.Lock())


class Connector:
    key: str = ""
    name: tuple[str, str] = ("", "")
    how: str = "fields"                     # browser | code | qr | paste | fields
    warn: Optional[tuple[str, str]] = None
    reads: tuple[str, str] = ("", "")
    # Seconds between the loop's looks at this account.
    every: int = LOOK_EVERY_S
    # True when a loop of its own reads the account, not the accounts loop; `wake` asks it for a look now.
    own_loop: bool = False
    # "mail" or "message" for the person's own mail or private talk: kept only as privacy.py allows.
    private: str = ""

    def __init__(self, workspace):
        self.ws = workspace

    # -- what the page and the loop call

    async def start(self, values: dict) -> dict:
        raise NotImplementedError

    async def poll(self) -> dict:
        return {"state": "done", "error": ""}

    async def look(self) -> int:
        raise NotImplementedError

    def view(self) -> dict:
        raise NotImplementedError

    async def choose(self, on: list[str]) -> None:
        raise AccountError(f"{self.key}_invalid")

    async def revoke(self) -> None:
        raise NotImplementedError

    async def close(self) -> None:
        """Called when the app stops: end anything still running (a socket, a sign-in)."""

    def wake(self) -> None:
        """For an `own_loop` connector: look now."""

    # -- where things are kept

    def runtime(self) -> Path:
        return self.ws._runtime()

    def state_path(self) -> Path:
        return self.runtime() / "accounts" / f"{self.key}.json"

    def load(self) -> dict:
        try:
            saved = json.loads(self.state_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return saved if isinstance(saved, dict) else {}

    def change(self, change: Callable[[dict], None]) -> dict:
        """Read the state, let `change` edit it, write it back atomically."""
        with _lock(self.key):
            state = self.load()
            change(state)
            atomic_write_text(self.state_path(), json.dumps(state, ensure_ascii=False, indent=1))
            return state

    def forget(self) -> None:
        with _lock(self.key):
            self.state_path().unlink(missing_ok=True)

    def env(self, name: str) -> str:
        return self.ws.config().get(name, "")

    def keep_env(self, values: dict) -> None:
        """Secrets into the home's .env; "" removes one."""
        sw.write_env(self.ws.env, values)

    def client_id(self, constant: str, env_name: str) -> str:
        """An app id the author registers: the module's constant, or the environment's."""
        return os.environ.get(env_name) or self.env(env_name) or constant

    def keep_items(self, items: list[Item]) -> int:
        """Add to the library on this computer; how many."""
        if self.private:
            return privacy.keep(self.runtime(), self.ws.config(), items, self.private)
        library = Library(self.runtime())
        for item in items:
            library.add(item)
        return len(items)

    def known(self) -> set[str]:
        """The ids already in the library, read once; call it in a thread, the file is large.
        Private talk counted while the character may not read it is known too."""
        known = set(Library(self.runtime())._rows())
        return known | privacy.seen(self.runtime()) if self.private else known


# ------------------------------------------------------------- sign-in return --

DONE_PAGE = ("<!doctype html><html><head><meta charset=\"utf-8\"><title>personagent</title></head>"
             "<body style=\"font:16px system-ui;margin:3em\"><p>{}</p></body></html>")
DONE_TEXT = ("Signed in. You can close this tab and go back to personagent. "
             "已登录，可以关闭此标签页，回到 personagent。")
FAILED_TEXT = "Sign-in was not completed. 登录未完成。"


class Loopback:
    """A one-time listener on this computer where a sign-in in the system
    browser comes back (an http://localhost redirect, as OAuth allows for
    apps on a computer). `redirect` is the address to give the provider;
    `wait()` gives the query it came back with."""

    def __init__(self, path: str = "/"):
        self.path = path
        self.port = 0
        self._servers: list[asyncio.base_events.Server] = []
        self._got: asyncio.Future = asyncio.get_running_loop().create_future()

    @property
    def redirect(self) -> str:
        return f"http://localhost:{self.port}{self.path}"

    async def open(self) -> "Loopback":
        server = await asyncio.start_server(self._answer, "127.0.0.1", 0)
        self.port = server.sockets[0].getsockname()[1]
        self._servers.append(server)
        # A browser may take localhost as ::1 first.
        with contextlib.suppress(OSError):
            self._servers.append(await asyncio.start_server(self._answer, "::1", self.port))
        return self

    async def _answer(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            line = await asyncio.wait_for(reader.readline(), 10)
            while (await asyncio.wait_for(reader.readline(), 10)).strip():
                pass
            parts = line.decode("latin-1").split()
            target = urlsplit(parts[1]) if len(parts) >= 2 and parts[0] == "GET" else None
            mine = target is not None and target.path == self.path and target.query
            query = {k: v[0] for k, v in parse_qs(target.query).items()} if mine else {}
            if mine and not self._got.done():
                self._got.set_result(query)
            text = DONE_TEXT if mine and "code" in query else FAILED_TEXT
            body = DONE_PAGE.format(text).encode("utf-8") if mine else b""
            status = "200 OK" if mine else "404 Not Found"
            writer.write(f"HTTP/1.1 {status}\r\nContent-Type: text/html; charset=utf-8\r\n"
                         f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode() + body)
            await writer.drain()
        except (asyncio.TimeoutError, OSError, UnicodeError, ValueError):
            pass
        finally:
            writer.close()

    async def wait(self, seconds: float) -> dict:
        """The query the browser came back with; asyncio.TimeoutError when it does not."""
        try:
            return await asyncio.wait_for(asyncio.shield(self._got), seconds)
        finally:
            self.close()

    def close(self) -> None:
        for server in self._servers:
            server.close()
        self._servers = []
