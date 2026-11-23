"""The first run's sample finds (feed.first_round): every picked topic, every chosen platform with a find, video
and text and a couple off the topics are asked about; a near-duplicate of a thing asked gives way to another
subject; FIRST_PER_SOURCE from one site unless too few sites have something, never one site twice running, and
the round stops rather than break that; the same library gives the same round, and an empty one none. What an
answer would teach is the model's own (taste.Belief)."""
from __future__ import annotations

import math
from itertools import pairwise

import pytest
from harness.clock import Clock
from harness.finds import Shelf

from mibo import profile, subjects, taste
from mibo.panels import feed

NOW = 1_800_000_000
SUMMARY = "A summary long enough to say what the story is about, and then some more of it."
OTHERS = ["Football match recap", "New laptop review", "Stars and galaxies through a telescope", "Stock market falls",
          "A painting exhibition", "A jazz concert tonight", "A new novel by an author", "Election results",
          "A classic film restored", "A cat and a dog"]


@pytest.fixture
def shelf(tmp_path, monkeypatch):
    return Shelf(tmp_path / "runtime", Clock(monkeypatch, NOW), monkeypatch)


def first(shelf: Shelf, topics: list[str] = (), chosen: list[str] = ()) -> list[dict]:
    return feed.first_round(shelf.library, shelf.events(), shelf.clock.now, list(topics), list(chosen))


def about(row: dict) -> tuple:
    return subjects.of(row["title"], "")


def test_every_picked_topic_chosen_platform_and_form_is_asked_about_and_some_outside_the_topics(shelf):
    for n in range(3):
        for k, title in enumerate(OTHERS[:8]):
            shelf.add(f"{title} {n}", site=f"site{k}.example", text=SUMMARY, hours_ago=0.5)
    # Older than everything else and one of each: nothing but the design asks for them.
    food = shelf.add("Braised pork recipe", site="kitchen.example", text=SUMMARY, hours_ago=40)
    game = shelf.add("A new video game release", site="arcade.example", text=SUMMARY, hours_ago=40)
    room = shelf.add("今晚的围棋直播", site="www.douyu.com", kind="video", text="直播", hours_ago=40)
    shown = first(shelf, ["food", "games"], ["douyu.com"])
    ids = [row["id"] for row in shown]
    assert len(shown) == feed.FIRST_MAX and {food.id, game.id, room.id} <= set(ids)
    assert sum(1 for row in shown if not {"food", "games"} & set(about(row))) >= feed.FIRST_OUTSIDE
    # The picked topics lead: the round opens on what the person ticked.
    assert set(ids[:2]) == {food.id, game.id}


def test_a_near_duplicate_of_a_thing_asked_gives_way_to_another_subject(shelf):
    for n in range(10):
        shelf.add(f"Braised pork recipe {n}", site=f"kitchen{n}.example", text=SUMMARY, hours_ago=0.5)
        shelf.add(OTHERS[n], site=f"other{n}.example", text=SUMMARY, hours_ago=0.5)
    shown = first(shelf)
    assert len(shown) == feed.FIRST_MAX
    assert sum(1 for row in shown if "food" in about(row)) <= 1
    assert len({about(row) for row in shown}) >= feed.FIRST_MAX - 1


@pytest.mark.parametrize("sites, most", [(("kitchen", "pitch", "gadget", "harbour", "garden"), 2),
                                         (("kitchen", "pitch", "gadget"), 4)])
def test_two_from_a_site_at_most_unless_too_few_sites_have_something_and_never_one_site_twice_running(
        shelf, sites, most):
    for n in range(5):
        for site in sites:
            shelf.add(f"A story from the {site} number {n}", site=f"{site}.example", text=SUMMARY)
    shown = [row["site"] for row in first(shelf)]
    # Five sites fill the round two each; three cannot, and then a site gives more.
    assert len(shown) == feed.FIRST_MAX and max(shown.count(s) for s in shown) == most, shown
    assert all(a != b for a, b in pairwise(shown)), shown


def test_the_round_stops_rather_than_show_one_site_twice_running(shelf):
    for n in range(5):
        shelf.add(f"A story from the kitchen number {n}", site="kitchen.example", text=SUMMARY)
    shelf.add("A story from the pitch", site="pitch.example", text=SUMMARY)
    assert [row["site"] for row in first(shelf)] == ["kitchen.example", "pitch.example", "kitchen.example"]
    shelf.add("A story from the harbour", site="harbour.example", text=SUMMARY)
    sites = [row["site"] for row in first(shelf)]
    assert len(sites) == 5 and not any(a == b for a, b in pairwise(sites))


def test_the_same_library_gives_the_same_round_and_an_empty_one_none(shelf):
    assert first(shelf, ["food"]) == []
    for n in range(4):
        for k, title in enumerate(OTHERS):
            shelf.add(f"{title} {n}", site=f"site{k}.example", text=SUMMARY, hours_ago=n + k / 10)
    assert [row["id"] for row in first(shelf, ["food"])] == [row["id"] for row in first(shelf, ["food"])]


def test_what_the_person_already_answered_is_asked_about_less_on_a_second_run(shelf):
    made = [shelf.add(f"Braised pork recipe {n}", site=f"kitchen{n}.example", text=SUMMARY, hours_ago=0.5)
            for n in range(10)]
    for n in range(10):
        shelf.add(OTHERS[n], site=f"other{n}.example", text=SUMMARY, hours_ago=0.6)
    # Fresher, so the first run opens on one.
    assert "food" in about(first(shelf)[0])
    for item in made[:6]:
        shelf.react(item, "seen", surface="first")
        shelf.react(item, "like", surface="first")
    shelf.learn()
    assert not any("food" in about(row) for row in first(shelf)[:feed.FIRST_MAX - 1])


def test_a_hidden_source_and_a_topic_said_no_to_are_never_asked_about(shelf):
    wire = [shelf.add(f"A painting exhibition {n}", site=f"wire{n}.example", text=SUMMARY, source="art-wire")
            for n in range(3)]
    shelf.react(wire[0], "seen")
    shelf.react(wire[0], "hide_source")
    profile.edit(shelf.runtime, {"rules": [{"kind": "topic", "topic": "football"}]})
    for n in range(4):
        shelf.add(f"Football match recap {n}", site=f"pitch{n}.example", text=SUMMARY, hours_ago=0.1)
    shelf.add("Braised pork recipe", site="kitchen.example", text=SUMMARY)
    assert [row["title"] for row in first(shelf)] == ["Braised pork recipe"]


def test_an_answer_counted_ahead_adds_its_fisher_weight_to_each_feature_it_has():
    belief = taste.Belief({"m": {"a": 1.0}, "q": {"a": 4.0}}, lambda k: (0.0, 2.0))
    x = {"a": 1.0, "b": 0.5}
    p, var = belief.chance(x)
    assert p == pytest.approx(1 / (1 + math.exp(-1))) and var == pytest.approx(1 / 4 + 0.25 / 2)
    c = p * taste.LIKE[1] + (1 - p) * taste.SKIP[1]
    assert belief.gain(x) == pytest.approx(0.5 * math.log1p(c * p * (1 - p) * var))
    before = belief.gain({"b": 1.0}), belief.gain({"c": 1.0})
    belief.asked(x)
    assert belief.q == pytest.approx({"a": 4 + c * p * (1 - p), "b": 2 + c * p * (1 - p) * 0.25})
    # The mean holds (no answer is known yet); what shares a feature with the thing asked teaches less.
    assert belief.chance(x)[0] == p
    assert belief.gain({"b": 1.0}) < before[0] and belief.gain({"c": 1.0}) == before[1]
