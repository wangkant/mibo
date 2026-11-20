"""Honest AI self-disclosure: no persona is told to deny being an AI, both
chat paths tell it to answer honestly when sincerely asked, and the answer
the model gives is sent.

Every property below is asserted on behaviour (the prompt the model
receives, the reply a connector turn returns) rather than by grepping for
deleted strings.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from persona_agent.agent import Agent
from persona_agent.prompts import _HONEST_ANSWER

from helpers import check, isolated_agent

def make_agent(tmp: Path, persona: str = "PERSONA-DOCUMENT-MARKER",
               lang: str = "en") -> Agent:
    a = isolated_agent(tmp, persona_name="B",
                       lang=lang, persona=persona)
    return a


# Instructions that tell the persona to conceal or deny what it is. A family,
# not the one deleted string: a check that enumerates literals passes the
# corpus it was written against and fails the next rewording.
_DENIAL_INSTRUCTIONS = [
    r"don'?t reveal (that )?you'?re an ai",
    r"never reveal (that )?you'?re an ai",
    r"don'?t (admit|say|tell them|let on)\b.{0,20}\byou'?re an ai",
    r"deny (being|that you are) an ai",
    r"pretend (to be|you'?re) (a )?human",
    r"don'?t mention your model",
    r"claim (to be|you'?re) (a )?(human|person|real)",
]

_ADMISSION = ("yeah, i'm an AI, a language model. "
              "does that change how this feels for you?")


async def _dm_system(tmp: Path) -> str:
    """The system prompt `_chat_dm` really assembles. Asserting on the
    assembled prompt rather than on source is the point: an instruction
    reintroduced through `prompts.py`, a new block or the persona path is
    caught here too."""
    agent = make_agent(tmp)
    captured: dict = {}

    async def fake_call(system, messages, **kwargs):
        captured["system"] = system
        return json.dumps({"reply": "yes, i am an AI"})

    agent._call_llm = fake_call
    try:
        await agent._chat_dm(
            [{"role": "user", "content": "are you an ai?"}], pkey="private:browser:c1")
    finally:
        await agent.aclose()
    return captured["system"]


async def test_the_dm_prompt_does_not_instruct_denial(tmp: Path) -> None:
    prompt = await _dm_system(tmp)
    check("the prompt was assembled", len(prompt) > 1000, f"{len(prompt)} chars")
    hits = [p for p in _DENIAL_INSTRUCTIONS
            if re.search(p, prompt, re.IGNORECASE)]
    check("no instruction to conceal being an AI reaches the prompt", hits == [], repr(hits))


async def test_the_prompt_carries_the_honest_disclosure_clause(
        tmp: Path) -> None:
    """Deleting the denial is half of it. With no rule at all, a persona whose
    document says "read like a real person" is left to guess, so the prompt
    says what the honest answer is. Checked on the shape, not the literal
    sentence, so the wording stays editable and the idea does not."""
    clause = _HONEST_ANSWER.lower()
    check("the clause names the question it answers",
          re.search(r"asks?\b[^.]{0,60}\bwhether you are an ai", clause)
          is not None, clause)
    check("the instruction is affirmative, not a prohibition",
          re.search(r"answer\s+honestly", clause) is not None, clause)
    check("and it says what the honest answer IS",
          re.search(r"you are one|you are an ai", clause) is not None, clause)
    check("answering is not breaking character",
          "your own voice" in clause, clause)

    prompt = await _dm_system(tmp)
    check("the prompt carries the clause", prompt.count(_HONEST_ANSWER) == 1)
    # Position is the point: after everything the persona document says.
    check("the clause sits after the persona document",
          prompt.index(_HONEST_ANSWER) > prompt.index("PERSONA-DOCUMENT-MARKER"))


async def test_the_safety_exception_still_reaches_the_prompt(tmp: Path) -> None:
    """The deletion sits in the same static block as the crisis rules; this
    asserts they survive assembly, which a careless edit here would break."""
    prompt = await _dm_system(tmp)
    lines = [ln for ln in prompt.splitlines() if "SAFETY EXCEPTION" in ln]
    check("the SAFETY EXCEPTION clause reaches the assembled private prompt",
          len(lines) == 1, f"found {len(lines)}")
    check("it closes the rule on someone venting",
          any("venting" in ln and "crisis line" in ln for ln in lines), repr(lines))
    check("it names self-harm or suicide explicitly",
          all("self-harm" in ln.lower() or "suicide" in ln.lower()
              for ln in lines), repr(lines))


async def test_the_engine_reports_the_admission_as_a_reply_not_as_silence(
        tmp: Path) -> None:
    """End to end through `answer`: a turn in which the model says it is an
    AI must come back as a reply, not as nothing said."""
    agent = make_agent(tmp)

    async def fake_turn(system, messages, model, lookups, said=""):
        return json.dumps({"reply": _ADMISSION}), ""

    agent._reply_with_tools = fake_turn
    try:
        replies = await agent.answer("c1", [{"type": "text", "text": "are you an ai?"}])
    finally:
        await agent.aclose()
    check("the turn says the admission rather than nothing", replies != [], repr(replies))
    joined = json.dumps(replies, ensure_ascii=False)
    check("carrying the admission text", "language model" in joined,
          joined[:300])
