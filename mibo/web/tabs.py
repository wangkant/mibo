"""A tab: one page somebody can drive, whatever browser it is in.

Reading (read.py) and operating go through this shape only, so the same code
serves the signed-out headless visitor (PlaywrightTab, here) and the person's
own pane. Every method is a coroutine; a tab over a browser whose calls block
runs them on a thread of its own.

- `goto(url)` opens an address and answers once the document is there:
  an `Answer` (final address, HTTP status, content type, the body on demand),
  or raises TabError with the browser's own reason (net::ERR_...).
- `url` is where the page is now.
- `evaluate(script, arg)` runs a JavaScript function expression with `arg`
  in the page and gives back its JSON value. Scripts stay synchronous: a pane
  does not wait for promises.
- `cdp(method, params)` sends one Chrome DevTools Protocol command to the page.
- `events(name, handler)` calls `handler(dict)` on "navigation" (the main
  frame moved: {"url"}), "load" ({"url"}) or any CDP event name.
- `scroll(screens)` moves the page down that many screens, as a wheel does.
- `close()` closes the tab.

No tab reads cookies or storage out, and none opens a debugging port.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

# How long an address may take to start answering, and its document to be parsed after.
OPEN_S = 30.0
PARSED_S = 20.0


class TabError(Exception):
    """A navigation the browser itself failed; the message is the browser's reason."""


@dataclass
class Answer:
    url: str
    status: int = 0
    kind: str = ""                     # the content type, lower case
    length: int = 0                    # the declared content length, 0 when none
    body: Optional[Callable[[], Awaitable[bytes]]] = None


class Tab:
    """The shape every tab has; see the module's words."""

    @property
    def url(self) -> str:
        raise NotImplementedError

    async def goto(self, url: str, *, referer: str = "", timeout_s: float = OPEN_S) -> Answer:
        raise NotImplementedError

    async def evaluate(self, script: str, arg: Any = None) -> Any:
        raise NotImplementedError

    async def cdp(self, method: str, params: Optional[dict] = None) -> dict:
        raise NotImplementedError

    async def events(self, name: str, handler: Callable[[dict], None]) -> None:
        raise NotImplementedError

    async def scroll(self, screens: float = 1.0) -> None:
        raise NotImplementedError

    async def close(self) -> None:
        raise NotImplementedError


class PlaywrightTab(Tab):
    """A tab over one Playwright page: the visitor's headless, signed-out browser (roam.Visitor),
    whose own guards check every request the page makes."""

    def __init__(self, page: Any):
        self.page = page
        self._session: Any = None

    @property
    def url(self) -> str:
        return self.page.url

    async def goto(self, url: str, *, referer: str = "", timeout_s: float = OPEN_S) -> Answer:
        try:
            response = await self.page.goto(url, referer=referer or None, wait_until="commit",
                                            timeout=int(timeout_s * 1000))
        except Exception as exc:
            raise TabError(" ".join(str(exc).split())[:300]) from None
        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=int(PARSED_S * 1000))
        except Exception:
            # A slow document is read as far as it got.
            pass
        if response is None:
            return Answer(self.page.url)
        headers = response.headers
        try:
            length = int(headers.get("content-length") or 0)
        except ValueError:
            length = 0
        return Answer(self.page.url, response.status, headers.get("content-type", "").lower(), length, response.body)

    async def evaluate(self, script: str, arg: Any = None) -> Any:
        return await self.page.evaluate(script, arg)

    async def _cdp_session(self) -> Any:
        if self._session is None:
            self._session = await self.page.context.new_cdp_session(self.page)
        return self._session

    async def cdp(self, method: str, params: Optional[dict] = None) -> dict:
        return await (await self._cdp_session()).send(method, params or {})

    async def events(self, name: str, handler: Callable[[dict], None]) -> None:
        if name == "navigation":
            self.page.on("framenavigated",
                         lambda frame: handler({"url": frame.url}) if frame == self.page.main_frame else None)
        elif name == "load":
            self.page.on("load", lambda page: handler({"url": page.url}))
        else:
            (await self._cdp_session()).on(name, handler)

    async def scroll(self, screens: float = 1.0) -> None:
        width, height = await self.page.evaluate("() => [innerWidth, innerHeight]")
        # A wheel over the middle of the page: virtual lists listen for wheels, not for scrollTo.
        await self.page.mouse.move(width / 2, height / 2)
        await self.page.mouse.wheel(0, height * screens)

    async def close(self) -> None:
        await self.page.close()


