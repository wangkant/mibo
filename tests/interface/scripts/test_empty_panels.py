"""The look of "nothing here yet": Settings › Connect with nothing signed in shows its two empty lists as filled
panels, and no stylesheet draws a box with a dashed or dotted outline."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from harness.page import measured

import mibo

pytestmark = pytest.mark.browser

STATIC = Path(mibo.__file__).parent / "static"
# A dashed or dotted border, or a dashed stroke, in a stylesheet. No place keeps one on purpose.
OUTLINE = re.compile(r"border[\w-]*\s*:[^;{}]*\b(dashed|dotted)\b|stroke-dasharray")
BOXES = """
(() => [...document.querySelectorAll(".places-empty")].map((box) => {
  const style = getComputedStyle(box);
  return { text: box.textContent.trim(), style: style.borderStyle, fill: style.backgroundColor, icon: Boolean(box.querySelector("svg")) };
}))()
"""


def test_the_two_empty_lists_in_connect_are_filled_panels_with_no_dashed_border(app, browser):
    app.post("/api/look/toured")
    measured(app)
    page = browser.open(app, lang="zh")
    p = page.page
    p.locator("#side-settings").click()
    p.locator(".setup-nav-item[data-part=connect]").click()
    p.locator(".sites-empty:visible").wait_for()
    p.locator(".sites-kept-none:visible").wait_for()
    boxes = p.evaluate(BOXES)
    assert [box["text"] for box in boxes if box["text"]] and len(boxes) == 2
    for box in boxes:
        assert box["style"] == "solid" and box["fill"] != "rgba(0, 0, 0, 0)" and box["icon"], box
    assert page.errors == []


def test_no_stylesheet_or_script_draws_a_dashed_or_dotted_outline():
    drawn = [f"{path.relative_to(STATIC)}:{n}" for path in sorted(STATIC.rglob("*")) if path.suffix in {".css", ".js", ".html"}
             and "markdown-it" not in path.name
             for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1) if OUTLINE.search(line)]
    assert drawn == []
