"""The painted figures' pet sheets (<key>.pet.webp laid out in <key>.pet.json, written by tools/figure_sheet.py)
as the pet's page reads them: every pose it plays, each piece inside the packed picture and its window, and the
three figures drawn as one set, none standing a head shorter than the others."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

FIGURES = Path(__file__).resolve().parents[3] / "mibo" / "static" / "welcome" / "figures"
PAINTED = ("chatgpt", "deepseek", "claude")
# The poses pet.js plays; blink, talk, talk2 and look are drawn over rest, the peek faces over peek.
POSES = {
    "rest", "idle2", "blink", "talk", "talk2", "look", "look_left", "look_right",
    "walk1", "walk2", "walk3", "walk4", "turn", "crouch", "air", "land", "held", "held2", "dizzy",
    "surprised", "wave1", "wave2", "give", "doze", "asleep", "peek", "peek_blink", "peek_talk", "peek_look",
}
ON = {"blink": "rest", "talk": "rest", "talk2": "rest", "look": "rest",
      "peek_blink": "peek", "peek_talk": "peek", "peek_look": "peek"}
# How far apart the rest poses may stand on the sheet: horns and a maid's headdress count toward height.
SAME_HEIGHT = 0.10


def layout(key: str) -> dict:
    return json.loads((FIGURES / f"{key}.pet.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("key", PAINTED)
def test_a_painted_figure_has_every_pose_the_pet_plays_inside_its_picture_and_window(key):
    laid = layout(key)
    with Image.open(FIGURES / f"{key}.pet.webp") as picture:
        wide, high = picture.size
    window = (laid["cell"][0] * laid["scale"], laid["cell"][1] * laid["scale"])
    assert set(laid["frames"]) == POSES
    for name, frame in laid["frames"].items():
        x, y, w, h = frame["at"]
        assert 0 <= x and 0 <= y and x + w <= wide and y + h <= high, name
        to_x, to_y = frame["to"]
        assert 0 <= to_x and 0 <= to_y and to_x + w <= window[0] and to_y + h <= window[1], name
        assert frame.get("on") == ON.get(name), name
    for name in ("walk1", "walk2", "walk3", "walk4"):
        assert laid["frames"][name]["advance"] > 0, name


def test_the_three_painted_figures_stand_about_as_tall_as_one_another():
    tall = {key: layout(key)["frames"]["rest"]["at"][3] for key in PAINTED}
    assert min(tall.values()) >= (1 - SAME_HEIGHT) * max(tall.values()), tall