class _BlockingTab(Tab):
    """A tab whose browser answers on another thread: each call waits there (asyncio.to_thread), never on
    the browser's own thread. `_call(method, params)` is the blocking DevTools call."""

    def _call(self, method: str, params: dict) -> dict:
        raise NotImplementedError

    async def cdp(self, method: str, params: Optional[dict] = None) -> dict:
        return await asyncio.to_thread(self._call, method, params or {})

    async def evaluate(self, script: str, arg: Any = None) -> Any:
        answer = await self.cdp("Runtime.evaluate", {"expression": f"({script})({json.dumps(arg)})",
                                                     "returnByValue": True, "awaitPromise": False})
        if answer.get("exceptionDetails"):
            detail = answer["exceptionDetails"]
            raise RuntimeError((detail.get("exception") or {}).get("description") or detail.get("text") or "")
        return (answer.get("result") or {}).get("value")

    async def scroll(self, screens: float = 1.0) -> None:
        view = (await self.cdp("Page.getLayoutMetrics", {})).get("cssVisualViewport") or {}
        wide, high = float(view.get("clientWidth") or 1280), float(view.get("clientHeight") or 800)
        await self.cdp("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": wide / 2, "y": high / 2,
                                                    "deltaX": 0, "deltaY": high * screens})


class PaneTab(_BlockingTab):
    """The pane the person browses in (browser.Pane): their own WebView2 profile, signed in where they
    signed in. Calls go through WebView2's in-process DevTools protocol (no port), on the window's thread,
    and a suspended page is resumed first. Read in place (read.read with here=True) or operated (pageops);
    it never moves the person's page except when they asked for something to be done in it."""

    def __init__(self, pane: Any):
        self.pane = pane

    @property
    def url(self) -> str:
        return self.pane.address()

    def _call(self, method: str, params: dict) -> dict:
        return self.pane.cdp(method, params)

    async def goto(self, url: str, *, referer: str = "", timeout_s: float = OPEN_S) -> Answer:
        answer = await self.cdp("Page.navigate", {"url": url, **({"referrer": referer} if referer else {})})
        if answer.get("errorText"):
            raise TabError(str(answer["errorText"]))
        began = time.monotonic()
        while time.monotonic() - began < timeout_s:
            await asyncio.sleep(0.3)
            with contextlib.suppress(RuntimeError):
                if await self.evaluate("() => document.readyState") in ("interactive", "complete"):
                    break
        return Answer(self.url)

    async def events(self, name: str, handler: Callable[[dict], None]) -> None:
        if name in ("navigation", "load"):
            event = "Page.frameNavigated" if name == "navigation" else "Page.loadEventFired"
            await self.cdp("Page.enable", {})
            await asyncio.to_thread(self.pane.listen, event, lambda params: handler(
                {"url": (params.get("frame") or {}).get("url", self.url)}) if name == "load" or not (
                params.get("frame") or {}).get("parentId") else None)
        else:
            await asyncio.to_thread(self.pane.listen, name, handler)

    async def close(self) -> None:
        # The person's pane stays: it closes when they close it.
        return None


class HiddenTab(_BlockingTab):
    """A hidden WebView2 on the pane's profile (browser.Reader), for reading with the person's session out of
    sight. Read only by construction: it goes to addresses of the one site it was opened for, its page may
    send only GET requests to that site, and of DevTools it has only what reading needs (no clicks, no keys;
    a wheel to scroll). It never reads cookies or storage."""

    READS = frozenset({"Runtime.evaluate", "Page.getLayoutMetrics", "Page.getFrameTree", "Accessibility.getFullAXTree",
                       "DOM.getDocument", "DOM.querySelectorAll", "DOM.describeNode", "Page.enable"})

    def __init__(self, view: Any):
        self.view = view

    @property
    def url(self) -> str:
        return self.view.address()

    def _call(self, method: str, params: dict) -> dict:
        if method not in self.READS and not (method == "Input.dispatchMouseEvent"
                                             and params.get("type") == "mouseWheel"):
            raise TabError(f"{method} is not for reading")
        return self.view.cdp(method, params)

    async def goto(self, url: str, *, referer: str = "", timeout_s: float = OPEN_S) -> Answer:
        final = await asyncio.to_thread(self.view.goto, url, timeout_s)
        return Answer(final)

    async def events(self, name: str, handler: Callable[[dict], None]) -> None:
        raise TabError("a hidden tab has no events")

    async def close(self) -> None:
        await asyncio.to_thread(self.view.close)
