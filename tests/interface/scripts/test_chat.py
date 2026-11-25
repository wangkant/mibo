"""The chat page's scripts (chat.js, app.js) against the app and the scripted model: what a person types reaches
the model and its reply shows, stop ends a turn and gives the words back, a message typed while a reply runs waits
in a row above the box until the reply ends by itself, and a 无痕对话 opened from its toggle leaves nothing behind."""
from __future__ import annotations

import json
import threading
import time

import pytest
from harness.model import hang, held, say
from harness.page import measured

pytestmark = pytest.mark.browser


def _chat(browser, app):
    """The app's page past its first run, on the main chat."""
    app.post("/api/look/toured")
    measured(app)
    page = browser.open(app)
    # The box sits in the empty start once the chat's history is read; words sent before that are drawn over.
    page.page.locator(".chat-empty .chat-input:visible").wait_for()
    return page


def test_a_message_typed_in_the_box_reaches_the_model_and_its_reply_shows(app, model, browser):
    page = _chat(browser, app)
    model.script(say("Tide pools fill at high water."))
    box = page.page.locator(".chat-input:visible")
    box.fill("What are tide pools?")
    box.press("Enter")
    page.page.get_by_text("Tide pools fill at high water.").wait_for()
    (asked,) = model.asked()
    assert "What are tide pools?" in json.dumps(asked["body"]["messages"][-1], ensure_ascii=False)
    assert page.page.locator(".chat-messages").get_by_text("What are tide pools?").count() == 1
    assert page.errors == [] and page.refused == []


def test_stop_ends_the_turn_and_gives_the_words_back_to_the_box(app, model, browser):
    page = _chat(browser, app)
    model.script(hang())
    box = page.page.locator(".chat-input:visible")
    box.fill("Plan a week of dinners")
    box.press("Enter")
    stop = page.page.locator(".chat-send.stopping")
    stop.wait_for()
    stop.click()
    page.page.locator(".chat-send:not(.stopping)").wait_for()
    assert box.input_value() == "Plan a week of dinners"
    # The request to the service is closed just after the page has its box back.
    waited = time.monotonic() + 30
    while app.get("/api/chat/doing").json()["busy"] and time.monotonic() < waited:
        time.sleep(0.05)
    assert app.get("/api/chat/doing").json()["busy"] is False
    (last,) = [m for m in app.get("/api/chat/history").json()["messages"] if m["role"] == "user"]
    assert last["text"] == "Plan a week of dinners" and last.get("failed") == "stopped"
    assert page.errors == []


def _type(page, text: str) -> None:
    box = page.page.locator(".chat-input:visible")
    box.fill(text)
    box.press("Enter")


def _sent(model) -> list[str]:
    """The words each request to the model ended with, in order."""
    return [json.dumps(asked["body"]["messages"][-1], ensure_ascii=False) for asked in model.asked()]


def _rows(page) -> list[str]:
    return page.page.locator(".chat-queue-row .chat-queue-text").all_inner_texts()


def test_a_message_typed_during_a_reply_waits_in_a_row_and_is_sent_when_the_reply_ends(app, model, browser):
    gate = threading.Event()
    model.script(held(gate, say("Low tide is at six.")), say("Bring boots."))
    page = _chat(browser, app)
    _type(page, "When is low tide?")
    page.page.locator(".chat-send.stopping").wait_for()
    box = page.page.locator(".chat-input:visible")
    box.fill("What should I bring?")
    assert page.page.locator(".chat-send").get_attribute("aria-label") == "Queue"
    box.press("Enter")
    assert _rows(page) == ["What should I bring?"] and box.input_value() == ""
    gate.set()
    page.page.get_by_text("Bring boots.").wait_for()
    page.page.locator(".chat-queue").wait_for(state="hidden")
    sent = _sent(model)
    assert len(sent) == 2 and "When is low tide?" in sent[0] and "What should I bring?" in sent[1]
    assert page.errors == [] and page.refused == []


def test_two_queued_messages_are_sent_in_the_order_they_were_typed(app, model, browser):
    gate = threading.Event()
    model.script(held(gate, say("One.")), say("Two."), say("Three."))
    page = _chat(browser, app)
    _type(page, "First question")
    page.page.locator(".chat-send.stopping").wait_for()
    _type(page, "Second question")
    page.page.locator(".chat-compose input[type=file]").set_input_files(
        files=[{"name": "notes.txt", "mimeType": "text/plain", "buffer": b"tide tables"}])
    page.page.locator(".chat-tray .att:not(.pa-shimmer)").wait_for()
    _type(page, "Third question")
    # What was attached goes with the queued message, its count in the row.
    assert _rows(page) == ["Second question", "Third question"]
    assert page.page.locator(".chat-queue-files").all_inner_texts() == ["Attachments: 1"]
    assert page.page.locator(".chat-tray").is_hidden()
    gate.set()
    page.page.get_by_text("Three.").wait_for()
    page.page.locator(".chat-send:not(.stopping)").wait_for()
    sent = _sent(model)
    assert [word in said for word, said in zip(("First", "Second", "Third"), sent)] == [True] * 3 and len(sent) == 3
    assert "tide tables" in sent[2] and "tide tables" not in sent[1]
    assert page.errors == [] and page.refused == []


