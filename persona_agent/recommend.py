"""The one thing the character brings next, chosen by its own model.

When a recommendation is due (the pet's card has none waiting, or the share
step brings one into the main chat), `Chooser` takes the ranking's best
CANDIDATES unseen things and asks the person's model which one is for them
now, with one sentence in the character's voice on why. One small call per
thing shown: the choice is kept until a surface shows it or it is STALE_S old,
both surfaces draw from it, and nothing is asked while quiet, while a choice
waits or with nothing to choose from. Without a model, or on an answer it
cannot use, the ranking's top thing goes with its own words and no line.
The calls are counted with the character's others (`profile.count`, "pick").
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Optional

from . import drafting, life, profile, quiet
from .library import DISMISSED, Item
from .roam import fence_pages, knowing
from .textproc import _UNTRUSTED_INPUT_RULES, _fence_user_data, salvage_json_object, strip_json_fences

logger = logging.getLogger("personagent.recommend")

CANDIDATES = 6
STALE_S = 3 * 3600
# After a look found nothing to choose from, the next waits this long, however often the surfaces ask.
EMPTY_S = 30
MAX_TOKENS = 240
SUMMARY_MAX = 300
# The line's length in characters: a sentence of CJK carries about twice what one of Latin letters does.
LINE_MAX, LINE_MAX_CJK = 160, 80
CJK = ("zh", "zh-TW", "ja", "ko")

_SYSTEM = """You are {name}. This is your persona:
<<<
{persona}
>>>
You live on your person's computer desktop and now and then bring them one thing you found on your walks. Below are a few you found; pick the one that is most for them right now, and tell them in one sentence why this one is for them.

- Answer JSON only: {{"id": "<the id of the thing you picked>", "line": "<your sentence>"}}
- The line in {language}, in your own voice as the persona describes it, at most {limit} characters.
- Concrete: what in this thing meets what they like or what they are doing now. Not a summary of it, no generic praise.
- About them, say only what your notes, their topics and their situation below tell you. When those say nothing that fits, say what in the thing itself is worth their time, and never make up an interest, a habit or something they are busy with.
- Plain text only: no links, no markdown, no emoji, no quotation marks, no name tag.
- Never say how you know what they like or do.

