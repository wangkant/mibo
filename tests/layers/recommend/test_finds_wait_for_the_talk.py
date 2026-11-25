"""A find the share step brings into the main chat waits while the person and the character are talking there (a word
between them within pacing.TALK_S, a message of theirs waiting for its answer, a question waiting on them) and comes
at the next good moment after it; once brought it reaches the model in their next message as an aside, apart from what
they were talking about, while a card their message answers is still named as what they reply to."""
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest
from harness.clock import Clock
from harness.finds import Shelf
from harness.model import say

from mibo import activity, pacing, quiet, welcome

LINE = "A ride across the high passes, filmed the whole way."


@pytest.fixture
def share(app, monkeypatch):
    """The app past its first run at a still moment (no typing, a pause in front, nothing quiet), with finds waiting
    for the share step: `share()` runs it once and gives how many it brought, `taken` the finds it took."""
    clock = Clock(monkeypatch, time.time())
    monkeypatch.setattr(activity, "sense", lambda ignore=(): activity.Sample("", 120.0, False))
    monkeypatch.setattr(activity, "idle", lambda: 120.0)
    monkeypatch.setattr(quiet, "state", lambda: {"quiet": False, "why": "", "since": 0.0, "video_front": False})
    monkeypatch.setattr(quiet, "typed_ago", lambda: float("inf"))
    # The app's own share step sleeps (its wake is one nothing sets): the test runs the step itself, at the times it
    # sets.
    monkeypatch.setattr(app.workspace, "_share_wake", asyncio.Event())
    welcome.save_app_settings(app.workspace._desktop, toured=True)
    shelf = Shelf(app.home / "runtime", clock, monkeypatch)
    finds = [shelf.add("Riding the high passes", site="video.example", kind="video", length=1200),
             shelf.add("A field guide to moss", site="moss.example")]
    taken = []

    async def take(surface: str, now: bool = False):
        # The pet's card may look too; only the share step takes these.
        if surface != "chat":
            return None
        taken.append(finds[len(taken)])
        return {"line": LINE}, taken[-1]

    monkeypatch.setattr(app.workspace.chooser, "take", take)
    return SimpleNamespace(clock=clock, finds=finds, taken=taken, run=lambda: asyncio.run(app.workspace.share()))


def _said(app) -> str:
    """Their last message as the last reply request carried it, without the turn context."""
    body = [r["body"] for r in app.model.requests if r.get("purpose") == "reply"][-1]
    last = next(m for m in reversed(body["messages"]) if m["role"] == "user")["content"]
    return last.split("[Turn context]")[0]


def test_a_find_waits_while_they_talk_in_the_main_chat_and_comes_at_the_next_good_moment(app, turn, share):
    turn("compare the two phones' battery life", say("The Pixel lasts about two hours longer."))
    share.clock.move(pacing.TALK_S - 60)
    assert share.run() == 0 and share.taken == []
    share.clock.move(120)
    assert share.run() == 1
    (brought,) = app.workspace._main.shared()
    assert brought["card"]["id"] == share.finds[0].id and brought["unasked"] is True


def test_a_find_waits_while_a_message_of_theirs_or_a_question_waits_however_long_ago(app, share):
    room = app.workspace._main
    (asked,) = room.append([{"role": "user", "text": "delete the old logs", "pending": True}])
    share.clock.move(pacing.TALK_S * 3)
    assert share.run() == 0
    asked.pop("pending")
    (question,) = room.append([{"role": "assistant", "text": "Delete 3 files?",
                                "ask": {"id": "q1", "state": "waiting"}}])
    share.clock.move(pacing.TALK_S * 3)
    assert share.run() == 0 and share.taken == []
    question["ask"]["state"] = "yes"
    assert share.run() == 1


def test_a_brought_find_reaches_the_model_as_an_aside_and_a_card_they_answer_as_what_they_reply_to(app, turn, share):
    turn("compare the two phones' battery life", say("The Pixel lasts about two hours longer."))
    share.clock.move(pacing.TALK_S + 60)
    assert share.run() == 1
    turn("put the result above in a table", say("| phone | hours |"))
    said = _said(app)
    assert "[aside" in said and LINE in said and "[reply" not in said
    # Past the pacing's own gap since the last find as well.
    share.clock.move(pacing.CAP_S * 2)
    assert share.run() == 1
    app.model.script(say("About twenty minutes."))
    assert app.post("/api/chat", {"text": "how long is it?", "reply_to": share.finds[1].id}).status_code == 200
    said = _said(app)
    assert "[aside" not in said and said.count("[reply Mibo:") == 1 and "A field guide to moss" in said
