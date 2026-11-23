"""The visitor browser: one headless browser on its own profile, never signed in, that walks and lookups
read the open web through. Every request it makes, each redirect hop included, goes only to a public address."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from . import installed_browser as web
from .pagefacts import host_ok, public_address
from .web import sites
from .web.tabs import PlaywrightTab

logger = logging.getLogger("mibo.roam")

IDLE_S = 300.0

class Visitor:
    """One headless browser on a profile that is never signed in, started when
    a page is wanted and stopped when none has been for a while."""

    def __init__(self, profile: Path, *, executable: Path | None = None,
                 host_check: Callable[[str], bool] = host_ok,
                 public: Callable[[str], Awaitable[bool]] = public_address, clock: Callable[[], float] = time.monotonic):
        self.browser = web.Browser(profile, executable=executable, headless=True)
        self.host_check = host_check
        self.public = public
        self.clock = clock
        self.lock = asyncio.Lock()
        self.used = 0.0
        self.context: Any = None

    def _allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        return parts.scheme in ("http", "https") and self.host_check(parts.hostname or "")

    async def _guard(self, route: Any) -> None:
        if self._allowed(route.request.url):
            await route.continue_()
        else:
            await route.abort("blockedbyclient")

    async def _watch(self, page: Any) -> None:
        """Check every request of `page`, each redirect hop included, which the
        route above is not shown; a page's own address is resolved too. The
        page names itself with Mibo's token on the browser's user agent."""
        session = await page.context.new_cdp_session(page)
        agent = await page.evaluate("() => navigator.userAgent")
        await session.send("Emulation.setUserAgentOverride", {"userAgent": f"{agent} {sites.TOKEN}"})
        pending: set = set()

        async def paused(event: dict) -> None:
            url, ident = str(event.get("request", {}).get("url", "")), event.get("requestId")
            try:
                if self._allowed(url) and (event.get("resourceType") != "Document" or await self.public(url)):
                    await session.send("Fetch.continueRequest", {"requestId": ident})
                else:
                    logger.info("roam: a request to %s was refused", urlsplit(url).hostname or "?")
                    await session.send("Fetch.failRequest", {"requestId": ident, "errorReason": "BlockedByClient"})
            except Exception:
                pass

        def heard(event: dict) -> None:
            task = asyncio.ensure_future(paused(event))
            pending.add(task)
            task.add_done_callback(pending.discard)
        session.on("Fetch.requestPaused", heard)
        await session.send("Fetch.enable", {"patterns": [{"urlPattern": "*", "requestStage": "Request"}]})

    async def _open(self) -> Any:
        if self.context is None:
            context = await self.browser.start()
            try:
                await context.route("**/*", self._guard)
                session = await context.browser.new_browser_cdp_session()
                await session.send("Browser.setDownloadBehavior", {"behavior": "deny"})
            except BaseException:
                await self.browser.stop()
                raise
            self.context = context
        return self.context

    @contextlib.asynccontextmanager
    async def page(self):
        """A fresh tab, the only one in use, closed after."""
        async with self.lock:
            context = await self._open()
            page = await context.new_page()
            try:
                await self._watch(page)
                yield page
            finally:
                self.used = self.clock()
                with contextlib.suppress(Exception):
                    await page.close()

    @contextlib.asynccontextmanager
    async def tab(self):
        """A fresh tab as web/tabs.py's Tab, the only one in use, closed after."""
        async with self.page() as page:
            yield PlaywrightTab(page)

    async def stop_if_idle(self) -> None:
        if self.context is not None and not self.lock.locked() and self.clock() - self.used >= IDLE_S:
            async with self.lock:
                await self.stop()

    async def stop(self) -> None:
        self.context = None
        await self.browser.stop()
