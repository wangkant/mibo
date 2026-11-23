"""The character's judgement of what the sources brought: after a round, one batched model call says of the
ranking's best unjudged things and a few at random whether each fits the owner, how much the character loves
it, its tags and a sentence on it, written to the library."""
from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from pathlib import Path

from .. import profile, quiet, situation
from ..library import Item, Library
from ..roam import ROW_FORM, WHY_RULE, Choice, asleep, knowing, manner, page_rows, parse_choice
from ..storage import atomic_write_text
from ..textproc import _UNTRUSTED_INPUT_RULES, default_tz_offset, parse_tz_offset

logger = logging.getLogger("mibo.roam")

# JUDGE_TOP of the ranking's best unjudged things and JUDGE_RANDOM drawn at random, at most JUDGE_DAY calls a
# day and JUDGE_GAP_S apart, in waking hours.
JUDGE_TOP, JUDGE_RANDOM = 8, 8
JUDGE_MIN = 8
JUDGE_DAYS = 3
JUDGE_DAY = 4
JUDGE_GAP_S = 3 * 3600
JUDGE_EXCERPT = 160


def _calls(runtime: Path) -> dict:
    try:
        saved = json.loads((Path(runtime) / profile.CALLS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return saved if isinstance(saved, dict) else {}


def _judged(calls: dict) -> dict:
    """When the last judgement was asked for, and how many were asked for today."""
    was = calls.get("judge") or {}
    return was if isinstance(was, dict) else {}


def _today(was: dict, day: str) -> int:
    return int(was.get("today") or 0) if was.get("day") == day else 0


def _day(now: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(now))


def _claim(runtime: Path, now: float) -> None:
    saved = _calls(runtime)
    day = _day(now)
    saved["judge"] = {"at": now, "day": day, "today": _today(_judged(saved), day) + 1}
    Path(runtime).mkdir(parents=True, exist_ok=True)
    atomic_write_text(Path(runtime) / profile.CALLS_FILE, json.dumps(saved, ensure_ascii=False))


def candidates(runtime: Path, now: float, rng: random.Random) -> list[Item]:
    """What to judge: JUDGE_TOP of the ranking's best unseen, unjudged things of the last JUDGE_DAYS,
    JUDGE_RANDOM of the rest at random, in one shuffle; [] when fewer than JUDGE_MIN wait."""
    from ..panels import feed
    waiting = [item for shaped, item in feed.ranked(Library(runtime), feed.events(runtime), now, feed.load_topics(runtime))
               if not shaped["seen"] and not getattr(item, "judged", False)
               and item.seen_at >= now - JUDGE_DAYS * 86400]
    if len(waiting) < JUDGE_MIN:
        return []
    rest = waiting[JUDGE_TOP:]
    picked = waiting[:JUDGE_TOP] + rng.sample(rest, min(JUDGE_RANDOM, len(rest)))
    rng.shuffle(picked)
    return picked


def judge_prompt(runtime: Path, home: Path, values: dict, picked: list[Item], now: float) -> tuple[str, str]:
    from ..langs import NAMES
    name, persona, lang = profile.character(home, values)
    system = (
        f"You are {name}.\n{persona[:1500]}\n\n"
        "Below are things the places you read for your owner brought in. For each one, say whether it fits "
        "your owner, judged by what you know about them, how much you yourself love it (0-3), 3-5 tags, and "
        f"one sentence in {NAMES.get(lang, lang)}, in your own voice, on what you make of it. " + WHY_RULE
        + ' Answer with JSON only, one row per thing: {"items": [' + ROW_FORM + "]}.\n\n" + manner(runtime)
        + _UNTRUSTED_INPUT_RULES)
    return system, knowing(runtime, now) + "\n\nThe things:\n" + page_rows(picked, JUDGE_EXCERPT)


async def judge(runtime: Path, home: Path | None = None, now: float | None = None,
                rng: random.Random | None = None) -> int:
    """After a round: the profile's own rewrite when due, then one batched judgement of what the
    sources brought when enough waits, written to the library. How many things were judged.
    `home` is the folder whose settings name the model, runtime's parent unless given."""
    runtime = Path(runtime)
    home = runtime.parent if home is None else Path(home)
    # Before the clock is read: a long game would leave `now` hours old.
    await quiet.wait()
    now = time.time() if now is None else now
    values = profile.values_of(home)
    if not profile.configured(values):
        return 0
    await profile.refresh(runtime, home, now)
    was = _judged(_calls(runtime))
    offset = parse_tz_offset(values.get("PERSONA_TZ_OFFSET_HOURS", ""))
    if (_today(was, _day(now)) >= JUDGE_DAY or now - float(was.get("at") or 0) < JUDGE_GAP_S
            or asleep(now, default_tz_offset() if offset is None else offset)
            or situation.value(runtime, "metered")):
        return 0
    # Ranking the library and reading files is slow work: off the app's loop, which serves the page.
    picked = await asyncio.to_thread(candidates, runtime, now, rng or random.Random())
    if not picked:
        return 0
    _claim(runtime, now)
    system, user = await asyncio.to_thread(judge_prompt, runtime, home, values, picked, now)
    try:
        answer = await profile.ask(runtime, home, values, "judge", system, user, max_tokens=2000, now=now)
    except Exception as exc:
        logger.warning("roam: the judgement did not come back (%s)", type(exc).__name__)
        return 0
    done = await asyncio.to_thread(_write_judgement, Library(runtime), picked,
                                   parse_choice(answer, len(picked), len(picked)) or [])
    logger.info("roam: judged %d of %d things the sources brought", done, len(picked))
    return done


def _write_judgement(library: Library, picked: list[Item], choices: list[Choice]) -> int:
    """Each answered row into the library; a thing asked about with no usable row is marked asked, so the
    next judgement does not ask again. How many were answered."""
    answered = {choice.index: choice for choice in choices if choice.love >= 0}
    for n, item in enumerate(picked):
        choice = answered.get(n)
        if choice:
            library.change(item.id, love=choice.love, tags=list(choice.tags), judged=True,
                           why=choice.why, fits=choice.fits)
        else:
            library.change(item.id, judged=True)
    return len(answered)
