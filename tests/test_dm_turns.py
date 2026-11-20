"""A turn of the chat: how long it may take, what a draft with nothing to say
becomes, what happens to words a failed turn left, and what the trim keeps.

Run from the repo root:

    python -m pytest tests/test_dm_turns.py
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from persona_agent import chatlangs
from persona_agent.agent import Agent
from persona_agent.dm import chat_key

from helpers import check, make_agent

CHAT = "c1"
USER, PKEY = chat_key(CHAT)
EXCUSES = chatlangs.SPECS["en"].failure_excuses


def _said(turns) -> list:
    """Turns as role and content; their times and numbers are checked in
    tests/test_memory_recent.py."""
    return [{k: v for k, v in dict(m).items() if k in ("role", "content")}
            for m in turns or []]


def _user(*lines: str) -> dict:
    return {"role": "user", "content": "\n".join(lines)}


def _bot(text: str) -> dict:
    return {"role": "assistant", "content": text}


def _text(words: str) -> list:
    return [{"type": "text", "text": words}]


def _texts(items) -> list:
    return [item["text"] for item in items]


# ---- the turn's time ----------------------------------------------------------

async def test_a_turn_over_its_budget_ends_with_the_failure_line(tmp: Path, monkeypatch) -> None:
    """A turn's model work is bounded as a turn, however many calls it makes."""
    agent = make_agent(tmp)
    agent.llm_timeout_s = 0.02
    # No time for tools on top: the answer's own time is the whole budget here.
    monkeypatch.setattr("persona_agent.search._TOOLS_WITHIN_S", 0.0)
    cancelled: list = []
    answers = False

    async def chat(history, pkey="", **kwargs):
        if answers:
            return "there you are", ""
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(history[-1]["content"])

    agent._chat_dm = chat
    said = await asyncio.wait_for(agent.answer(CHAT, _text("you there?")), 5)
    check("the person is told, with the usual line, marked as said in place of an answer",
          len(said) == 1 and said[0]["text"] in EXCUSES and said[0].get("reason") == "excuse", repr(said))
    said = await asyncio.wait_for(agent.answer(CHAT, _text("hello??")), 5)
    await asyncio.sleep(0)
    check("the next message's turn is written from the words the first one left",
          cancelled == ["you there?", "you there?\nhello??"], repr(cancelled))
    check("that failure is told too", len(said) == 1 and said[0]["text"] in EXCUSES, repr(said))
    check("the words wait for a turn that answers",
          agent._dm_unanswered.get(USER) == ["you there?", "hello??"], repr(agent._dm_unanswered))

    answers = True
    said = await asyncio.wait_for(agent.answer(CHAT, _text("ok?")), 5)
    check("which the next message gets",
          _texts(said) == ["there you are"] and _said(agent.dm_history[USER]) == [
              _user("you there?", "hello??", "ok?"), _bot("there you are")],
          repr(agent.dm_history.get(USER)))
    check("no turn is left under way", not agent.turn_locks[PKEY].locked())


# ---- a draft with nothing to say ------------------------------------------------

def _scripted_model(agent: Agent, drafts: list) -> list:
    """The real `_chat_dm` over a model that answers `drafts` in turn; returns
    the system prompt of each call."""
    systems: list = []

    def draft(system):
        systems.append(system)
        answer = drafts[min(len(systems), len(drafts)) - 1]
        if isinstance(answer, BaseException):
            raise answer
        return json.dumps({"reply": answer, "mem": []})

    async def with_tools(system, messages, model, lookups, said=""):
        return draft(system), ""

    async def call(system, messages, **kwargs):
        return draft(system)

    agent._reply_with_tools = with_tools
    agent._call_llm = call
    return systems


async def test_a_draft_of_pass_is_drafted_again(tmp: Path) -> None:
    """The chat has no PASS, yet a bare PASS ended the turn in silence."""
    agent = make_agent(tmp)
    systems = _scripted_model(agent, ["PASS", "hey, sure"])
    said = await agent.answer(CHAT, _text("can you come?"))
    check("the second draft is said", _texts(said) == ["hey, sure"], repr(said))
    check("one extra call, which says why",
          len(systems) == 2 and "PASS" in systems[1][len(systems[0]):],
          repr(systems[1][len(systems[0]):]))


async def test_what_was_said_during_an_outage_waits_whole(tmp: Path) -> None:
    """A chat that kept failing kept only its last three unanswered lines."""
    agent = make_agent(tmp)
    lines = [f"line {i} of what happened" for i in range(5)]
    systems = _scripted_model(agent, [RuntimeError("provider down")])
    told = [await agent.answer(CHAT, _text(line)) for line in lines]
    seen: list = []

    async def chat(history, pkey="", **kwargs):
        seen.append(_said(history))
        return "sorry, I'm back", ""

    agent._chat_dm = chat
    said = await agent.answer(CHAT, _text("hello?"))
    check("five failed calls, each told, then one reply", len(systems) == 5
          and all(len(t) == 1 and t[0].get("reason") == "excuse" for t in told)
          and _texts(said) == ["sorry, I'm back"], repr((told, said)))
    check("the reply is written from every line",
          seen and seen[0][-1] == _user(*lines, "hello?"), repr(seen))


# ---- the trim and consolidation ----------------------------------------------

async def test_the_trim_hands_its_unconsolidated_turns_to_the_spill(tmp: Path) -> None:
    agent = make_agent(tmp)

    async def chat(history, pkey="", **kwargs):
        return "noted", ""

    agent._chat_dm = chat
    agent._wake(PKEY)
    agent.dm_history[USER] = [
        {"role": "user" if i % 2 else "assistant", "content": f"turn {i}",
         "t": 1e9 + i, "seq": i} for i in range(1, 60)]
    agent.window_seq[PKEY] = 59
    agent.folded_upto[PKEY] = 10
    await agent.answer(CHAT, _text("one more"))
    kept = agent.dm_history[USER]
    check("the trim is unchanged: past 60 turns, 40 are kept", len(kept) == 40
          and kept[-1]["content"] == "noted", repr(len(kept)))
    check("exactly the dropped turns not yet consolidated wait in the spill",
          [t["seq"] for t in agent._dm_spill[USER]] == list(range(11, 22)),
          repr([t["seq"] for t in agent._dm_spill.get(USER, [])]))
    await agent.answer(CHAT, _text("and another"))
    check("no trim, nothing more spilled", len(agent.dm_history[USER]) == 42
          and len(agent._dm_spill[USER]) == 11)
