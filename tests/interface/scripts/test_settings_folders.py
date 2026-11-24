"""Settings › Files and commands (setup/shell.js): each allowed folder and each always-allowed program is a row that
holds its words however long they are, and a folder's select sets view only or sorting too."""
from __future__ import annotations

import json

import pytest
from harness.page import measured
from playwright.sync_api import expect

pytestmark = pytest.mark.browser

LONG = "A folder named for the quarterly reports and the drafts that go with them every year"


@pytest.fixture
def folders(app, tmp_path):
    """A folder in a very long path, one set to view only, and a program always allowed in the first."""
    long = tmp_path.joinpath(*(f"{LONG} {n}" for n in range(3)))
    short = tmp_path / "Photos"
    long.mkdir(parents=True)
    short.mkdir()
    app.post("/api/shell", {"add": str(long)})
    app.post("/api/shell", {"add": str(short), "read_only": True})
    grants = app.app.state.shell.grants
    grants.allow(str(long / "tool.exe"), "tool.exe", str(long))
    return long, short


def open_shell(app, browser, width):
    measured(app)
    app.post("/api/look/toured")
    page = browser.open(app, width=width, settle=False)
    page.page.locator("#side-settings").click()
    page.page.locator('.setup-nav-item[data-part="shell"]').click()
    page.page.locator(".setup-shell-row").first.wait_for()
    page.settle()
    return page


@pytest.mark.parametrize("width", [480, 1200])
def test_a_long_path_stays_inside_its_row(app, browser, folders, width):
    page = open_shell(app, browser, width)
    rows = page.page.evaluate("""() => [...document.querySelectorAll(".setup-shell-row")].map((row) => {
      const box = row.getBoundingClientRect(), card = row.closest(".setup-card").getBoundingClientRect();
      return [...row.querySelectorAll(".setup-option-name, .setup-option-text, select, button")].map((node) => {
        const at = node.getBoundingClientRect();
        return at.left >= box.left - 0.5 && at.right <= box.right + 0.5 && at.right <= card.right + 0.5;
      });
    })""")
    assert len(rows) >= 3 and all(all(inside) for inside in rows)
    assert page.page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert page.page.locator(".setup-shell-row .setup-option-words").first.get_attribute("title") == str(folders[0])
    assert page.errors == []


def test_the_select_sets_view_only_or_sorting_too(app, browser, folders):
    long, short = folders
    page = open_shell(app, browser, 1200)
    sent = []
    page.page.on("request", lambda request: request.method == "POST" and request.url.endswith("/api/shell")
                 and sent.append(json.loads(request.post_data)))
    # The person's own folders are listed too: these two are found by their paths.
    selects = [page.page.locator(".setup-shell-row").filter(has=page.page.get_by_title(str(where), exact=True)).locator("select")
               for where in (long, short)]

    def values():
        return [select.input_value() for select in selects]

    assert values() == ["sort", "read"]
    with page.page.expect_response(lambda r: r.url.endswith("/api/shell") and r.request.method == "POST"):
        selects[0].select_option("read")
    with page.page.expect_response(lambda r: r.url.endswith("/api/shell") and r.request.method == "POST"):
        selects[1].select_option("sort")
    assert sent == [{"add": str(long), "read_only": True}, {"add": str(short)}]
    # The rows are drawn again once the answer is in.
    for select, value in zip(selects, ("read", "sort")):
        expect(select).to_have_value(value)
    assert page.errors == []
