"""A question a step waits on, in the chat (chat.js, chatthread.js, cardwait.py): the app's question is the
character's message and the person's answer is their own message, in order, as the chat keeps them. An ordinary
question has no card and no button: what the person types decides it, a plain yes runs the step and anything else is
a no that is then answered as the ordinary message it is. A very important step (cardwait.ALONE) is one card in the
conversation, its act's button named in the app's words; a press or a typed yes answers it, and it stays answered."""
from __future__ import annotations

import json

import pytest
from harness.folders import Profile
from harness.model import call, say
from harness.page import measured

from mibo import i18n
from mibo.acting import Modes
from mibo.shell import checkpoint
from mibo.shell.grants import Grants

pytestmark = pytest.mark.browser

# The thread as the person reads it, in order: their messages, the questions and the character's other lines.
THREAD = """() => [...document.querySelectorAll(".chat-messages .me, .chat-messages .line:not(.typing)")].map((n) =>
  n.classList.contains("me") ? ["me", n.querySelector(".bubble-text")?.textContent || ""]
    : [n.dataset.ask ? "ask" : "ai", (n.querySelector(".say, .ask-card-text")?.textContent || "").trim()])"""


def _chat(browser, app):
    """The app's page past its first run, on the main chat."""
    app.post("/api/look/toured")
    measured(app)
    page = browser.open(app)
    page.page.locator(".chat-empty .chat-input:visible").wait_for()
    return page


def _type(page, text: str) -> None:
    box = page.page.locator(".chat-input:visible")
    box.fill(text)
    box.press("Enter")


def _again(page) -> list:
    """The conversation as the page draws it after a reload, once its messages are there."""
    page.reload()
    page.page.locator(".chat-messages .line:not(.typing)").first.wait_for()
    return page.page.evaluate(THREAD)


def _ended(page) -> None:
    page.page.locator(".chat-send:not(.stopping)").wait_for()
    page.settle()


@pytest.fixture
def desktop(app, tmp_path, monkeypatch):
    """A profile whose desktop a turn lists while acting is off: turning it on is an ordinary question."""
    person = Profile(tmp_path / "profile", monkeypatch)
    Modes(app.home / "runtime" / "desktop").set("off")
    return person.root / "Desktop"


@pytest.fixture
def notes(app, tmp_path, monkeypatch):
    """notes.txt in a granted folder where no checkpoint keeps a file: rewriting it is very important (a card)."""
    place = tmp_path / "work"
    place.mkdir()
    (place / "notes.txt").write_text("old\n", encoding="utf-8")
    assert Grants(app.home / "runtime" / "desktop", app.home).add(str(place)) == ""
    monkeypatch.setattr(checkpoint, "KEEP_MAX", 1)
    return place / "notes.txt"


def _listed(model) -> bool:
    (result,) = [m["content"] for m in model.asked()[1]["body"]["messages"] if m.get("role") == "tool"]
    return "待办.txt" in result


def test_a_typed_yes_is_the_persons_message_after_the_question_and_the_reply_follows(app, model, browser, desktop):
    model.script(call("list_files", path=str(desktop)), say("Here is what I found."))
    page = _chat(browser, app)
    _type(page, "What is on my desktop?")
    question = page.page.locator(".chat-messages .line[data-ask]")
    question.wait_for()
    # An ordinary question is the character's plain words: no card and no button anywhere in the chat.
    assert page.page.locator(".chat-messages .ask-card").count() == 0
    assert page.page.locator(".chat-messages button").count() == 0
    asked = question.locator(".say").inner_text()
    assert asked.endswith("?")
    _type(page, "确定")
    page.page.get_by_text("Here is what I found.").wait_for()
    _ended(page)
    assert page.page.evaluate(THREAD) == [["me", "What is on my desktop?"], ["ask", asked], ["me", "确定"],
                                          ["ai", "Here is what I found."]]
    # The reply after the answer is a new message of the character's, its own run under its name.
    assert page.page.locator(".chat-messages .ai").count() == 2
    assert _listed(model) and len(model.asked()) == 2
    # A reload draws the same conversation from what the chat kept.
    assert _again(page) == [["me", "What is on my desktop?"], ["ask", asked], ["me", "确定"],
                            ["ai", "Here is what I found."]]
    stored = app.get("/api/chat/history").json()["messages"]
    assert [m["role"] for m in stored] == ["user", "assistant", "user", "assistant"]
    assert stored[1]["ask"]["state"] == "yes" and stored[2]["answers"] == stored[1]["ask"]["id"]
    assert page.errors == [] and page.refused == []


