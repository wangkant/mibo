"""Whether to look by picture at all, and the person's "always" for it.

Structure first, every time. A window goes to sight only when its structure
gives almost nothing (fewer than FEW named controls, or one nameless drawn area
covering most of it). Then what the person's model was measured to do decides
(profile.reach): a model that points works the window by picture, one that
takes pictures but did not point looks and tells the person where to click,
and for one that takes no pictures the window goes back to the person with a
sentence on which kind of model would do it (words.NO_PICTURES).

The first picture of a task waits for the person's answer on a card
(words.ASK: this once, always or no); "always" is kept here for the model
service it was given for, listed in Settings and taken back there.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import words

FEW = 3
DRAWN = 0.5
SWITCH_FILE = "see.json"


class Switch:
    """"Always" on the picture card: pictures of such windows go to this model service without a card."""

    def __init__(self, folder: Path):
        self.path = Path(folder) / SWITCH_FILE

    def on(self, service: str) -> bool:
        try:
            return json.loads(self.path.read_text(encoding="utf-8")).get("always") == service
        except (OSError, ValueError):
            return False

    def set(self, service: str) -> None:
        """Always for `service`; "" takes it back."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"always": service}), encoding="utf-8")

    @staticmethod
    def sentence(lang: str, who: str, service: str) -> str:
        return words.say(words.SWITCH, lang, who=who, service=service)


def decide(*, named: int, drawn: float, eyes: str) -> tuple[str, str]:
    """("structure" | "sight" | "look" | "handback", why). `named` is how many controls with a name the structure
    shows, `drawn` the share of the window one nameless area covers (a canvas, a game, a remote screen), `eyes`
    what the person's model may do with a picture (profile.reach)."""
    if named >= FEW and drawn < DRAWN:
        return "structure", f"the structure names {named} controls"
    why = f"one nameless area covers {drawn:.0%} of it" if drawn >= DRAWN else f"the structure names only {named} controls"
    if eyes == "act":
        return "sight", why
    if eyes == "look":
        return "look", f"{why}; the model takes pictures but did not point in the self-test"
    return "handback", f"{why}, and the model takes no pictures"
