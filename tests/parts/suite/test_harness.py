"""The shared harness does what the suite relies on: a scripted turn runs through the real page and loop with
every tool result passed back, inner calls reach their own scripts, an unscripted request fails the test, the
failure rounds answer as a failing host does, the stand-in sites are the only internal addresses the app may
reach, and the clock and the profile are where the app looks."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os

import httpx
import pytest

from harness import attacks
from harness.app import KEY
from harness.clock import Clock
from harness.folders import KEYS, Profile
from harness.model import (MODEL, SYSTEM_OF, Unscripted, call, content_filter, error_in_200, fail, hang, say,
                           text, think)
from harness.sites import Site
from harness.turn import run_turn
from mibo import ingestion, life, review, roam, updates
from mibo.acting import Modes
from mibo.shell import grants

# How a page's words open when they reach the model as external material.
FENCED = roam.fence_pages("").partition("\n")[0]


def _tools_hash(body: dict) -> str:
    return hashlib.sha256(json.dumps(body["tools"], sort_keys=True).encode()).hexdigest()


def test_a_scripted_turn_reads_a_page_and_keeps_a_schedule_with_every_result_passed_back(app, site, turn):
    page = f"{site.url}/og"
    done = turn(f"Read {page} and remind me tomorrow at 9am to call mum",
                [call("read_page", url=page),
                 call("schedule_create", title="Call mum", kind="remind", request="Call mum", when="tomorrow at 9am")],
                say("Read it, and the reminder is set."))
    assert done.status == 200 and done.reply == "Read it, and the reminder is set."
    read, kept = done.calls()
    assert (read["name"], kept["name"]) == ("read_page", "schedule_create")
    # Each result reached the model in the next round, beside the call it answers.
    assert done.result_of(read["id"]).startswith(FENCED) and "Tide pools" in done.result_of(read["id"])
    assert "Call mum" in done.result_of(kept["id"])
    first, second = done.asked()
    assert [m["role"] for m in second["messages"][-3:]] == ["assistant", "tool", "tool"]
    # The same tools, chosen by the model, in every round; no reply format forced.
    assert _tools_hash(first) == _tools_hash(second)
    assert {b["tool_choice"] for b in (first, second)} == {"auto"} and "response_format" not in first
    # The effects, read where they landed: the site served the page once, the page keeps the task.
    assert site.log.count("GET /og") == 1
    assert [t["title"] for t in app.get("/api/schedule").json()["tasks"]] == ["Call mum"]
    assert [s["url"] for s in done.sources] == [page] and [s["tool"] for s in done.trace] == ["read"]
    # The key goes as the bearer token alone.
    assert {r["key"] for r in done.requests} == {KEY}
    assert all("authorization" not in r["headers"] for r in done.requests)


def test_reasoning_is_passed_back_with_the_calls_it_came_with(site, turn):
    done = turn("What does that page say?", [think("I should read it first."), call("read_page", url=f"{site.url}/og")],
                say("It is about tide pools."))
    assert done.asked()[1]["messages"][-2]["reasoning_content"] == "I should read it first."


def test_a_card_the_turn_raises_is_answered_through_the_pages_card_route(app, turn):
    acting = Modes(app.home / "runtime" / "desktop")
    acting.set("off")
    done = turn("List what is on my desktop", call("list_files", path="Desktop"), say("It stays off."), cards="no")
    assert [(c["kind"], c["answer"]) for c in done.cards] == [("shell", "no")]
    (listed,) = done.calls()
    assert done.result_of(listed["id"]).startswith("Error:") and acting.mode() == "off"


def test_an_unscripted_request_fails_the_turn_and_shows_the_request(app):
    with pytest.raises(Unscripted, match="unscripted model request") as failed:
        run_turn(app, "Nobody scripted an answer to this")
    assert "Nobody scripted an answer to this" in str(failed.value)


def test_a_scripted_answer_left_unasked_fails_the_turn(app):
    with pytest.raises(AssertionError, match="never asked for"):
        run_turn(app, "hello", say("hi"), say("a second answer nobody asks for"))
    app.model.reset()


@pytest.mark.parametrize("purpose", list(SYSTEM_OF))
def test_each_inner_call_is_answered_from_its_own_script(model, purpose):
    model.script(say("the reply script")).script(text(f"the {purpose} script"), purpose=purpose)
    asked = httpx.post(f"{model.url}/chat/completions", timeout=10, json={
        "model": MODEL, "messages": [{"role": "system", "content": SYSTEM_OF[purpose]},
                                     {"role": "user", "content": "the request"}]})
    assert asked.json()["choices"][0]["message"]["content"] == f"the {purpose} script"
    assert model.left() == 1 and len(model.asked(purpose)) == 1


def test_the_apps_reviewer_reaches_the_reviewer_script_and_never_the_reply(model):
    verdict = {"kind_asked": True, "target_named": True, "text_given": True, "nothing_added": True,
               "does": "send", "decision": "go", "reason": "They asked to send exactly this to Ana."}
    model.script(say("the reply script")).script(text(json.dumps(verdict)), purpose="reviewer")
    action = {"area": "browser", "kind": "outward", "where": "chat.example", "target": ["Ana"],
              "text": "see you at six"}
    found = asyncio.run(review.review(["Send 'see you at six' to Ana"], action, lang="en",
                                      ask=review.endpoint(model.url, KEY, MODEL)))
    assert (found.decision, found.by) == ("go", "review")
    # What reached the reviewer: the person's words and the act, under the reviewer's own instructions.
    (asked,) = model.asked("reviewer")
    assert asked["body"]["messages"][0]["content"] == review.POLICY and "see you at six" in json.dumps(asked)
    assert model.left() == 1


def test_the_failure_rounds_answer_as_a_failing_host_does(model):
    model.script(fail(429), error_in_200(), content_filter(), hang())

    def ask(timeout: float = 10) -> httpx.Response:
        return httpx.post(f"{model.url}/chat/completions", timeout=timeout,
                          json={"model": MODEL, "messages": [{"role": "user", "content": "hi"}]})

    assert ask().status_code == 429
    assert ask().json()["error"]["code"] == "overloaded"
    assert ask().json()["choices"][0]["finish_reason"] == "content_filter"
    with pytest.raises(httpx.ReadTimeout):
        ask(timeout=0.5)


def test_a_failed_model_call_reaches_the_page_as_a_failed_message(app):
    done = run_turn(app, "hello", fail(503))
    assert done.status == 502 and done.reply == ""


@pytest.mark.parametrize("attack", attacks.load("page"))
def test_a_page_carrying_an_attack_reaches_the_model_only_as_a_fenced_tool_result(site, turn, attack):
    page = site.url + attack["page"]
    done = turn("Sum up this page for me: " + page, call("read_page", url=page), say("Here is the gist."))
    (read,) = done.calls()
    assert done.result_of(read["id"]).startswith(FENCED)
    for message in done.asked()[1]["messages"]:
        if message["role"] != "tool":
            assert attack["mark"] not in json.dumps(message, ensure_ascii=False)


def test_only_the_stand_in_sites_are_reachable_and_they_log_what_they_receive(site, tmp_path):
    other = Site(tmp_path)
    try:
        async def fetch(url: str):
            return await ingestion.safe_fetch_url(url, timeout=5, max_wire_bytes=1 << 20, max_decoded_bytes=1 << 21)

        assert b"Tide pools" in asyncio.run(fetch(f"{site.url}/og")).content
        # opsite's pages and its record of what it was sent, from the same server.
        assert asyncio.run(fetch(f"{site.url}/t/t01-chat.html")).status_code == 200
        assert asyncio.run(fetch(f"{other.url}/og")) is None
        httpx.post(f"{site.url}/api/send", json={"to": "Ana", "text": "hi"}, timeout=5)
        assert site.state()["sent"] == [{"to": "Ana", "text": "hi"}]
        assert site.log[-1].startswith("POST /api/send ") and json.loads(site.log[-1][15:]) == {"to": "Ana", "text": "hi"}
        assert site.put("/mine", "<title>Mine</title>") == f"{site.url}/mine"
        assert httpx.get(f"{site.url}/mine", timeout=5).text == "<title>Mine</title>"
    finally:
        other.close()


def test_the_clock_moves_what_the_app_reads_as_now(monkeypatch, tmp_path):
    clock = Clock(monkeypatch, 1_800_000_000)
    assert life.clock() == 1_800_000_000
    home = tmp_path / "home"
    (home / "runtime" / "desktop").mkdir(parents=True)
    (home / "runtime" / "desktop" / "update.json").write_text(json.dumps({"checked": clock.now, "latest": "1.0.0"}))
    assert not updates.stale(home)
    clock.move(updates.CHECK_EVERY_S + 1)
    assert updates.stale(home) and life.clock() == 1_800_000_000 + updates.CHECK_EVERY_S + 1


def test_the_profile_is_where_the_app_looks_and_its_keys_are_ones_the_app_hides(monkeypatch, tmp_path):
    profile = Profile(tmp_path / "profile", monkeypatch)
    desktop = next(guid for key, guid, *_ in grants.KNOWN if key == "desktop")
    assert grants.known_folder(desktop) == str(profile.root / "Desktop")
    places = grants.Places(tmp_path / "home")
    assert places.profile == grants.norm(profile.root)
    assert [key for key in KEYS if places.blocked(grants.norm(profile.root / key), False) != "secrets"] == []
    assert places.blocked(grants.norm(profile.root / "Documents" / "简历.docx"), False) == ""
    assert os.path.getsize(profile.root / "Downloads" / "setup.bin") >= 1_500_000
