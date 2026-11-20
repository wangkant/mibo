"""The style guide asks for text that reads easily."""
from __future__ import annotations


def test_the_style_guide_asks_for_the_answer_first_in_everyday_words():
    from mibo import prompts

    # One to one: the answer first in everyday words, at the length asked for.
    guide = prompts.dm_style_guide(prompts.PersonaStyle())
    assert "The answer comes first, in everyday words" in guide
    assert guide.index("[LANGUAGE]") < guide.index("show the move, not the wording") < guide.index("[FORMAT")