""" + _UNTRUSTED_INPUT_RULES


def limit(lang: str) -> int:
    return LINE_MAX_CJK if lang in CJK else LINE_MAX


def candidates(library, events: list, now: float, topics: list[str], lang: str, here: set[str]) -> list:
    """The ranking's best CANDIDATES unseen things from the last week, not told and not in the main chat
    already, as (shaped, item)."""
    from .panels import feed
    rows = []
    for shaped, item in feed.ranked(library, events, now, topics, seed=int(now * 1000), lang=lang):
        if shaped["seen"] or len(rows) >= CANDIDATES:
            break
        if item.id not in here and not item.told and item.seen_at >= now - life.TELL_DAYS * 86400:
            rows.append((shaped, item))
    return rows


def prompt(runtime, name: str, persona: str, lang: str, topics: list[str], rows: list, now: float) -> tuple[str, str]:
    system = _SYSTEM.format(name=name, persona=persona[:1500], limit=limit(lang),
                            language=drafting.LANGUAGE_NAMES.get(lang, "English"))
    things = "\n\n".join(
        f"id: {shaped['id']}\ntitle: {shaped['title']}\nsite: {shaped['site']}\nkind: {shaped['kind']}"
        + (f"\nsummary: {' '.join(shaped['text'].split())[:SUMMARY_MAX]}" if shaped["text"] else "")
        for shaped, _ in rows)
    user = "\n\n".join([
        knowing(runtime, now),
        "Topics they picked:\n" + (_fence_user_data(", ".join(topics)) if topics else "(none)"),
        # Titles and summaries are the pages' own words.
        "The things:\n" + fence_pages(things)])
    return system, user


_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_URL = re.compile(r"(?:https?://|www\.)\S+", re.I)
_MARKUP = re.compile(r"[*_`#>|~<>\[\]]")


def clean_line(text, lang: str) -> str:
    """The model's sentence as plain text on one line, clipped to the language's limit."""
    line = _MARKUP.sub("", _URL.sub("", _LINK.sub(r"\1", str(text or ""))))
    line = " ".join("".join(c for c in line if c.isprintable() or c.isspace()).split())
    line = line.strip(" \"'“”‘’「」『』«»")
    most = limit(lang)
    return line if len(line) <= most else line[:most - 1].rstrip() + "…"


def parse(answer: str, rows: list, lang: str) -> Optional[tuple[dict, Item, str]]:
    """The candidate the answer named, with its line; None when the answer is not that."""
    value = salvage_json_object(strip_json_fences(str(answer or "")))
    if not isinstance(value, dict):
        return None
    chosen = next((row for row in rows if row[0]["id"] == str(value.get("id") or "")), None)
    line = clean_line(value.get("line"), lang) if isinstance(value.get("line"), str) else ""
    return (*chosen, line) if chosen and line else None


class Chooser:
    """The choice both the pet's card and the main chat bring, one at a time."""

    def __init__(self, workspace):
        self.ws = workspace
        # {"at", "shaped", "item"}, until shown or stale.
        self.choice: Optional[dict] = None
        self._task: Optional[asyncio.Task] = None
        # The surfaces that asked while it was being made, told when it is ready.
        self._asked: set[str] = set()
        self._empty_at = -EMPTY_S

    def _here(self) -> set[str]:
        return {m["card"]["id"] for m in self.ws._main.shared()}

    def _unshown(self, choice: dict) -> bool:
        from .panels import feed
        if life.clock() - choice["at"] > STALE_S:
            return False
        item = self.ws._library().get(choice["item"].id)
        mark = feed._marks(feed._load(self.ws._runtime() / feed.TASTE_FILE))[0].get(choice["item"].id, {})
        return (item is not None and item.state != DISMISSED and not item.told and not mark.get("seen")
                and item.id not in self._here())

    async def take(self, surface: str) -> Optional[tuple[dict, Item]]:
        """The choice when one waits that no surface has shown; else None, and one is chosen in the
        background, `surface` told when it is ready (the card through `news`, the chat by the share step)."""
        choice = self.choice
        if choice and await asyncio.to_thread(self._unshown, choice):
            # The chat always shows what it takes; the card may yet not, and says so when it does (seen).
            if surface == "chat":
                self.choice = None
            return choice["shaped"], choice["item"]
        self.choice = None
        if time.monotonic() - self._empty_at < EMPTY_S:
            return None
        self._asked.add(surface)
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._choose())
        return None

    async def _choose(self) -> None:
        from .panels import feed
        await quiet.wait()
        runtime, values = self.ws._runtime(), self.ws.config()
        now = life.clock()
        path = runtime / feed.TASTE_FILE
        topics = feed.load_topics(path)
        name, persona, lang = profile.character(self.ws.home, values)
        rows = await asyncio.to_thread(candidates, self.ws._library(), feed._load(path), now, topics, lang,
                                       self._here())
        if not rows:
            self._asked.clear()
            self._empty_at = time.monotonic()
            return
        shaped, item = rows[0]
        line = ""
        if profile.configured(values):
            system, user = await asyncio.to_thread(prompt, runtime, name, persona, lang, topics, rows, now)
            try:
                answer = await profile.ask(runtime, self.ws.home, values, "pick", system, user,
                                           max_tokens=MAX_TOKENS, now=now)
            except Exception as exc:
                logger.warning("the pick call failed: %s", exc)
                answer = ""
            picked = parse(answer, rows, lang)
            if picked:
                shaped, item, line = picked
        self.choice = {"at": life.clock(), "shaped": dict(shaped, line=line), "item": item}
        asked, self._asked = self._asked, set()
        if "chat" in asked:
            self.ws._share_wake.set()
        if "card" in asked:
            self.ws.news()
