"""What the character knows of its owner, as short text the owner can read and edit.

`<runtime>/profile.json` holds the owner text (likes, habits, situation), the
character's own "things my owner showed me" note, a lean per catalogue source
(-1..+1, applied to the draw by `situation.supply`) and a few walk search
words. The character's core taste is its persona and is never rewritten here.

It starts from the picked topics, an optional free-text answer (which asks the
model at once) and the owner notes, and is rewritten by one model call about
once a week. A line the owner edits is pinned and kept verbatim; a "not this"
they write becomes a hard rule. The model calls here, in `roam.judge` and in
`recommend` are counted in `<runtime>/character_calls.json` for the settings page.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import date
from pathlib import Path
from typing import Optional

from dotenv import dotenv_values

from . import drafting, langs, situation
from . import setup_wizard as sw
from .llm import purpose
from .storage import atomic_write_text
from .textproc import _UNTRUSTED_INPUT_RULES, _fence_user_data, strip_json_fences
from .usage import UsageBook

logger = logging.getLogger("personagent.profile")

FILE = "profile.json"
CALLS_FILE = "character_calls.json"
FIELDS = ("owner", "character_learned")
OWNER_MAX = 1000
LEARNED_LINES = 3
LINE_MAX = 200
FREE_MAX = 1000
WORDS_MIN, WORDS_MAX, WORD_LEN = 3, 5, 40
PINNED_MAX = 30
RULES_MAX = 30
EDITS_MAX = 200
NOTES = 15
LIKED, DISLIKED, DISAGREED = 30, 20, 12
# A rewrite of its own: 25 reactions since the last, or a week with 5.
REWRITE_REACTIONS, WEEK_REACTIONS, WEEK_S = 25, 5, 7 * 86400
# A topic the owner said no to is all but never shown.
AVOID_TOPIC = (-3.0, 100.0)


# ------------------------------------------------------------------ the file --

def _path(runtime: Path) -> Path:
    return Path(runtime) / FILE


def _state(runtime: Path) -> dict:
    try:
        saved = json.loads(_path(runtime).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    return saved if isinstance(saved, dict) else {}


def _save(runtime: Path, state: dict) -> None:
    Path(runtime).mkdir(parents=True, exist_ok=True)
    atomic_write_text(_path(runtime), json.dumps(state, ensure_ascii=False, indent=1))


def _seed(runtime: Path, state: dict) -> str:
    """The owner text before any rewrite: the picked topics and the free-text answer."""
    from .panels import feed
    topics = feed.load_topics(Path(runtime) / feed.TASTE_FILE)
    lines = (["Picked topics: " + ", ".join(topics)] if topics else []) + (
        [str(state["free_text"])] if state.get("free_text") else [])
    return "\n".join(lines)


def load(runtime: Path) -> dict:
    """{owner, character_learned, source_lean, walk_words, pinned, rules}."""
    state = _state(runtime)
    lean = state.get("source_lean") if isinstance(state.get("source_lean"), dict) else {}
    return {"owner": str(state.get("owner") or "") or _seed(runtime, state),
            "character_learned": str(state.get("character_learned") or ""),
            "source_lean": {str(k): float(v) for k, v in lean.items() if isinstance(v, (int, float))},
            "walk_words": [str(w) for w in state.get("walk_words") or [] if isinstance(w, str)],
            "pinned": [p for p in state.get("pinned") or [] if isinstance(p, dict)],
            "rules": [r for r in state.get("rules") or [] if isinstance(r, dict)]}


def rewritten(runtime: Path) -> bool:
    return bool(_state(runtime).get("at"))


def avoided(runtime: Path) -> list[str]:
    """The topics the owner said no to (the taste model gives each the AVOID_TOPIC prior)."""
    return [str(r["topic"]) for r in load(runtime)["rules"] if r.get("kind") == "topic" and r.get("topic")]


def hidden_sources(runtime: Path) -> set[str]:
    return {r["key"] for r in load(runtime)["rules"] if r.get("kind") == "hide_source"}


# ------------------------------------------------------------------- the model --

class _Model(drafting._Client):
    """The configured model, outside the service; keeps the usage the last answer reported."""
    usage: dict = {}

    def _count_usage(self, model: str, resp) -> None:
        try:
            body = resp.json()
            self.usage = body["usage"] if isinstance(body, dict) and isinstance(body.get("usage"), dict) else {}
            book = UsageBook(self._usage_path)
            book.add(model, self.usage, time.time(), "other")
            book.flush(time.time())
        except Exception:
            pass


def values_of(home: Path) -> dict:
    return {k: str(v or "") for k, v in dotenv_values(Path(home) / ".env").items()}


def character(home: Path, values: dict) -> tuple[str, str, str]:
    """(name, persona text, language) the way the page's own persona view reads them."""
    lang = langs.normalize(values.get("AGENT_LANG")) or "en"
    name = values.get("PERSONA_NAME") or sw.DEFAULT_NAMES.get(lang, "Nova")
    card = Path(home) / "persona.txt"
    text = card.read_text(encoding="utf-8") if card.is_file() else sw.persona_text(
        sw.TEMPLATE, name=name, lang=lang, admin_name=values.get("ADMIN_NAME", ""),
        admin_relationship=values.get("ADMIN_RELATIONSHIP", ""))
    return name, text.strip(), lang


