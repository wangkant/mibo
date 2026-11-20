"""Tests for decision.py: what becomes of a draft."""
from __future__ import annotations

from pathlib import Path

import pytest

from persona_agent import decision

from helpers import check, isolated_agent

#: Only the bare word is the sentinel; a reply that starts with it is a reply.
PASS_ROWS = [("PASS", True), ("pass.", True), (" PASS ", True), ("**PASS**", True),
             ("Pass auf dich auf", False), ("pass lol, my voice is cursed", False),
             ("Pass, not for me", False), ("pass the salt", False)]


@pytest.mark.parametrize("raw,is_pass", PASS_ROWS)
def test_only_the_bare_word_pass_is_a_pass(tmp: Path, raw: str, is_pass: bool) -> None:
    agent = isolated_agent(tmp)
    final = agent._final_reply(raw, log_ctx="test")
    check(f"{raw!r} is {'a PASS' if is_pass else 'sent'}",
          final.verdict == (decision.PASS if is_pass else decision.SEND), repr(final))
