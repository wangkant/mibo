"""Settings › Recommendations (setup/recs.js) against the app: topics and platforms as chips that keep what is
pressed, a platform read only once signed in saying so, and what the ranking remembers in one folded list, each
pill taking its own preference out."""
from __future__ import annotations

import pytest
from harness.page import measured

pytestmark = pytest.mark.browser

CHIPS = ".setup-section-recs .setup-chips"


def open_recs(app, browser):
    app.post("/api/look/toured")
    measured(app)
    page = browser.open(app, lang="en")
    page.page.locator("#side-settings").click()
    page.page.locator(".setup-nav-item[data-part='recs']").click()
    page.page.locator(f"{CHIPS} .setup-chip").first.wait_for()
    return page


def test_a_topic_chip_and_a_platform_chip_toggle_and_are_kept(app, browser):
    page = open_recs(app, browser)
    p = page.page
    topics, platforms = p.locator(CHIPS).nth(0), p.locator(CHIPS).nth(1)
    name = app.get("/api/feed/interests?lang=en").json()["suggested"][0]["name"]

    topic = topics.locator(".setup-chip", has_text=name)
    topic.click()
    topics.locator(f".setup-chip[aria-pressed='true']:has-text('{name}')").wait_for()
    assert app.get("/api/feed/interests?lang=en").json()["topics"] == [name]
    typed = topics.locator(".setup-word-input")
    typed.fill("tide pools")
    typed.press("Enter")
    topics.locator(".setup-chip[aria-pressed='true']:has-text('tide pools')").wait_for()
    topic.click()
    topics.locator(f".setup-chip[aria-pressed='false']:has-text('{name}')").wait_for()
    assert app.get("/api/feed/interests?lang=en").json()["topics"] == ["tide pools"]

    # The platforms past the first few come behind "More"; one read only once signed in brings its line.
    assert platforms.locator(".setup-chip", has_text="YouTube").count() == 0
    platforms.locator(".setup-chip", has_text="More").click()
    platforms.locator(".setup-chip", has_text="YouTube").click()
    platforms.locator(".setup-chip[aria-pressed='true']:has-text('YouTube')").wait_for()
    assert p.locator(".setup-recs-note").is_hidden()
    platforms.locator(".setup-chip", has_text="Reddit").click()
    p.locator(".setup-recs-note").wait_for()
    assert app.get("/api/feed/interests?lang=en").json()["platforms"] == ["youtube.com", "reddit.com"]
    assert app.get("/api/feed/interests?lang=en").json()["topics"] == ["tide pools"]

    p.locator(".setup-recs-note .setup-button-link").click()
    p.locator(".setup-nav-item[data-part='connect'][aria-current='page']").wait_for()
    p.locator(".setup-nav-item[data-part='recs']").click()
    platforms.locator(".setup-chip[aria-pressed='true']:has-text('YouTube')").wait_for()
    platforms.locator(".setup-chip", has_text="YouTube").click()
    platforms.locator(".setup-chip[aria-pressed='false']:has-text('YouTube')").wait_for()
    assert app.get("/api/feed/interests?lang=en").json()["platforms"] == ["reddit.com"]
    assert page.errors == [] and page.refused == []


def test_the_fold_lists_what_was_remembered_and_a_pill_takes_its_preference_out(app, browser):
    app.post("/api/profile/taste", {"likes": ["tide pools"]})
    app.post("/api/profile/taste", {"rules": [{"kind": "topic", "topic": "celebrity news"}]})
    page = open_recs(app, browser)
    p = page.page
    fold = p.locator(".setup-section-recs .setup-fold")
    assert fold.get_attribute("open") is None
    assert "(2)" in fold.locator("summary").inner_text()
    fold.locator("summary").click()
    pills = fold.locator(".setup-word")
    assert [pills.nth(i).inner_text() for i in range(2)] == ["Likes: tide pools", "Not interested: celebrity news"]

    pills.nth(1).locator(".setup-word-off").click()
    fold.locator("summary:has-text('(1)')").wait_for()
    taste = app.get("/api/profile/taste?lang=en").json()
    assert [x["topic"] for x in taste["likes"]] == ["tide pools"] and taste["rules"] == []
    assert fold.get_attribute("open") is not None
    assert page.errors == [] and page.refused == []
