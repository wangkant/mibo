"""The installed browser a page read starts beside its plain fetch, when the app closes before it is up: its
driver's start is let finish and the driver is stopped, so nothing of it is left for the closing loop to cut off.
A start cut off while the driver's process is being made never ends on Windows (Python 3.12 and later), and the
app would not exit. A stand-in is the driver; no browser is started."""
from __future__ import annotations

import asyncio
import sys
import threading
from pathlib import Path

import pytest
from harness.model import call, say

from mibo import installed_browser, roam

PAGES = Path(__file__).resolve().parents[2] / "data" / "pages"


class Driver:
    """Playwright's driver as the app starts and stops it; its start ends only once `release` is set."""

    def __init__(self) -> None:
        self.entered, self.release = threading.Event(), threading.Event()
        self.started = self.stopped = False

    def __call__(self) -> Driver:
        return self

    async def start(self) -> Driver:
        self.entered.set()
        while not self.release.is_set():
            await asyncio.sleep(0.01)
        self.started = True
        return self

    async def stop(self) -> None:
        self.stopped = True


def test_closing_the_app_while_a_reads_browser_starts_waits_for_its_driver_and_stops_it(app, turn, web, monkeypatch):
    api = pytest.importorskip("playwright.async_api")
    driver = Driver()
    monkeypatch.setattr(api, "async_playwright", driver)
    monkeypatch.setattr(roam.Roam, "available", lambda self: "")
    monkeypatch.setattr(installed_browser, "find_browser", lambda: Path(sys.executable))
    monkeypatch.setattr(installed_browser, "end_profile", lambda profile, process=None: None)
    web.site.put("/lighthouse", (PAGES / "short-story.html").read_bytes(), "text/html; charset=utf-8")
    url = web.name("shore.example", "93.184.216.34") + "/lighthouse"
    done = turn(f"What does {url} say?", call("read_page", url=url), say("Read it."))
    # The read itself came from the plain fetch; the browser is still starting behind it.
    assert "北角灯塔昨晚七点重新点亮" in done.result_of(done.calls()[0]["id"])
    assert driver.entered.wait(10) and not driver.started
    threading.Timer(0.5, driver.release.set).start()
    app.close()
    assert driver.started and driver.stopped
