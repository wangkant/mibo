"""A page tab over one Electron view (web.tabs.Tab), for reading and operating as PaneTab does over WebView2.

Calls go through the view's webContents.debugger in Electron's main process: no debugging port is opened. The
`link` is the app's side of the connection to that process, with three blocking calls:

- `call(op, **fields)` sends one request and gives back its result, or raises RuntimeError with Electron's reason;
- `cdp(tab, method, params, session)` is `call("cdp", ...)`;
- `listen(tab, event, handler)` calls `handler(params, session)` for each DevTools event of that view, on the
  link's own thread, which must never wait for an answer.

Frames from another site are attached with Target.setAutoAttach (flatten) and reached through their session id."""
from __future__ import annotations

import asyncio
import contextlib
import threading
import time
from collections.abc import Callable
from typing import Any

from ..web.tabs import AUTO_ATTACH, OPEN_S, Answer, TabError, _BlockingTab


class ElectronTab(_BlockingTab):
    def __init__(self, link: Any, tab: str):
        super().__init__()
        self.link = link
        self.tab = tab
        # Frame sessions: id -> made ready (frames under it attached, Fetch on while it is on in the page).
        self._frames: dict[str, bool] = {}
        self._watching = False

    @property
    def url(self) -> str:
        return self.link.call("tab.url", tab=self.tab)["url"]

    def _call(self, method: str, params: dict, session: str) -> dict:
        return self.link.cdp(self.tab, method, params, session)

    def _attached(self) -> list[str]:
        return list(self._frames)

    async def frames(self) -> list[str]:
        if not self._watching:
            self._watching = True
            self.link.listen(self.tab, "Target.attachedToTarget", self._on_attached)
            self.link.listen(self.tab, "Target.detachedFromTarget", self._on_detached)
            await self.cdp("Target.setAutoAttach", AUTO_ATTACH)
        for session in [s for s, ready in list(self._frames.items()) if not ready]:
            await asyncio.to_thread(self._ready, session)
        return list(self._frames)

    def _on_attached(self, params: dict, session: str) -> None:
        # On the link's thread: the frame is made ready on another, since that waits for answers.
        if (params.get("targetInfo") or {}).get("type") == "iframe":
            self._frames[params["sessionId"]] = False
            threading.Thread(target=self._ready, args=(params["sessionId"],), daemon=True).start()

    def _on_detached(self, params: dict, session: str) -> None:
        self._frames.pop(params.get("sessionId", ""), None)

    def _ready(self, session: str) -> None:
        """Frames from another site under this frame attached too, and Fetch on in it while it is on in the page.
        A frame gone meanwhile is dropped."""
        try:
            self._call("Target.setAutoAttach", AUTO_ATTACH, session)
            if self._fetch is not None:
                self._call("Fetch.enable", self._fetch, session)
        except RuntimeError:
            self._frames.pop(session, None)
            return
        if session in self._frames:
            self._frames[session] = True

    async def goto(self, url: str, *, referer: str = "", timeout_s: float = OPEN_S) -> Answer:
        answer = await self.cdp("Page.navigate", {"url": url, **({"referrer": referer} if referer else {})})
        if answer.get("errorText"):
            raise TabError(str(answer["errorText"]))
        began = time.monotonic()
        while time.monotonic() - began < timeout_s:
            await asyncio.sleep(0.2)
            with contextlib.suppress(RuntimeError):
                if await self.evaluate("() => document.readyState") in ("interactive", "complete"):
                    break
        return Answer(self.url)

    async def events(self, name: str, handler: Callable[[dict], None]) -> None:
        if name in ("navigation", "load"):
            await self.cdp("Page.enable", {})
            # The main frame's address as it last moved: the link's thread may not ask Electron for it.
            here = {"url": ""}

            def moved(params: dict, session: str) -> None:
                frame = params.get("frame") or {}
                if session or frame.get("parentId"):
                    return
                here["url"] = frame.get("url", "")
                if name == "navigation":
                    handler({"url": here["url"]})
            self.link.listen(self.tab, "Page.frameNavigated", moved)
            if name == "load":
                self.link.listen(self.tab, "Page.loadEventFired",
                                 lambda params, session: None if session else handler({"url": here["url"]}))
        elif name.startswith("Fetch."):
            # Fetch events come from the page and from its frames: each answer goes back where it came from.
            self.link.listen(self.tab, name, lambda params, session: (self._heard(session, params), handler(params)))
        else:
            self.link.listen(self.tab, name, lambda params, session: None if session else handler(params))

    async def close(self) -> None:
        await asyncio.to_thread(self.link.call, "tab.close", tab=self.tab)
