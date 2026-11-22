"""What the character itself said in earlier chats is on the record like the person's words: asked about it in a
new chat, past-chat search finds its own line, and the reply request carries that line marked as the character's,
told apart from the person's lines the same way every time, whether the model searched itself or the app brought
the lines for a model that does not call tools."""
from __future__ import annotations

import json
import re

from harness.model import call, say
from harness.page import measured
from harness.turn import run_turn
from mibo import pastchats

# Two exchanges in the main chat: the person's line, then the character's own.
TALK = [("How was your weekend?", "I went to the market again and the self-checkout froze on me twice."),
        ("Sleep well?", "Same dream again: I was flying over a city at night, all lights below.")]
# The window of a small local model.
SMALL = 16384


def marks(text: str) -> dict:
    """{line: the two words written just before it} for each line of TALK quoted in `text`."""
    out = {}
    for pair in TALK:
        for line in pair:
            at = text.find(json.dumps(line, ensure_ascii=False))
            if at >= 0:
                out[line] = tuple(re.findall(r"\S+", text[:at])[-2:])
    return out


def told_apart(text: str) -> None:
    """The character's lines are all quoted with one mark, the person's with another."""
    found = marks(text)
    own = {found[mine] for _theirs, mine in TALK if mine in found}
    theirs = {found[t] for t, _mine in TALK if t in found}
    assert len(own) == 1 and len(theirs) <= 1 and not own & theirs, found


def talk(app) -> None:
    for theirs, mine in TALK:
        assert run_turn(app, theirs, say(mine)).status == 200


def test_a_question_about_its_own_earlier_words_finds_them_through_past_chat_search_marked_as_its_own(app):
    # A small window: past-chat search is still among the tools the request carries, not left behind find_tools.
    measured(app, context=SMALL)
    talk(app)
    chat = app.post("/api/chats").json()["id"]
    done = run_turn(app, "What keeps going wrong for you at the market?",
                    call(pastchats.NAME, query="market self-checkout"), say("The self-checkout."), conversation=chat)
    assert pastchats.NAME in [t["function"]["name"] for t in done.asked()[0]["tools"]]
    found = done.result_of(done.calls()[0]["id"])
    assert json.dumps(TALK[0][1], ensure_ascii=False) in found, found
    told_apart(found)


def test_for_a_model_that_does_not_call_tools_the_turn_brings_its_own_earlier_words_marked_as_its_own(app):
    talk(app)
    chat = app.post("/api/chats").json()["id"]
    done = run_turn(app, "What did you say about your dream?", say("Flying over a city."), conversation=chat)
    asked = done.asked()[0]
    turn = asked["messages"][-1]["content"]
    assert json.dumps(TALK[1][1], ensure_ascii=False) in turn, turn
    told_apart(turn)
