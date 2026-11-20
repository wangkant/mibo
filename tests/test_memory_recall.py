"""What a reply recalls: the running summary, facts and events within one
budget, ranked by relevance, recency, importance, use and time words; what
the gate sees; dated lines and gaps; and the use count after a send.

No model is called: prompts are built and read."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from persona_agent.agent import Agent

from helpers import check, isolated_agent

DAY = 86400.0
G = "telegram:room1"


@pytest.fixture(autouse=True)
def _fixed_zone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PERSONA_TZ_OFFSET_HOURS", "8")


def make_agent(tmp: Path, *, lang: str = "en", **settings) -> Agent:
    return isolated_agent(tmp, persona_name="Luna", lang=lang, **settings)


# ---------------------------------------------------------------------------
# The budget and the caps
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# The ranking
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# The prompts
# ---------------------------------------------------------------------------

def test_a_dm_sends_only_role_and_content_and_notes_the_pause(tmp: Path) -> None:
    a = make_agent(tmp)
    then = time.time() - 2 * DAY
    history = [{"role": "user", "content": "see you", "t": then - 60, "seq": 1},
               {"role": "assistant", "content": "bye", "t": then, "seq": 2},
               {"role": "user", "content": "back again", "t": time.time(), "seq": 3}]
    prompt = a._build_dm_prompt(history, pkey="private:telegram:7")
    check("turns carry role and content only",
          all(set(m) == {"role", "content"} for m in prompt.messages), repr(prompt.messages))
    check("the pause goes into the turn context",
          "The message before this one came 2 days earlier." in prompt.turn_context)
    check("never into the turns", not any("earlier" in m["content"] for m in prompt.messages))
    history[-1]["t"] = then + 600
    check("a short pause is not noted", "[Pause]" not in a._build_dm_prompt(
        history, pkey="private:telegram:7").turn_context)


# ---------------------------------------------------------------------------
# Use counting
# ---------------------------------------------------------------------------
