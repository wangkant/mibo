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
    # A platform read without signing in, and one read only after it, which brings the notice on reading the
    # person's own feed there, under the row; a no leaves the line, and the next such pick asks again.
    p.locator(".onboard-chip[data-key='bilibili.com']").click()
    assert p.locator(".onboard-platforms-note").count() == 0 and p.locator(".onboard-reading").count() == 0
    p.locator(".onboard-chip[data-key='douyin.com']").click()
    notice = p.locator(".onboard-platforms .onboard-reading")
    notice.locator(".onboard-reading-title", has_text="推荐流").wait_for()
    assert p.locator("dialog[open]").count() == 0
    notice.locator(".onboard-reading-no").click()
    p.locator(".onboard-platforms-note").wait_for()
    assert notice.count() == 0
    p.locator(".onboard-chip[data-key='weibo.com']").click()
    notice.locator(".onboard-reading-yes").click()
    p.locator(".onboard-platforms-note").wait_for()
    p.locator(".onboard-chip[data-key='kuaishou.com']").click()
    assert notice.count() == 0
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
    assert interests["platforms"] == ["bilibili.com", "douyin.com", "weibo.com", "kuaishou.com"]
    assert interests["agreed"] is True
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


def test_a_no_on_the_notice_keeps_the_pick_a_preference_and_skip_drops_a_yes(app, browser):
    measured(app)
    page = browser.open(app)
    p = page.page
    now = p.locator(".onboard-dot-now .onboard-dot-name")
    following = p.locator(".onboard-next")
    p.locator(".onboard-lang[lang='zh']").click()
    now.filter(has_text="语言").wait_for()
    for _ in range(3):
        following.click()
    now.filter(has_text="喜好").wait_for()
    p.locator(".onboard-chip[data-key='douyin.com']").click()
    p.locator(".onboard-reading-no").click()
    following.click()
    now.filter(has_text="关于你").wait_for()
    interests = app.get("/api/feed/interests?lang=zh").json()
    assert interests["platforms"] == ["douyin.com"] and interests["agreed"] is False

    # Back at the platforms, a yes given and then the step skipped is not kept.
    p.locator(".onboard-foot .onboard-back").click()
    now.filter(has_text="喜好").wait_for()
    p.locator(".onboard-chip[data-key='weibo.com']").click()
    p.locator(".onboard-reading-yes").click()
    p.locator(".onboard-skip").click()
    now.filter(has_text="关于你").wait_for()
    assert app.get("/api/feed/interests?lang=zh").json()["agreed"] is False
    assert page.errors == [] and page.refused == []


def test_a_sample_find_with_no_picture_is_the_text_card(app, browser):
    measured(app)
    page = browser.open(app)
    p = page.page
    finds = [{"id": "a" * 16, "kind": "article", "title": "没有封面的文章", "site": "shore.example", "words": "", "text": "一段说明。",
              "picture": ""},
             {"id": "b" * 16, "kind": "article", "title": "封面取不到的文章", "site": "shore.example", "words": "", "text": "",
              "picture": "/api/library/picture/" + "b" * 16}]
    p.route("**/api/feed/first*", lambda route: route.fulfill(json={"items": finds}))
    now = p.locator(".onboard-dot-now .onboard-dot-name")
    p.locator(".onboard-lang[lang='zh']").click()
    now.filter(has_text="语言").wait_for()
    for _ in range(3):
        p.locator(".onboard-next").click()
    now.filter(has_text="喜好").wait_for()
    p.locator(".onboard-next").click()
    card = p.locator(".onboard-find")
    card.filter(has_text="没有封面的文章").wait_for()
    assert "onboard-find-plain" in card.get_attribute("class") and card.locator(".onboard-find-media").count() == 0
    p.locator(".onboard-find-no").click()
    card.filter(has_text="封面取不到的文章").wait_for()
    p.locator(".onboard-find-plain").wait_for()
    assert card.locator(".onboard-find-media").count() == 0
    assert page.errors == [] and page.refused == []
