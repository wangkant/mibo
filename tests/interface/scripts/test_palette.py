"""The palette as one system (app.css): a primary action and a switch that is on are drawn the same whichever
character is chosen, while the character's own colour still changes with it; and no stylesheet writes a colour
past the tokens."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from harness.page import measured

import mibo

pytestmark = pytest.mark.browser

STATIC = Path(mibo.__file__).parent / "static"
HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
# Pure white and black are not the palette's: a mask's opaque part, a mark on a picture or a video's letterbox.
PLAIN = {"#fff", "#ffffff", "#000", "#000000"}
# Each figure's primary button, switch that is on, and its own colour, as the page draws them.
DRAWN = """
(figure) => {
  document.documentElement.dataset.figure = figure;
  const made = [["button", "pa-btn pa-btn-primary"], ["button", "setup-button setup-button-primary"]].map(([tag, cls]) => {
    const node = document.createElement(tag);
    node.className = cls;
    document.body.append(node);
    return node;
  });
  const box = document.createElement("input");
  box.type = "checkbox";
  box.className = "pa-switch";
  box.checked = true;
  document.body.append(box);
  const seen = {
    primary: made.map((node) => getComputedStyle(node).backgroundColor),
    on: getComputedStyle(box).backgroundColor,
    own: getComputedStyle(document.documentElement).getPropertyValue("--pa-char").trim(),
  };
  for (const node of [...made, box]) node.remove();
  return seen;
}
"""


def test_a_primary_action_and_a_switch_are_drawn_the_same_for_every_character(app, browser):
    app.post("/api/look/toured")
    measured(app)
    page = browser.open(app)
    mibo_, claude = (page.page.evaluate(DRAWN, figure) for figure in ("mibo", "claude"))
    assert mibo_["primary"] == claude["primary"] and mibo_["on"] == claude["on"]
    assert len(set(mibo_["primary"])) == 1 and mibo_["primary"][0] != mibo_["on"]
    assert mibo_["own"] != claude["own"]
    assert page.errors == []


def test_no_stylesheet_writes_a_colour_outside_the_token_blocks():
    """A colour is named once, as a custom property (app.css's tokens, or a page's own block where it does not load
    app.css: the pet, its card); every other declaration takes it by name."""
    written = []
    for path in sorted(STATIC.rglob("*.css")):
        text = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)
        for declaration in re.split(r"[;{}]", text):
            declaration = declaration.strip()
            if declaration.startswith("--"):
                continue
            written += [f"{path.relative_to(STATIC)}: {declaration}" for found in HEX.findall(declaration)
                        if found.lower() not in PLAIN]
    assert written == []
