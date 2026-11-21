"""The page tab over an Electron view (mibo.host.etab.ElectronTab): the contract between the operating code and
Electron's in-process debugger. A stand-in link plays Electron's side; every command and event goes through it."""
from __future__ import annotations

import threading

import pytest

from mibo.host.etab import ElectronTab
from mibo.web.tabs import TabError


class Link:
    """Electron's side as the tab sees it: commands recorded with their view and session, events fired by hand."""

    def __init__(self, answers: dict | None = None):
        self.sent: list[tuple[str, str, dict, str]] = []
        self.handlers: dict[tuple[str, str], list] = {}
        self.answers = answers or {}
        # Frame sessions that closed: a command to one fails as Electron's does.
        self.gone: set[str] = set()
        self.lock = threading.Lock()

    def call(self, op: str, **fields) -> dict:
        return {"url": f"http://127.0.0.1/{fields['tab']}"} if op == "tab.url" else {}

    def cdp(self, tab: str, method: str, params: dict, session: str = "") -> dict:
        with self.lock:
            self.sent.append((tab, method, params, session))
        if session in self.gone:
            raise RuntimeError("No session with given id")
        answer = self.answers.get(method, {})
        if isinstance(answer, Exception):
            raise answer
        return answer

    def listen(self, tab: str, event: str, handler) -> None:
        self.handlers.setdefault((tab, event), []).append(handler)

    def fire(self, tab: str, event: str, params: dict, session: str = "") -> None:
        for handler in self.handlers.get((tab, event), []):
            handler(params, session)

    def to(self, method: str) -> list[tuple[str, dict, str]]:
        return [(tab, params, session) for tab, m, params, session in self.sent if m == method]


async def test_every_command_and_script_goes_to_its_own_view() -> None:
    link = Link({"Runtime.evaluate": {"result": {"value": 42}}})
    first, second = ElectronTab(link, "tab-1"), ElectronTab(link, "tab-2")
    assert await second.evaluate("(x) => x * 2", 21) == 42
    await first.cdp("Page.getLayoutMetrics", {})
    assert [(tab, method) for tab, method, _, _ in link.sent] == [("tab-2", "Runtime.evaluate"),
                                                                  ("tab-1", "Page.getLayoutMetrics")]
    assert first.url == "http://127.0.0.1/tab-1"


async def test_a_script_that_throws_raises_the_pages_own_error() -> None:
    link = Link({"Runtime.evaluate": {"exceptionDetails": {"exception": {"description": "ReferenceError: nope"}}}})
    with pytest.raises(RuntimeError, match="ReferenceError: nope"):
        await ElectronTab(link, "tab-1").evaluate("() => nope")


async def test_a_navigation_the_browser_refuses_raises_its_reason() -> None:
    link = Link({"Page.navigate": {"errorText": "net::ERR_NAME_NOT_RESOLVED"}})
    with pytest.raises(TabError, match="ERR_NAME_NOT_RESOLVED"):
        await ElectronTab(link, "tab-1").goto("http://nowhere.invalid/")


async def test_a_request_paused_in_a_frame_is_answered_in_that_frames_session() -> None:
    link = Link()
    tab = ElectronTab(link, "tab-1")
    heard: list[dict] = []
    await tab.events("Fetch.requestPaused", heard.append)
    link.fire("tab-1", "Fetch.requestPaused", {"requestId": "in-frame"}, session="frame-A")
    link.fire("tab-1", "Fetch.requestPaused", {"requestId": "in-page"})
    await tab.cdp("Fetch.continueRequest", {"requestId": "in-frame"})
    await tab.cdp("Fetch.continueRequest", {"requestId": "in-page"})
    assert [r["requestId"] for r in heard] == ["in-frame", "in-page"]
    assert link.to("Fetch.continueRequest") == [("tab-1", {"requestId": "in-frame"}, "frame-A"),
                                                ("tab-1", {"requestId": "in-page"}, "")]


async def test_fetch_turned_on_in_the_page_reaches_every_frame_from_another_site() -> None:
    link = Link()
    tab = ElectronTab(link, "tab-1")
    assert await tab.frames() == []
    link.fire("tab-1", "Target.attachedToTarget", {"sessionId": "frame-A", "targetInfo": {"type": "iframe"}})
    link.fire("tab-1", "Target.attachedToTarget", {"sessionId": "worker", "targetInfo": {"type": "worker"}})
    assert await tab.frames() == ["frame-A"]
    watched = {"patterns": [{"urlPattern": "*", "requestStage": "Request"}]}
    await tab.cdp("Fetch.enable", watched)
    assert ("tab-1", watched, "frame-A") in link.to("Fetch.enable")
    # Frames from yet another site inside the frame are attached through its own session.
    assert ("tab-1", "frame-A") in [(t, s) for t, p, s in link.to("Target.setAutoAttach") if p.get("flatten")]
    link.fire("tab-1", "Target.detachedFromTarget", {"sessionId": "frame-A"})
    assert await tab.frames() == []


async def test_a_frame_that_went_while_it_was_made_ready_is_dropped() -> None:
    link = Link()
    link.gone = {"frame-gone"}
    tab = ElectronTab(link, "tab-1")
    await tab.frames()
    link.fire("tab-1", "Target.attachedToTarget", {"sessionId": "frame-gone", "targetInfo": {"type": "iframe"}})
    assert await tab.frames() == []


async def test_page_events_come_from_the_page_and_navigation_only_from_its_main_frame() -> None:
    link = Link()
    tab = ElectronTab(link, "tab-1")
    dialogs: list[dict] = []
    moved: list[dict] = []
    await tab.events("Page.javascriptDialogOpening", dialogs.append)
    await tab.events("navigation", moved.append)
    link.fire("tab-1", "Page.javascriptDialogOpening", {"message": "from a frame"}, session="frame-A")
    link.fire("tab-1", "Page.javascriptDialogOpening", {"message": "from the page"})
    link.fire("tab-1", "Page.frameNavigated", {"frame": {"url": "http://a/frame", "parentId": "main"}})
    link.fire("tab-1", "Page.frameNavigated", {"frame": {"url": "http://a/next"}})
    assert [d["message"] for d in dialogs] == ["from the page"]
    assert moved == [{"url": "http://a/next"}]
