"""Settings › Skills (setup/skills.js): the installed skills are tiles in a grid, each tile holds its own text and
its own switch, and a skill with no title in the page's language is shown by its name."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from harness.page import measured

from mibo.skills import panel

pytestmark = pytest.mark.browser

LONG = "a-very-long-skill-title-" * 6
# Each tile's boxes against the tile's own: the tile's columns, and what of its text sits outside it.
TILES = """
(() => {
  const tiles = [...document.querySelectorAll(".skm-pane:not([hidden]) .skm-grid > .skm-card")];
  const outside = tiles.flatMap((tile) => {
    const box = tile.getBoundingClientRect();
    return [...tile.querySelectorAll("*")].filter((node) => {
      const r = node.getBoundingClientRect();
      return r.width && (r.left < box.left - 1 || r.right > box.right + 1 || r.bottom > box.bottom + 1);
    }).map((node) => node.className);
  });
  return { count: tiles.length, columns: new Set(tiles.map((tile) => Math.round(tile.getBoundingClientRect().left))).size, outside };
})()
"""


def test_installed_skills_are_a_grid_of_tiles_that_keep_their_text_and_each_switch_turns_its_skill_off(app, browser, monkeypatch):
    # No model is asked for a Chinese title: the skill without one is shown as it is.
    async def no_titles(*args):
        return None

    monkeypatch.setattr(panel, "_title", no_titles)
    for name, about in (("packing-list", "Pack for a trip."), (LONG[:60], "A very long description. " * 40),
                        ("notes-helper", "x" * 300), ("plain-skill", "No Chinese title.")):
        folder = Path(os.environ["AGENT_HOME"]) / "skills" / name
        folder.mkdir(parents=True)
        titled = "" if name == "plain-skill" else "metadata:\n  mibo-title-zh: 行李清单\n  mibo-description-zh: 说明\n"
        (folder / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {about}\n{titled}---\n\nSteps.\n",
                                         encoding="utf-8")
    app.post("/api/look/toured")
    measured(app)
    page = browser.open(app, lang="zh", width=1400, settle=False)
    p = page.page
    p.locator("#side-settings").click()
    p.locator(".setup-nav-item[data-part=abilities]").click()
    p.locator(".skm-grid > .skm-card").first.wait_for()
    page.settle()

    shown = p.evaluate(TILES)
    assert shown["count"] > 3 and shown["columns"] >= 3
    assert shown["outside"] == []

    # No title in Chinese: its name, once.
    plain = p.locator("[data-item=skill-plain-skill]")
    assert plain.locator(".skm-card-title").inner_text() == "plain-skill"
    assert plain.locator(".skm-card-by").inner_text() == ""

    switch = p.locator("#setup-switch-skill-packing-list")
    assert switch.is_checked()
    switch.click()
    page.settle()
    assert not p.locator("#setup-switch-skill-packing-list").is_checked()
    assert {row["name"]: row["on"] for row in app.get("/api/skills").json()["skills"]}["packing-list"] is False
    assert page.errors == [] and page.refused == []