def test_anything_else_typed_shows_as_their_message_leaves_the_step_undone_and_is_answered(app, model, browser,
                                                                                         desktop):
    # The turn's reply after the declined step, then the reply to their words as a message of their own.
    model.script(call("list_files", path=str(desktop)), say("I did not look."), say("好的，我先不看。"))
    page = _chat(browser, app)
    _type(page, "What is on my desktop?")
    page.page.locator(".chat-messages .line[data-ask]").wait_for()
    _type(page, "不用了，我自己看")
    # Their words show at once, before anything comes back.
    page.page.locator(".chat-messages .me").get_by_text("不用了，我自己看").wait_for()
    page.page.get_by_text("好的，我先不看。").wait_for()
    _ended(page)
    thread = page.page.evaluate(THREAD)
    assert [kind for kind, _ in thread] == ["me", "ask", "me", "ai", "ai"]
    assert thread[2] == ["me", "不用了，我自己看"] and thread[-1] == ["ai", "好的，我先不看。"]
    assert not _listed(model) and len(model.asked()) == 3
    # The words are answered where they stand, once: the last request ends with them.
    assert "不用了，我自己看" in json.dumps(model.asked()[2]["body"]["messages"][-1], ensure_ascii=False)
    assert _again(page) == thread
    assert page.errors == [] and page.refused == []


def test_a_very_important_step_is_one_card_whose_act_button_runs_it_and_stays_answered(app, model, browser, notes):
    model.script(call("write_file", path="notes.txt", content="new\n", folder=str(notes.parent)), say("Rewritten."))
    page = _chat(browser, app)
    _type(page, "Rewrite notes.txt")
    card = page.page.locator(".chat-messages .ask-card")
    card.locator(".pa-btn-primary").wait_for()
    assert card.count() == 1 and page.page.locator(".chat-messages .line[data-ask]").count() == 1
    act, decline = i18n.t("ask.acts.replace", "en"), i18n.t("ask.decline", "en")
    assert card.locator("button").all_inner_texts() == [act, decline]
    # The decisive fact is in the card's own sentence.
    assert card.locator(".ask-card-text").inner_text().startswith(i18n.t("ask.costly.replace", "en"))
    card.locator(".pa-btn-primary").click()
    page.page.get_by_text("Rewritten.").wait_for()
    _ended(page)
    assert notes.read_text(encoding="utf-8") == "new\n"
    thread = page.page.evaluate(THREAD)
    assert [kind for kind, _ in thread] == ["me", "ask", "me", "ai"] and thread[2] == ["me", act]
    # Answered: what was decided and when, and no buttons, also after a reload.
    for _ in range(2):
        answered = page.page.locator(".chat-messages .ask-card.answered")
        assert answered.count() == 1 and answered.locator("button").count() == 0
        assert answered.locator(".ask-card-told").inner_text().startswith("Done")
        again = _again(page)
    assert again == thread
    assert page.errors == [] and page.refused == []


def test_declining_a_card_leaves_the_step_undone(app, model, browser, notes):
    model.script(call("write_file", path="notes.txt", content="new\n", folder=str(notes.parent)), say("Left it."))
    page = _chat(browser, app)
    _type(page, "Rewrite notes.txt")
    card = page.page.locator(".chat-messages .ask-card")
    card.locator(".pa-btn-secondary").click()
    page.page.get_by_text("Left it.").wait_for()
    _ended(page)
    assert notes.read_text(encoding="utf-8") == "old\n"
    assert page.page.evaluate(THREAD)[2] == ["me", i18n.t("ask.decline", "en")]
    assert card.locator(".ask-card-told").inner_text().startswith("Not done")
    # A press is the answer: nothing is sent on to be answered as a message.
    assert len(model.asked()) == 2
    assert page.errors == [] and page.refused == []


def test_a_typed_yes_answers_a_card_too(app, model, browser, notes):
    model.script(call("write_file", path="notes.txt", content="new\n", folder=str(notes.parent)), say("Rewritten."))
    page = _chat(browser, app)
    _type(page, "Rewrite notes.txt")
    page.page.locator(".chat-messages .ask-card .pa-btn-primary").wait_for()
    _type(page, "确定")
    page.page.get_by_text("Rewritten.").wait_for()
    _ended(page)
    assert notes.read_text(encoding="utf-8") == "new\n"
    assert page.page.evaluate(THREAD)[2] == ["me", "确定"]
    assert page.page.locator(".chat-messages .ask-card.answered button").count() == 0
    assert page.errors == [] and page.refused == []
