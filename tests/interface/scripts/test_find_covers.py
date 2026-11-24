"""A find's cover on its card in 推荐记录 and in the chat (findcard.js): one that does not arrive the first time is
asked for once more, and a find with no picture, or one that will not arrive or will not decode, is drawn as the
text card, with no picture box in it."""
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
    """Three finds on the shelf, seen at noon: one with a good cover, one whose cover file is not a picture, one
    with no cover, and a video with none."""
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
    for n, kind in ((2, "article"), (3, "video")):
        item = library.add(Item(url=f"https://shore.example/{kind}/{n}", site="shore.example", kind=kind,
                                title="没有封面的" + kind, description="一段说明。", seen_at=int(NOON - 60 * n),
                                embed="https://www.youtube-nocookie.com/embed/00000000001" if kind == "video" else ""))
        feed.remember(runtime, item, "seen", NOON - 60 * n, surface="card")
    return app


def open_finds(app, browser):
    page = browser.open(app, lang="zh")
    page.page.locator("#side-finds").click()
    page.page.locator("article.find").nth(3).wait_for()
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


def test_a_cover_that_will_not_decode_leaves_the_text_card(shelf, browser):
    page = open_finds(shelf, browser)
    bad = page.page.locator("article.find-plain", has_text="坏的封面")
    bad.wait_for()
    assert bad.locator("img, .cover").count() == 0


def test_a_find_with_no_picture_is_the_text_card_and_one_with_a_picture_is_unchanged(shelf, browser):
    page = open_finds(shelf, browser)
    plain = page.page.locator("article.find", has_text="没有封面的article")
    assert "find-plain" in plain.get_attribute("class")
    assert plain.locator("img, .cover").count() == 0
    good = page.page.locator("article.find", has_text="好的封面")
    page.page.wait_for_function("() => document.querySelector('article.find .cover img')?.naturalWidth > 0")
    assert "find-plain" not in good.get_attribute("class")
    assert good.locator(".cover img").count() == 1


def test_a_video_with_no_cover_has_a_play_button_in_the_text_card(shelf, browser):
    page = open_finds(shelf, browser)
    video = page.page.locator("article.find-plain", has_text="没有封面的video")
    video.locator(".find-play").click()
    video.locator(".player iframe").wait_for()
    assert video.locator(".cover").count() == 0


def test_the_actions_work_on_the_text_card(shelf, browser):
    page = open_finds(shelf, browser)
    plain = page.page.locator("article.find-plain", has_text="没有封面的article")
    plain.locator(".like").click()
    plain.locator(".like[aria-pressed='true']").wait_for()
    assert plain.locator("a.icon-btn").get_attribute("href") == "https://shore.example/article/2"
    plain.locator(".find-more-wrap > button").click()
    assert plain.locator(".find-menu").is_visible()
    page.settle()
    (kept,) = shelf.get("/api/feed?limit=5&kept=true").json()["items"]
    assert kept["title"] == "没有封面的article"


def test_the_chat_draws_a_find_with_no_picture_as_the_text_card(shelf, browser):
    items = shelf.get("/api/feed?limit=9").json()["items"]
    ident = next(item["id"] for item in items if item["title"] == "没有封面的article")
    shelf.post("/api/chat/bring", {"id": ident})
    page = browser.open(shelf, lang="zh")
    card = page.page.locator("article.find-plain", has_text="没有封面的article")
    card.wait_for()
    assert card.locator("img, .cover").count() == 0
