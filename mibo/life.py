"""The character's life as its home page shows it: what it is doing now, what
it has gathered, and its days.

Everything here is read from what already exists (the library of its walks,
what it knows of its person in person.json), so the page can show it while
the service is stopped too. Nothing here ever goes down or punishes absence.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from . import memstore, person, players
from .library import DISMISSED, KEPT, KINDS, Item, Library

# Replaced in tests: every "now" here comes from this.
clock = time.time

# How long "back from a walk" stays on the home after one that brought something.
BACK_S = 600
# What it kept for the owner and was never asked about stays in the days only after this.
TELL_DAYS = 7
# What the page's frame-src lists: the official players (players.py), on their paths where it can.
PLAYER_HOSTS = players.frame_sources()
STATES = ("home", "answering", "out", "asleep", "back", "off")
_PICTURE = re.compile(r"/api/library/picture/[0-9a-f]{16}")
_TEXT_MAX = 300


# ------------------------------------------------------------------ sources --

@dataclass
class Sources:
    """What the days are read from: the character's own state, or the files
    it keeps when it could not be built."""
    runtime: Path
    # The facts it keeps about its person (person.json).
    facts: list = field(default_factory=list)

    @property
    def library(self) -> Library:
        return Library(self.runtime)

    @classmethod
    def of_agent(cls, agent, runtime: Path) -> Sources:
        return cls(Path(runtime), agent.person_store.facts())

    @classmethod
    def from_files(cls, runtime: Path) -> Sources:
        """The files alone."""
        runtime = Path(runtime)
        try:
            facts = person.Person(runtime / person.FILE).facts()
        except (OSError, ValueError, memstore.MemoryFileDamaged):
            facts = []
        return cls(runtime, facts)


# -------------------------------------------------------------------- facts --

def _note_time(row: dict) -> int:
    return int(float(row.get("born") or row.get("at") or 0))


def owner_notes(src: Sources) -> list[dict]:
    """What it knows of its person: the facts in use."""
    return list(src.facts)


# ---------------------------------------------------------------------- now --

def asleep_until(now: float, offset_hours: float) -> int | None:
    """The waking time when `now` is inside the sleep hours on the persona's clock, else None."""
    from .textproc import SLEEP_HOUR_END, SLEEP_HOUR_START
    local = datetime.fromtimestamp(now, timezone(timedelta(hours=offset_hours)))
    start, end, hour = SLEEP_HOUR_START, SLEEP_HOUR_END, local.hour
    inside = start <= hour < end if start <= end else (hour >= start or hour < end)
    if not inside:
        return None
    wake = local.replace(hour=end, minute=0, second=0, microsecond=0)
    if wake <= local:
        wake += timedelta(days=1)
    return int(wake.timestamp())


def now_state(library: Library, now: float, *, answering: bool = False,
              sleep_until: int | None = None) -> dict:
    outing = library.outing()
    if outing.state == "out":
        return {"state": "out", "where": outing.site, "since": int(outing.since), "until": None, "count": 0}
    if answering:
        return {"state": "answering", "where": "", "since": int(now), "until": None, "count": 0}
    if sleep_until:
        return {"state": "asleep", "where": "", "since": int(now), "until": int(sleep_until), "count": 0}
    if outing.last_count > 0 and 0 <= now - outing.last_end < BACK_S:
        return {"state": "back", "where": "", "since": int(outing.last_end),
                "until": int(outing.last_end + BACK_S), "count": int(outing.last_count)}
    return {"state": "home", "where": "", "since": int(outing.last_end or 0), "until": None, "count": 0}


def home(src: Sources, *, answering: bool = False, sleep_until=None,
         now: float | None = None) -> dict:
    """What the character is doing now: out, answering, asleep, just back, or at home."""
    now = clock() if now is None else now
    return {"now": now_state(src.library, now, answering=answering, sleep_until=sleep_until)}


# --------------------------------------------------------------------- days --

def _clip(text, limit: int = _TEXT_MAX) -> str:
    value = " ".join(str(text or "").split())
    return value if len(value) <= limit else value[:limit - 1] + "…"


def mark(library: Library, ident: str, action: str, kept: bool = True) -> Item | None:
    """The owner's choice about one thing it saw: keep (or un-keep), or not for me."""
    item = library.get(ident)
    if item is None:
        return None
    if action == "keep":
        return library.change(ident, state=KEPT if kept else "")
    if action == "dismiss":
        return library.change(ident, state=DISMISSED)
    if action == "told":
        return library.change(ident, told=True)
    return None


# -------------------------------------------------------------------- cards --

def _https_player(url: str) -> str:
    try:
        parts = urlsplit(url)
    except ValueError:
        return ""
    return url if parts.scheme == "https" and parts.hostname in {host for host, _ in players.PLAYERS} else ""


def _web(url: str) -> str:
    try:
        return url if urlsplit(url).scheme in ("http", "https") else ""
    except ValueError:
        return ""


def clean_card(card) -> dict | None:
    """A card a chat message may carry, with only what the page may draw:
    a player only from a listed host, a picture only from the library."""
    if not isinstance(card, dict):
        return None
    url = _web(str(card.get("url") or "")[:2000])
    if not url:
        return None
    length = card.get("length")
    picture = str(card.get("picture") or "")
    return {"kind": card.get("kind") if card.get("kind") in KINDS else "page",
            "title": _clip(card.get("title"), 300), "site": _clip(card.get("site"), 80),
            "author": _clip(card.get("author"), 120),
            "length": int(length) if isinstance(length, (int, float)) and not isinstance(length, bool)
            and 0 <= length < 10 ** 7 else None,
            "picture": picture if _PICTURE.fullmatch(picture) else "",
            "embed": _https_player(str(card.get("embed") or "")[:2000]), "url": url,
            "excerpt": _clip(card.get("excerpt"), 400), "readable": card.get("readable") is True}


def said(item: Item) -> dict:
    """The page chat message that brings one thing it saw to the owner: its own
    sentence, else the title, and the card with what the chat reacts to it by."""
    card = clean_card(item.card())
    if card:
        card.update(id=item.id, source=item.source, liked=item.state == KEPT,
                    at=datetime.fromtimestamp(item.seen_at).astimezone().isoformat(timespec="seconds"))
    text = " ".join(item.why.split()) or _clip(item.title, 80) or item.url
    return {"role": "assistant", "text": text, **({"card": card} if card else {})}
