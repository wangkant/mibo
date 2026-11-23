"""An act in the app's browser waits for the person's own message typed in the chat (panels/browser.py,
cardwait.py): a plain yes runs it, anything else does not, and only under its own id. A question a turn left
waiting is answered by their next message beside the page, read the same way, and kept for its act; a yes earlier
in the turn reaches it only when it is of the kind described (cardwait.reaches), and an upload is always asked."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from mibo import acting
from mibo.cardwait import asking
from mibo.panels.browser import Operating
from mibo.web import operate


class Pane:
    def __init__(self):
        self.op, self.kept = None, []

    def front(self, tab):
        pass

    def operate(self, task, go_on=False):
        self.op = {"held": ""}

    def op_card(self, card, text):
        pass

    def op_answered(self, state, text):
        pass

    def op_kept(self, yes):
        self.kept.append(yes)


class Page:
    async def hold_ring(self, node):
        pass


class Chat:
    """The workspace's side of a question (workspace.question_said and answer_said): what the chat was given."""

    def __init__(self, home):
        self.home, self.said, self.answers = home, [], []

    def question_said(self, conversation, entry):
        self.said.append((conversation, entry))

    def answer_said(self, ident, state, line="", pending=False):
        self.answers.append((ident, state, line))
        return len(self.answers) if line else None


def operating(tmp_path) -> Operating:
    home = tmp_path / "home"
    (home / "runtime" / "desktop").mkdir(parents=True)
    (home / "runtime" / "desktop" / "chat-doing.json").write_text(
        json.dumps({"conversation": "main", "turn": "t1"}), encoding="utf-8")
    window = SimpleNamespace(pane=Pane(), attended=lambda: True, show=lambda: None,
                             pick_files=lambda many: [str(tmp_path / "photo.jpg")])
    run = Operating(window, tmp_path, Chat(home))
    run._page = lambda tab: Page()
    return run


def card_of(kind: str, ident: str) -> dict:
    return {"id": ident, "kind": kind, "site": "creator.example.com", "to": "作品《周末》", "text": "",
            "button": "好的", "skippable": False, "act": ("card", kind, "creator.example.com", "好的", "", "")}


async def answered(run: Operating, card: dict, *typed: tuple) -> dict | None:
    """Asks `card` and types each (id, text) in turn once it waits."""
    task = asyncio.ensure_future(run.ask(card, 1))
    while run.card is None and not task.done():
        await asyncio.sleep(0.01)
    said = [await asking(run.workspace).answer(ident, text) for ident, text in typed]
    return {"answer": await task, "said": said}


async def test_a_typed_yes_runs_the_act_and_only_under_its_own_id(tmp_path):
    run = operating(tmp_path)
    got = await answered(run, card_of("comment", "c1"), ("c0", "确定"), ("c1", "好，发吧"))
    assert got["said"] == [{"ok": False, "yes": False}, {"ok": True, "yes": False, "seq": 1}]
    assert got["answer"]["yes"] is False
    got = await answered(run, card_of("comment", "c2"), ("c2", "确定"))
    assert got["answer"]["yes"] is True
    # Each question is said in the chat in the app's words for the act, and each answer is the person's words.
    chat = run.workspace
    assert [(c, e["ask"]["id"], e["ask"]["tier"]) for c, e in chat.said] == [("main", "c1", "plain"),
                                                                            ("main", "c2", "plain")]
    assert "作品《周末》" in chat.said[0][1]["text"] and "好的" not in chat.said[0][1]["text"]
    assert chat.answers == [("c1", "no", "好，发吧"), ("c2", "yes", "确定")]


async def test_one_yes_carries_ordinary_acts_and_never_an_upload(tmp_path):
    run = operating(tmp_path)
    assert (await answered(run, card_of("comment", "c1"), ("c1", "你做")))["answer"]["yes"] is True
    # Another ordinary act of the turn goes with no question.
    assert await run.ask(card_of("submit", "c2"), 1) == {"yes": True}
    # An upload is asked on its own, and its yes opens the Open dialog: the chosen files are the answer.
    got = await answered(run, card_of("upload", "c3"), ("c3", "ok"))
    assert got["answer"] == {"yes": True, "never": False, "files": [str(tmp_path / "photo.jpg")]}


@pytest.mark.parametrize("kind", sorted(acting.HARD))
async def test_a_yes_to_an_ordinary_act_never_reaches_paying_deleting_or_an_account(kind, tmp_path, monkeypatch):
    monkeypatch.setattr(operate, "CARD_S", 0.3)
    run = operating(tmp_path)
    assert (await answered(run, card_of("comment", "c1"), ("c1", "确定")))["answer"]["yes"] is True
    left = await run.ask(card_of(kind, f"c-{kind}"), 1)
    assert "waiting" in left


async def test_a_question_left_waiting_is_answered_by_the_next_words_beside_the_page(tmp_path, monkeypatch):
    monkeypatch.setattr(operate, "CARD_S", 0.3)
    run = operating(tmp_path)
    card = card_of("comment", "c1")
    assert "waiting" in await run.ask(card, 1)
    assert run.left["id"] == "c1"
    assert run.keep(False)
    assert run.left is None and run.kept == {card["act"]: {"yes": False}} and run.window.pane.kept == [False]
    assert not run.keep(True)
    # The question stays in the chat, left for the next words; their message is the answer, marked on it.
    assert run.workspace.answers == [("c1", "left", ""), ("c1", "no", "")]
