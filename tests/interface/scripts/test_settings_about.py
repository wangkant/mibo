"""Settings › About (setup/about.js) and the chat's line after an update: each state of the update has its own
sentence in the page's language, the one button only where this copy updates itself, the command where it does
not, and the bar while the file comes in."""
from __future__ import annotations

import json

import pytest
from harness.page import measured

from mibo import i18n, updates

pytestmark = pytest.mark.browser

NEW = "99.0.0"
MB = 1048576
# (way of running, the update under way, what the last check found, what the start after an update found).
STATES = {
    "latest": ("installer", None, updates.__version__, None),
    "found": ("installer", None, NEW, None),
    "found-mac": ("macos", None, NEW, None),
    "found-zip": ("zip", None, NEW, None),
    "found-pip": ("pip", None, NEW, None),
    "found-checkout": ("checkout", None, NEW, None),
    "downloading": ("installer", {"state": "downloading", "done": 31 * MB, "total": 74 * MB}, NEW, None),
    "verifying": ("installer", {"state": "verifying", "done": 74 * MB, "total": 74 * MB}, NEW, None),
    "installing": ("installer", {"state": "installing", "done": 74 * MB, "total": 74 * MB}, NEW, None),
    "opened": ("macos", {"state": "opened", "done": 74 * MB, "total": 74 * MB}, NEW, None),
    "blocked": ("installer", {"state": "failed", "error": "update_blocked"}, NEW, None),
    "mismatch": ("installer", {"state": "failed", "error": "update_mismatch"}, NEW, None),
    "updated": ("installer", None, updates.__version__, True),
    "not-updated": ("installer", None, "99.0.1", False),
}


def stage(app, monkeypatch, name: str) -> None:
    """The app as it stands in that state, its check's record and its update record written as they would be."""
    how, job, latest, ok = STATES[name]
    monkeypatch.setattr(updates, "way", lambda: how)
    monkeypatch.setattr(updates, "job", lambda home: job and {"version": NEW, "done": 0, "total": 0, "error": "",
                                                             **job})
    cache = app.home / "runtime" / "desktop" / "update.json"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"checked": 1, "latest": latest, "failed": False}))
    record = app.home / "runtime" / "updates" / "state.json"
    record.parent.mkdir(parents=True, exist_ok=True)
    outcome = None if ok is None else {"version": updates.__version__ if ok else "99.0.1", "from": "0.1.0", "ok": ok}
    record.write_text(json.dumps({"outcome": outcome} if outcome else {}))


def open_about(app, browser, lang: str, width: int = 1200):
    measured(app)
    app.post("/api/look/toured")
    page = browser.open(app, lang=lang, width=width, settle=False)
    page.page.locator("#side-settings").click()
    page.page.locator('.setup-nav-item[data-part="about"]').click()
    page.page.locator('.setup-section-about [data-item="updates"]:not([hidden])').wait_for()
    page.settle()
    return page


def said(page) -> dict:
    return page.page.evaluate("""() => {
      const row = document.querySelector('.setup-section-about [data-item="updates"]');
      const shown = (node) => node && !node.hidden && node.offsetParent !== null;
      const go = row.querySelector(".setup-button-primary");
      return {
        text: row.innerText,
        button: shown(go) ? go.innerText.trim() : "",
        command: shown(row.querySelector(".setup-command")) ? row.querySelector(".setup-command").innerText : "",
        meter: shown(row.querySelector(".setup-meter")),
        link: shown(row.querySelector("a.setup-link")) ? row.querySelector("a.setup-link").href : "",
      };
    }""")


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_each_state_of_the_update_has_its_sentence_and_only_its_controls(app, browser, monkeypatch, lang):
    words = i18n.words("setup_about", lang)
    expect = {
        "latest": [words["latest"]],
        "found": [words["newer"].replace("{v}", NEW), words["installerText"]],
        "found-mac": [words["macText"]],
        "found-zip": [words["zipText"]],
        "found-pip": [words["pipText"]],
        "found-checkout": [words["checkoutText"]],
        "downloading": [words["downloading"].replace("{v}", NEW).replace("{done}", "31.0").replace("{total}", "74.0")],
        "verifying": [words["verifying"]],
        "installing": [words["installing"].replace("{v}", NEW)],
        "opened": [words["opened"].replace("{v}", NEW)],
        "blocked": [words["errors"]["update_blocked"]],
        "mismatch": [words["errors"]["update_mismatch"]],
        "updated": [words["updated"].replace("{v}", updates.__version__)],
        "not-updated": [words["updateFailed"].replace("{v}", "99.0.1").replace("{current}", updates.__version__)],
    }
    page = open_about(app, browser, lang)
    seen = {}
    for name in STATES:
        stage(app, monkeypatch, name)
        page.page.locator('.setup-nav-item[data-part="device"]').click()
        page.page.locator('.setup-nav-item[data-part="about"]').click()
        page.settle()
        seen[name] = said(page)
        for sentence in expect[name]:
            assert sentence in seen[name]["text"], (name, sentence, seen[name]["text"])
    update = words["update"].replace("{v}", NEW)
    assert seen["found"]["button"] == update and seen["blocked"]["button"] == update
    assert seen["found-mac"]["button"] == words["download"].replace("{v}", NEW)
    # After an update that did not finish, the same version is offered again.
    assert [name for name, one in seen.items() if one["button"]] == ["found", "found-mac", "blocked", "mismatch",
                                                                      "not-updated"]
    assert seen["found-pip"]["command"].endswith("-m pip install -U mibo")
    assert seen["found-checkout"]["command"].startswith("git -C ")
    assert [name for name, one in seen.items() if one["command"]] == ["found-pip", "found-checkout"]
    assert [name for name, one in seen.items() if one["meter"]] == ["downloading"]
    assert seen["blocked"]["link"].endswith(f"/v{NEW}") and seen["not-updated"]["link"].endswith("/v99.0.1")
    assert not seen["installing"]["link"] and not seen["latest"]["link"]
    assert page.missing_words(lang) == [] and page.errors == [] and page.refused == []


def test_the_start_after_an_update_says_it_in_the_chat_until_closed(app, browser, monkeypatch):
    stage(app, monkeypatch, "updated")
    measured(app)
    app.post("/api/look/toured")
    page = browser.open(app)
    banner = page.page.locator(".chat-banner:not([hidden])")
    banner.wait_for()
    assert banner.inner_text().strip() == i18n.words("chat", "en")["updated"].replace("{v}", updates.__version__)
    banner.locator(".chat-banner-close").click()
    page.settle()
    assert page.page.locator(".chat-banner").first.is_hidden()
    assert app.get("/api/state").json()["updated"] is None
    stage(app, monkeypatch, "not-updated")
    page.reload()
    line = page.page.locator(".chat-banner:not([hidden])")
    line.wait_for()
    assert "99.0.1" in line.inner_text() and line.locator("a").get_attribute("href").endswith("/v99.0.1")
    assert page.errors == [] and page.missing_words("en") == []