def configured(values: dict) -> bool:
    return all(values.get(k) for k in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"))


def count(runtime: Path, kind: str, prompt: int, answer: int, now: float) -> None:
    """One call of `kind` ("judge", "profile" or "pick") and its tokens, in this month's row."""
    path = Path(runtime) / CALLS_FILE
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    saved = saved if isinstance(saved, dict) else {}
    month = saved.setdefault("months", {}).setdefault(time.strftime("%Y-%m", time.localtime(now)), {})
    row = month.setdefault(kind, {"calls": 0, "input": 0, "output": 0})
    row["calls"] += 1
    row["input"] += int(prompt)
    row["output"] += int(answer)
    Path(runtime).mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(saved, ensure_ascii=False))


def calls(runtime: Path) -> dict:
    """{month: {kind: {calls, input, output}}}, newest month first."""
    try:
        months = json.loads((Path(runtime) / CALLS_FILE).read_text(encoding="utf-8")).get("months") or {}
    except (OSError, ValueError, AttributeError):
        months = {}
    return dict(sorted(months.items(), reverse=True))


async def ask(runtime: Path, home: Path, values: dict, kind: str, system: str, user: str, *,
              max_tokens: int, now: float) -> str:
    """One JSON call to the configured model, counted; tokens as reported, else characters / 4."""
    client = _Model(values, drafting.usage_path(Path(home), values))
    try:
        with purpose("other"):
            answer = await client._call_llm(system, [{"role": "user", "content": user}], client.model,
                                            max_tokens=max_tokens, enable_search=False, disable_thinking=True,
                                            temperature=0.4, json_object=True)
    finally:
        await client.close()
    usage = client.usage
    count(runtime, kind, usage.get("prompt_tokens") or (len(system) + len(user)) // 4,
          usage.get("completion_tokens") or len(answer or "") // 4, now)
    return answer


# ------------------------------------------------------------- what it reads --

def _owner_notes(runtime: Path, values: dict) -> list[str]:
    from . import life
    rows = life.owner_notes(life.Sources.from_files(Path(runtime), values))
    rows.sort(key=life._note_time, reverse=True)
    return [" ".join(str(r.get("text")).split()) for r in rows][:NOTES]


def readable_sources(runtime: Path) -> dict:
    """The public catalogue sources the owner can read and reach, by key."""
    from .sources import catalog
    readable = situation.readable(runtime)
    return {s.key: s for s in catalog.all_sources(catalog.load_choice(runtime)["own"]).values()
            if s.group != "own" and s.lang in readable and situation.gate(runtime, key=s.key)}


def _reactions(runtime: Path) -> list:
    from .panels import feed
    return [e for e in feed._load(Path(runtime) / feed.TASTE_FILE) if e[2] != "seen"]


def _history(runtime: Path) -> tuple[list[str], list[str], list[str]]:
    """Titles liked or opened, skipped or hidden (newest first), and where the character's judgement disagreed."""
    from .library import Library
    from .panels import feed
    events = feed._load(Path(runtime) / feed.TASTE_FILE)
    marks = feed._marks(events)[0]
    items = {item.id: item for item in Library(runtime).items()}
    liked, disliked, seen = [], [], {}
    for at, ident, action, *_ in reversed(events):
        item = items.get(ident)
        if item is None or ident in seen or action == "seen":
            continue
        seen[ident] = True
        mark = marks[ident]
        if mark["like"] or mark["open"]:
            liked.append(item.title)
        elif mark["skip"]:
            disliked.append(item.title)
    disagreed = []
    for ident in seen:
        item, mark = items[ident], marks[ident]
        love = getattr(item, "love", -1)
        if love < 0:
            continue
        said_yes, did_yes = item.fits or love >= 2, mark["like"] or mark["open"]
        if said_yes != did_yes and (did_yes or mark["skip"]):
            disagreed.append(f"{item.title} - you said love {love}, fits {str(item.fits).lower()}; "
                             f"the owner {'opened or liked it' if did_yes else 'skipped it'}")
    return liked[:LIKED], disliked[:DISLIKED], disagreed[:DISAGREED]


def _signature(runtime: Path) -> str:
    return json.dumps([situation.value(runtime, "region"), sorted(situation.readable(runtime))])


# ---------------------------------------------------------------- the rewrite --

_INSTRUCTION = (
    "You are {name}. Your persona follows; it is your own taste and it is never rewritten.\n{persona}\n\n"
    "Below is what you know of your owner. Rewrite your notes about them as JSON only:\n"
    '{{"owner": "<at most about 200 tokens: stable likes and dislikes, format and attention habits, '
    'and situation lines such as job, studies, exams, current project, travel>", '
    '"character_learned": "<at most 3 lines: things my owner showed me that I came to like>", '
    '"source_lean": {{"<source key>": <-1 to 1>}}, '
    '"walk_words": ["<3 to 5 search words for what they are into or up to now>"], '
    '"avoid_sources": ["<source key>"], "avoid_topics": ["<short topic>"]}}\n'
    "- Write owner and character_learned in {language}. Keep every pinned line exactly as written.\n"
    "- source_lean: only keys from the source list, and only where their situation or taste says more "
    "(+) or less (-) of that source; leave the rest out.\n"
    "- walk_words: words a search box on a video site would take, in the language they read.\n"
    "- avoid_sources and avoid_topics: only what the owner wrote themselves that they do not want; "
    "never inferred from what they skipped. Empty lists are fine.\n\n" + _UNTRUSTED_INPUT_RULES)


def _prompt(runtime: Path, home: Path, values: dict, state: dict, now: float) -> tuple[str, str]:
    from .roam import fence_pages
    name, persona, lang = character(home, values)
    current = load(runtime)
    liked, disliked, disagreed = _history(runtime)
    sources = readable_sources(runtime)
    own_words = [p["text"] for p in current["pinned"]] + ([state["free_text"]] if state.get("free_text") else [])

    def block(title: str, lines: list[str], fence=_fence_user_data) -> str:
        return f"{title}:\n" + (fence("\n".join(f"- {x}" for x in lines)) if lines else "(none)")

    user = "\n\n".join([
        block("Your notes about the owner now", current["owner"].splitlines()),
        block("Things your owner showed you that you came to like", current["character_learned"].splitlines()),
        block("Pinned lines (keep verbatim)", [f"[{p['field']}] {p['text']}" for p in current["pinned"]]),
        block("What the owner wrote themselves", own_words),
        block("What you remember of the owner", _owner_notes(runtime, values)),
        # Titles are the pages' own words.
        block("Recently opened or liked", liked, fence_pages),
        block("Recently skipped or hidden", disliked, fence_pages),
        block("Where your judgement and the owner's reaction disagreed", disagreed, fence_pages),
        "Their situation:\n" + (situation.notes(runtime, now) or "(unknown)"),
        "Sources:\n" + "\n".join(f"{s.key}: {s.about[0]}" for s in sources.values())])
    return _INSTRUCTION.format(name=name, persona=persona[:1500], language=langs.NAMES.get(lang, lang)), user


def _text(value, limit: int) -> str:
    return "\n".join(" ".join(line.split()) for line in str(value or "").splitlines() if line.strip())[:limit]


def _with_pinned(text: str, pinned: list[dict], field: str) -> str:
    """`text` with every pinned line of `field` in it, verbatim."""
    lines = text.splitlines()
    missing = [p["text"] for p in pinned if p["field"] == field and p["text"] not in lines]
    return "\n".join(missing + lines)


def apply(runtime: Path, answer: str, state: dict) -> dict:
    """The rewrite's answer into the saved state; unknown source keys and malformed fields are dropped."""
    value = json.loads(strip_json_fences(str(answer or "")))
    keys = set(readable_sources(runtime))
    pinned = load(runtime)["pinned"]
    owner = _with_pinned(_text(value.get("owner"), OWNER_MAX), pinned, "owner")
    learned = "\n".join(_with_pinned(_text(value.get("character_learned"), LEARNED_LINES * LINE_MAX),
                                     pinned, "character_learned").splitlines()[:LEARNED_LINES])
    lean = value.get("source_lean") if isinstance(value.get("source_lean"), dict) else {}
    words = [w for w in (" ".join(str(x).split())[:WORD_LEN] for x in value.get("walk_words") or []
                         if isinstance(x, str)) if w]
    rules = [{"kind": "hide_source", "key": k} for k in value.get("avoid_sources") or [] if k in keys]
    rules += [{"kind": "topic", "topic": t} for t in (" ".join(str(x).split())[:WORD_LEN].casefold()
                                                     for x in value.get("avoid_topics") or []
                                                     if isinstance(x, str)) if t]
    # Rules the owner set by hand stay; the rest follow from their own lines each time.
    own = [r for r in state.get("rules") or [] if r.get("by") == "owner"]
    rules = own + [r for r in rules if {**r, "by": "owner"} not in own]
    state.update(owner=owner or state.get("owner", ""), character_learned=learned,
                 source_lean={k: max(-1.0, min(1.0, float(v))) for k, v in lean.items()
                              if k in keys and isinstance(v, (int, float)) and not isinstance(v, bool)},
                 walk_words=words[:WORDS_MAX] if len(words) >= WORDS_MIN else state.get("walk_words", []),
                 rules=rules[:RULES_MAX])
    return state


async def rewrite(runtime: Path, home: Optional[Path] = None, now: Optional[float] = None) -> bool:
    """One rewrite call now; False when no model is set or the answer could not be used."""
    runtime = Path(runtime)
    home = runtime.parent if home is None else Path(home)
    now = time.time() if now is None else now
    values = values_of(home)
    if not configured(values):
        return False
    # Reading the feed, the library and the catalogue is slow work: off the app's loop.
    state = await asyncio.to_thread(_state, runtime)
    system, user = await asyncio.to_thread(_prompt, runtime, home, values, state, now)
    try:
        answer = await ask(runtime, home, values, "profile", system, user, max_tokens=1200, now=now)
        state = await asyncio.to_thread(apply, runtime, answer, state)
    except Exception as exc:
        logger.warning("profile: the rewrite did not come back usable (%s)", type(exc).__name__)
        return False
    await asyncio.to_thread(_finish, runtime, state, now)
    return True


def _finish(runtime: Path, state: dict, now: float) -> None:
    state.update(at=now, day=date.fromtimestamp(now).isoformat(), reactions=len(_reactions(runtime)),
                 signature=_signature(runtime))
    _save(runtime, state)


def due(runtime: Path, now: float) -> bool:
    """A rewrite of its own: at most once a day, after enough reactions or a changed situation."""
    state = _state(runtime)
    if state.get("day") == date.fromtimestamp(now).isoformat():
        return False
    signature = _signature(runtime)
    if "signature" not in state:
        # The situation as first seen is where it starts, not a change; the first week counts from here.
        _save(runtime, {**state, "signature": signature, "since": now})
        return False
    new = len(_reactions(runtime)) - int(state.get("reactions") or 0)
    return (new >= REWRITE_REACTIONS or signature != state["signature"]
            or (new >= WEEK_REACTIONS and now - float(state.get("at") or state.get("since") or now) >= WEEK_S))


async def refresh(runtime: Path, home: Optional[Path] = None, now: Optional[float] = None) -> bool:
    now = time.time() if now is None else now
    return await asyncio.to_thread(due, runtime, now) and await rewrite(runtime, home, now)


# ---------------------------------------------------------- the owner's edits --

def _lines(text: str) -> list[str]:
    return _text(text, 10_000).splitlines()


async def answer(runtime: Path, home: Path, text: str, now: Optional[float] = None) -> bool:
    """The first run's free-text answer: kept, and one rewrite at once."""
    text = " ".join(str(text or "").split())
    if not text or len(text) > FREE_MAX:
        raise ValueError("profile_invalid")
    state = _state(runtime)
    _save(runtime, {**state, "free_text": text, "edits": (state.get("edits") or [])[-EDITS_MAX:]
                    + [{"at": time.time() if now is None else now, "field": "free_text"}]})
    return await rewrite(runtime, home, now)


def edit(runtime: Path, payload: dict, now: Optional[float] = None) -> bool:
    """The owner's own changes. A line they add to a text is pinned; a removed pinned line is unpinned.
    Returns whether a text changed, so the caller can ask for a rewrite that turns a "not this" into a rule."""
    now = time.time() if now is None else now
    state = _state(runtime)
    current = load(runtime)
    pinned = current["pinned"]
    changed = False
    for field in FIELDS:
        if field not in payload:
            continue
        if not isinstance(payload[field], str) or len(payload[field]) > OWNER_MAX * 2:
            raise ValueError("profile_invalid")
        lines = _lines(payload[field])
        if field == "character_learned":
            lines = lines[:LEARNED_LINES]
        added = [line[:LINE_MAX] for line in lines if line not in current[field].splitlines()]
        pinned = [p for p in pinned if p["field"] != field or p["text"] in lines] + [
            {"field": field, "text": line} for line in added]
        state[field] = "\n".join(lines)
        changed = changed or bool(added) or lines != current[field].splitlines()
    if "pinned" in payload:
        rows = payload["pinned"]
        if not isinstance(rows, list) or not all(isinstance(p, dict) and p.get("field") in FIELDS
                                                 and isinstance(p.get("text"), str) for p in rows):
            raise ValueError("profile_invalid")
        pinned = [{"field": p["field"], "text": p["text"][:LINE_MAX]} for p in rows]
    if "source_lean" in payload:
        lean = payload["source_lean"]
        if not isinstance(lean, dict) or not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                                                 for v in lean.values()):
            raise ValueError("profile_invalid")
        keys = set(readable_sources(runtime))
        state["source_lean"] = {k: max(-1.0, min(1.0, float(v))) for k, v in lean.items() if k in keys}
    if "walk_words" in payload:
        words = payload["walk_words"]
        if not isinstance(words, list) or not all(isinstance(w, str) for w in words):
            raise ValueError("profile_invalid")
        state["walk_words"] = [w for w in (" ".join(x.split())[:WORD_LEN] for x in words) if w][:WORDS_MAX]
    if "rules" in payload:
        rules = payload["rules"]
        if not isinstance(rules, list) or not all(
                isinstance(r, dict) and ((r.get("kind") == "hide_source" and isinstance(r.get("key"), str))
                                         or (r.get("kind") == "topic" and isinstance(r.get("topic"), str)))
                for r in rules):
            raise ValueError("profile_invalid")
        # A rule already there keeps who made it, so removing one rule does not make the rewrite's rules the owner's.
        before = {(r.get("kind"), r.get("key"), r.get("topic")): r for r in current["rules"]}
        state["rules"] = [before.get((r.get("kind"), r.get("key"), r.get("topic")))
                          or {**{k: r[k] for k in ("kind", "key", "topic") if k in r}, "by": "owner"}
                          for r in rules][:RULES_MAX]
    state["pinned"] = pinned[-PINNED_MAX:]
    # Every edit is a sign that inference or the rewrite was wrong; kept to look back on.
    state["edits"] = (state.get("edits") or [])[-EDITS_MAX:] + [
        {"at": now, "field": f} for f in ("owner", "character_learned", "source_lean", "walk_words", "rules",
                                          "pinned") if f in payload]
    _save(runtime, state)
    return changed
