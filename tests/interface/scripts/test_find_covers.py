"""A find's cover on its card in 推荐记录 (findcard.js): one that does not arrive the first time is asked for
once more, and one that will not arrive or will not decode leaves the quiet cover instead of a broken frame."""
from __future__ import annotations

import io
from datetime import datetime, timezone

import pytest
from harness.clock import Clock
from harness.page import measured
from PIL import Image

from mibo import situation
from mibo.library import Item, Library
from mibo.panels import feed

pytestmark = pytest.mark.browser

NOON = datetime(2026, 11, 20, 12, tzinfo=timezone.utc).timestamp()
ROUTE = "**/api/library/picture/*"


@pytest.fixture
def shelf(app, monkeypatch):
    """Two finds on the shelf, seen at noon: one with a good cover, one whose cover file is not a picture."""
    monkeypatch.setenv("PERSONA_TZ_OFFSET_HOURS", "0")
    Clock(monkeypatch, NOON)
    app.post("/api/look/toured")
    app.post("/api/feed/snooze", {"on": True})
    measured(app)
    runtime = app.home / "runtime"
    situation.set_value(runtime, "readable", ["zh"])
    library = Library(runtime)
    good = io.BytesIO()
    Image.new("RGB", (480, 270), "teal").save(good, "JPEG")
    for n, (title, data) in enumerate((("好的封面", good.getvalue()), ("坏的封面", b"not a picture"))):
        item = library.add(Item(url=f"https://shore.example/story/{n}", site="shore.example", kind="article",
                                title=title, description="一段说明。", seen_at=int(NOON - 60 * n)))
        library.change(item.id, picture=library.save_picture(item.id, data))
        feed.remember(runtime, item, "seen", NOON - 60 * n, surface="card")
    return app


def open_finds(app, browser):
    page = browser.open(app, lang="zh")
    page.page.locator("#side-finds").click()
    page.page.locator("article.find").nth(1).wait_for()
    return page


def test_a_cover_that_misses_once_is_asked_for_again_and_shown(shelf, browser):
    asked = []

    def flaky(route):
        asked.append(route.request.url)
        route.abort() if len(asked) == 1 else route.fallback()

    page = browser.open(shelf, lang="zh")
    page.page.route(ROUTE, flaky)
    page.page.locator("#side-finds").click()
    page.page.wait_for_function("""() => [...document.querySelectorAll('article.find')].some(
        (node) => node.textContent.includes('好的封面') && node.querySelector('img')?.naturalWidth > 0)""")
    assert len(asked) >= 2


def test_a_cover_that_will_not_decode_leaves_the_quiet_cover(shelf, browser):
    page = open_finds(shelf, browser)
    bad = page.page.locator("article.find", has_text="坏的封面")
    bad.locator(".cover.blank .cover-mark").wait_for()
    assert bad.locator("img").count() == 0