def test_send_now_stops_the_reply_and_sends_that_message_with_the_rest_behind_it(app, model, browser):
    model.script(hang(), say("About the second."), say("About the first."))
    page = _chat(browser, app)
    _type(page, "A long plan")
    page.page.locator(".chat-send.stopping").wait_for()
    _type(page, "Queued first")
    _type(page, "Queued second")
    page.page.locator(".chat-queue-row", has_text="Queued second").get_by_role("button", name="Send now").click()
    page.page.get_by_text("About the first.").wait_for()
    page.page.locator(".chat-send:not(.stopping)").wait_for()
    sent = _sent(model)
    assert len(sent) == 3 and "Queued second" in sent[1] and "Queued first" in sent[2]
    # The stopped message stays in the thread, and the box stays as the person left it.
    assert page.page.locator(".chat-input:visible").input_value() == ""
    stored = [m for m in app.get("/api/chat/history").json()["messages"] if m["role"] == "user"]
    assert stored[0]["text"] == "A long plan" and stored[0].get("failed") == "stopped"
    assert page.errors == [] and page.refused == []


def test_removing_a_queued_message_puts_its_words_back_in_an_empty_box(app, model, browser):
    gate = threading.Event()
    model.script(held(gate, say("Done.")))
    page = _chat(browser, app)
    _type(page, "Start")
    page.page.locator(".chat-send.stopping").wait_for()
    _type(page, "Maybe later")
    page.page.locator(".chat-queue-row").get_by_role("button", name="Remove", exact=True).click()
    assert page.page.locator(".chat-input:visible").input_value() == "Maybe later"
    assert page.page.locator(".chat-queue").is_hidden()
    gate.set()
    page.page.get_by_text("Done.").wait_for()
    page.page.locator(".chat-send:not(.stopping)").wait_for()
    page.settle()
    assert len(model.asked()) == 1
    assert page.errors == [] and page.refused == []


def test_a_stopped_reply_leaves_the_queue_until_the_person_sends_again(app, model, browser):
    model.script(hang(), say("Here is the plan."), say("Here is the list."))
    page = _chat(browser, app)
    _type(page, "Plan a week of dinners")
    page.page.locator(".chat-send.stopping").wait_for()
    _type(page, "And a shopping list")
    page.page.locator(".chat-send.stopping").click()
    page.page.locator(".chat-send:not(.stopping)").wait_for()
    page.settle()
    assert len(model.asked()) == 1 and _rows(page) == ["And a shopping list"]
    row = page.page.locator(".chat-queue-row")
    assert row.get_by_role("button", name="Send now").is_visible() and row.get_by_role("button", name="Remove").is_visible()
    # The stopped words came back to the box: sent again, they go first and the queue follows their reply.
    box = page.page.locator(".chat-input:visible")
    assert box.input_value() == "Plan a week of dinners"
    box.press("Enter")
    page.page.get_by_text("Here is the list.").wait_for()
    sent = _sent(model)
    assert len(sent) == 3 and "Plan a week of dinners" in sent[1] and "And a shopping list" in sent[2]
    assert page.errors == [] and page.refused == []


def test_a_private_chat_opened_from_its_toggle_keeps_nothing_and_is_left_from_the_menu(app, model, browser, tmp_path):
    page = _chat(browser, app)
    model.script(say("Noted, and only here."))
    page.page.locator("#side-new").click()
    page.page.get_by_role("button", name="Start a temporary chat").click()
    page.page.locator(".chat-empty .chat-private:visible").wait_for()
    (opened,) = [chat for chat in app.get("/api/chats").json()["chats"] if chat.get("private")]
    box = page.page.locator(".chat-input:visible")
    # Words found nowhere else in a home (a port, a time or an id may hold any four digits).
    box.fill("My locker tag says QZXV-4512")
    box.press("Enter")
    page.page.get_by_text("Noted, and only here.").wait_for()

    page.page.locator(".chat-attach:visible").click()
    page.page.get_by_role("menuitemcheckbox", name="Temporary chat").click()
    page.page.locator(".chat-private:visible").wait_for(state="detached")
    assert page.page.locator(".chat-input:visible").count() == 1
    kept = [path for path in app.home.rglob("*") if path.is_file() and b"QZXV-4512" in path.read_bytes()]
    assert kept == [] and opened["id"] in {chat["id"] for chat in app.get("/api/chats").json()["chats"]}
    assert page.errors == []
