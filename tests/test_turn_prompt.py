"""What the model is told on one turn: a picture it cannot see."""
from __future__ import annotations

from pathlib import Path

from helpers import check, isolated_agent


def _agent(tmp: Path):
    return isolated_agent(tmp, persona_name="Luna", admin_name="Kay")


def test_a_private_picture_it_cannot_see_is_named_as_unseen(tmp: Path) -> None:
    a = _agent(tmp)
    blind = a._build_dm_prompt([{"role": "user", "content": "[image]"}],
                               pkey="private:browser:c1")
    notes = [line for line in blind.turn_context.splitlines()
             if "**can't see**" in line]
    check("a bare picture gets the can't-see note", len(notes) == 1,
          blind.turn_context)
    check("...which offers no PASS, the chat has none",
          notes and "PASS" not in notes[0], repr(notes))
    seen = a._build_dm_prompt([{"role": "user", "content": "[image: a cat on a sofa]"}],
                              pkey="private:browser:c1")
    check("a described picture does not",
          "**can't see**" not in seen.turn_context, seen.turn_context)
    check("the guide tells a picture it reads from one it cannot see",
          "a bare [image]" in blind.system, blind.system[:200])
