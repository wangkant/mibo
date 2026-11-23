"""The first run (onboard.js) walked as a person walks it, against the app: five steps in order, the screens
following the language picked at once, and each choice kept where the app reads it after."""
from __future__ import annotations

import pytest
from harness.page import measured

from mibo import settingsfile

pytestmark = pytest.mark.browser


def test_the_first_run_walks_five_steps_and_keeps_each_choice(app, browser):
    measured(app)
    page = browser.open(app)
    p = page.page
    now = p.locator(".onboard-dot-now .onboard-dot-name")
    following = p.locator(".onboard-next")

    p.locator(".onboard-lang[lang='zh']").click()
    now.filter(has_text="语言").wait_for()
    following.click()

    now.filter(has_text="角色").wait_for()
    p.locator(".pac-card").nth(1).click()
    p.locator(".pac-card:nth-child(2)[aria-pressed='true']").wait_for()
    following.click()

    now.filter(has_text="模型").wait_for()
    p.locator(".onboard-connected").wait_for()
    following.click()

    now.filter(has_text="喜好").wait_for()
    p.locator(".onboard-add .onboard-field").fill("潮汐")
    p.locator(".onboard-add .onboard-field").press("Enter")
    p.locator(".onboard-chip[data-name='潮汐'][aria-pressed='true']").wait_for()
    # A platform read without signing in, and one read only after it, which brings its line.
    p.locator(".onboard-chip[data-key='bilibili.com']").click()
    assert p.locator(".onboard-platforms-note").count() == 0
    p.locator(".onboard-chip[data-key='douyin.com']").click()
    p.locator(".onboard-platforms-note").wait_for()
    following.click()

    now.filter(has_text="关于你").wait_for()
    following.click()
    p.locator(".chat-input:visible").wait_for()

    assert p.locator("#onboard-view").is_hidden()
    assert app.get("/api/look").json()["toured"] is True
    settings = settingsfile.values(app.home)
    assert (settings["AGENT_LANG"], settings["UI_LANG"]) == ("zh", "zh")
    interests = app.get("/api/feed/interests?lang=zh").json()
    assert "潮汐" in interests["topics"]
    assert interests["platforms"] == ["bilibili.com", "douyin.com"]
    assert {"key": "douyin.com", "name": "抖音", "reach": "signin", "connected": False} in interests["platformsOffered"]
    assert app.get("/api/characters").json()["chosen"] != "mibo"
    assert page.errors == [] and page.refused == []


def test_a_platform_picked_in_the_tour_stays_through_a_language_change_and_is_dropped_by_skip(app, browser):
    measured(app)
    page = browser.open(app)
    p = page.page
    now = p.locator(".onboard-dot-now .onboard-dot-name")
    following = p.locator(".onboard-next")

    p.locator(".onboard-lang[lang='en']").click()
    now.filter(has_text="Language").wait_for()
    for _ in range(3):
        following.click()
    # YouTube is past the first few an English reader is offered: it comes with "More".
    assert p.locator(".onboard-chip[data-key='youtube.com']").count() == 0
    p.locator(".onboard-chip-quiet").click()
    youtube = p.locator(".onboard-chip[data-key='youtube.com']")
    youtube.click()
    assert youtube.get_attribute("aria-pressed") == "true"

    for _ in range(3):
        p.locator(".onboard-foot .onboard-back").click()
    p.locator(".onboard-lang[lang='zh']").click()
    now.filter(has_text="语言").wait_for()
    for _ in range(3):
        following.click()
    p.locator(".onboard-chip[data-key='youtube.com'][aria-pressed='true']").wait_for()
    p.locator(".onboard-chip[data-key='douyin.com'] span").filter(has_text="抖音").wait_for()

    p.locator(".onboard-skip").click()
    now.filter(has_text="关于你").wait_for()
    assert app.get("/api/feed/interests?lang=zh").json()["platforms"] == []
    assert page.errors == [] and page.refused == []
