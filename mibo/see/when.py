"""Whether to look by picture at all, the person's switch for it, and the one notice of where pictures go.

Structure first, every time. A window goes to sight only when its structure
gives almost nothing (fewer than FEW named controls, or one nameless drawn area
covering most of it). Then what the person's model was measured to do decides
(profile.reach): a model that points works the window by picture, one that
takes pictures but did not point looks and tells the person where to click,
and for one that takes no pictures the window goes back to the person with a
sentence on which kind of model would do it (words.NO_PICTURES).

Page text, pictures of windows and file text go to the model service the person
chose, as every word of the chat does. They are told so once, in the chooser of
a model service (setup/model.js), and once more only when the service's host
changes (`told`, `tell`); nothing asks per action. Pictures go with no question
unless the person turned the switch off in Settings (each task's first picture
is asked about then), and a sensitive window asks every time (desk/panel.py).
"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

from . import words

FEW = 3
DRAWN = 0.5
SWITCH_FILE = "see.json"


def _read(folder: Path) -> dict | None:
    """see.json's object; {} when there is none, None when it cannot be read."""
    try:
        data = json.loads((Path(folder) / SWITCH_FILE).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write(folder: Path, data: dict) -> None:
    path = Path(folder) / SWITCH_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


class Switch:
    """Pictures of windows only a picture can work go to the model service with no question: on until the person
    turns it off in Settings, after which each task's first picture is asked about in the chat."""

    def __init__(self, folder: Path):
        self.folder = Path(folder)

    def on(self) -> bool:
        data = _read(self.folder)
        # A file from before the notice kept "always": "" for off; one that cannot be read is off.
        return data is not None and not data.get("off") and data.get("always") != ""

    def set(self, on: bool) -> None:
        kept = {key: value for key, value in (_read(self.folder) or {}).items() if key != "always"}
        _write(self.folder, {**kept, "off": not on})

    @staticmethod
    def sentence(lang: str, who: str, service: str) -> str:
        return words.say(words.SWITCH, lang, who=who, service=service)


def host_of(values: dict) -> str:
    """The host of the model service the home's settings name."""
    from ..config_env import DEFAULT_LLM_BASE_URL
    return urlsplit(values.get("LLM_BASE_URL") or DEFAULT_LLM_BASE_URL).hostname or ""


def told(folder: Path) -> str:
    """The model service's host the person was last told about; "" before the first."""
    return str((_read(folder) or {}).get("told") or "")


def tell(folder: Path, host: str) -> None:
    """The person was told that page text, pictures and file text go to `host`."""
    if host and host != told(folder):
        _write(folder, {**(_read(folder) or {}), "told": host})


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
