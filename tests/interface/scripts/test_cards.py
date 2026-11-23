"""A question in the chat (chat.js): a turn that needs the person's yes says what it will do under the reply on its
way, with no buttons, and what the person types in the chat box is what the server acts on: a plain yes runs the
step, and any other message is a no for it and is then sent as the ordinary message it is."""
from __future__ import annotations

import time

import pytest
from harness.folders import Profile
from harness.model import call, say
from harness.page import measured

from mibo.acting import Modes

pytestmark = pytest.mark.browser


def _taken(app) -> bool:
    """Whether the server has the answer within a few seconds. One it never got is given here, so the turn ends and
    the app can stop while the test fails."""
    for _ in range(50):
        waiting = app.get("/api/turnon/card").json()["card"]
        if not waiting:
            return True
        time.sleep(0.1)
    app.post("/api/confirm", {"id": waiting["id"], "text": "no"}, own_page=True)
    return False


@pytest.mark.parametrize("typed, listed", [("确定", True), ("不用了，我自己看", False)])
def test_a_question_a_turn_raises_shows_in_the_chat_and_the_typed_answer_decides_what_runs(
        app, model, browser, monkeypatch, tmp_path, typed, listed):
    person = Profile(tmp_path / "profile", monkeypatch)
    Modes(app.home / "runtime" / "desktop").set("off")
    app.post("/api/look/toured")
    measured(app)
    # The words that are not a yes are sent on as a message of their own once the reply ends.
    model.script(call("list_files", path=str(person.root / "Desktop")), say("Here is what I found."),
                 *([] if listed else [say("好的。")]))
    page = browser.open(app)
    box = page.page.locator(".chat-empty .chat-input:visible")
    box.fill("What is on my desktop?")
    box.press("Enter")
    card = page.page.locator(".chat-messages .op-card")
    card.locator(".op-card-ask").wait_for()
    assert card.locator("button").count() == 0
    box = page.page.locator(".chat-input:visible")
    box.fill(typed)
    box.press("Enter")
    card.locator(".op-card-ask").wait_for(state="hidden")
    assert _taken(app)
    page.page.get_by_text("Here is what I found.").wait_for()
    if not listed:
        page.page.get_by_text("好的。").wait_for()
    asked = model.asked()
    (result,) = [m["content"] for m in asked[1]["body"]["messages"] if m.get("role") == "tool"]
    assert ("待办.txt" in result) is listed
    assert len(asked) == (2 if listed else 3)
    assert page.errors == [] and page.refused == []
