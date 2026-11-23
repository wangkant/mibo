"""When the character brings something it found: the pet's card and the main chat's share step.

Nothing here runs on its own. `Pacer.due(surface)` is asked when the pet looks
(GET /api/feed/next) and when the share step looks; the program in front
changing (quiet's hook) asks it too, and a good moment found then tells the pet
to look at once (workspace.news) and wakes the share step.

The rule is `decide(pace, seen, now, watch)`, a plain function of two small
dicts, so a made-up day can be replayed against it:

- never while quiet holds or a video is in front, in a call or a game, while
  the person types (the last TYPING_S), or while they are away;
- the gap since the last one: LEISURE_S while browsing, DEEP_S in deep work,
  BASE_S otherwise, times the scale the last outcomes set (opened or liked:
  SOONER; closed, closed at once, left unanswered: LATER, LATER_QUICK), kept
  within FLOOR_S and CAP_S, with jitter so it is never clockwork;
- deep work waits for a good moment as well: back after being away, a switch
  from work to the browser or the desktop, still at the computer but not
  typing; back or off work, AT_MOMENT of the gap is enough;
- each one already brought today stretches the next gap (SPREAD); at most
  DAY_MAX a day, and with fewer than DAY_FLOOR today the gap is never above
  FLOOR_GAP_S and deep work waits no longer than that, so a day at the
  computer is never silent;
- the pace the person set in Settings or asked for in the chat (profile.py
  "pace"): at "less" every gap is FEWER times as long and the day's caps are
  divided by it, and the reason says "fewer"; at "more" the other way round;
- never in the quiet hours they set (profile.py "quiet_hours", local time).

`seen` is what is in front as `see` follows it, kept in memory only (activity.py
never writes it down). With the "角色会留意你在做什么" switch off (remarks)
only the coarse signals count: the idle time and quiet. `pace` per surface is
kept in <runtime>/pace.json: when the last one came, which, how it ended, the
scale and the day's count.
"""
from __future__ import annotations

import asyncio
import json
import math
import random
import threading
from datetime import date, datetime
from pathlib import Path

from . import activity, life, profile, quiet, remarks
from .storage import atomic_write_text

FILE = "pace.json"
SURFACES = ("card", "chat")
# What a person does, as activity.classify names it: work waits for a break, leisure takes things sooner.
WORK = frozenset({"homework", "writing", "coding", "reading", "studying", "designing", "spreadsheet"})
LEISURE = frozenset({"browsing", "shopping", "chatting", "music", "none"})
NEVER = frozenset({"video", "gaming", "meeting"})
# Where typing is the work itself: recent input there counts as typing.
TYPING_KINDS = frozenset({"homework", "writing", "coding", "chatting", "spreadsheet"})
# Seconds.
BASE_S, LEISURE_S, DEEP_S = 30 * 60, 12 * 60, 60 * 60
FLOOR_S, CAP_S = 6 * 60, 4 * 3600
TYPING_S = 30
AWAY_S = 5 * 60
# Away this long makes coming back a good moment; a switch or a return stays one this long.
BACK_S, MOMENT_S = 15 * 60, 3 * 60
# No input this long while present: reading, thinking, a pause.
STILL_S = 90
# Work held this long before a switch to leisure makes the switch a break; back within SWITCH_S is a glance.
STRETCH_S, SWITCH_S = 20 * 60, 60
# The other surface brought something this recently: not now.
SPACING_S = 10 * 60
AT_MOMENT = 0.6
DAY_MAX, DAY_FLOOR, FLOOR_GAP_S = 10, 2, 2 * 3600
# Asked for fewer: gaps this many times as long, the day's caps divided by it; asked for more, the reverse.
FEWER = 2
SLOW = {"less": FEWER, "normal": 1, "more": 1 / FEWER}
SPREAD = 10
SOONER, LATER, LATER_QUICK = 0.7, 1.35, 1.7
SCALE_MIN, SCALE_MAX = 0.25, 20.0
JITTER = (0.8, 1.3)
# A share in the chat nobody reacted to by then was left unanswered; a card that never said how it ended, nothing.
UNANSWERED_S = 15 * 60
# Good moments found by the hook tell the pet at most this often.
NUDGE_S = 60
# Do not disturb, from the pet's menu.
SNOOZE_S = 60 * 60
# How each ending moves the scale; "away" and "hushed" are no answer at all, nor is "known" (seen already).
OUTCOMES = {"open": SOONER, "like": SOONER, "quick": LATER_QUICK, "close": LATER, "timeout": LATER,
            "unanswered": LATER, "away": 1.0, "hushed": 1.0, "next": 1.0, "known": 1.0}


# ---------------------------------------------------------------- the rule --

def fresh_seen() -> dict:
    return {"kind": "", "since": 0.0, "was": "", "was_since": 0.0, "held": 0.0, "idle": 0.0, "away_from": None,
            "back": None, "away_for": 0.0, "typed": float("-inf"), "quiet": False, "video": False}


def see(seen: dict, now: float, kind: str, idle: float, quiet_on: bool, video: bool, typed: float) -> None:
    """One look at what is in front: the stretch of one activity, the last switch, away and back."""
    if quiet_on or video or kind in ("video", "meeting"):
        # A video is watched, and a call or a game held, without the keys: the person is there.
        idle = 0.0
    seen.update(idle=idle, quiet=quiet_on, video=video, typed=max(seen["typed"], typed))
    if idle >= AWAY_S:
        if seen["away_from"] is None:
            seen["away_from"] = now - idle
        return
    if seen["away_from"] is not None:
        seen["back"], seen["away_for"] = now - idle, now - idle - seen["away_from"]
        seen["away_from"] = None
        # Back at the computer: a stretch starts afresh.
        seen.update(kind=kind, since=now - idle, was="", held=0.0)
        return
    if kind == seen["kind"]:
        return
    if kind == seen["was"] and now - seen["since"] < SWITCH_S:
        # A glance elsewhere and back: the stretch before goes on.
        seen.update(kind=kind, since=seen["was_since"], was="", held=0.0)
        return
    seen.update(was=seen["kind"], was_since=seen["since"], held=now - seen["since"], kind=kind, since=now)


def typing(seen: dict, now: float, watch: bool) -> bool:
    return now - seen["typed"] < TYPING_S or (watch and seen["kind"] in TYPING_KINDS and seen["idle"] < TYPING_S)


def moment(seen: dict, now: float, watch: bool) -> str:
    """A good moment to bring something, or ""."""
    if seen["back"] is not None and now - seen["back"] < MOMENT_S and seen["away_for"] >= BACK_S:
        return "back"
    if watch and seen["was"] in WORK and seen["kind"] in LEISURE and now - seen["since"] < MOMENT_S \
            and seen["held"] >= STRETCH_S:
        return "break"
    if STILL_S <= seen["idle"] < AWAY_S and not typing(seen, now, watch):
        return "still"
    return ""


def gap(pace: dict, kind: str) -> float:
    """Seconds wanted since the last one, before a good moment shortens it."""
    base = DEEP_S if kind in WORK else LEISURE_S if kind in LEISURE else BASE_S
    slow = pace["slow"]
    # Each one already brought today spaces the next a little more, so the evening is not left empty.
    wanted = min(CAP_S, max(FLOOR_S, base * pace["scale"] * (1 + pace["count"] / SPREAD))) * slow
    if pace["count"] < DAY_FLOOR // slow:
        wanted = min(wanted, FLOOR_GAP_S * slow)
    # The same draw for as long as the last one stands, so asking again does not reroll it.
    return wanted * random.Random(int(pace["last"])).uniform(*JITTER)


def hushed(quiet: tuple | None, now: float) -> bool:
    """Whether local `now` is in the quiet hours (start, end) in minutes of the day; they may cross midnight."""
    if not quiet:
        return False
    at = datetime.fromtimestamp(now)
    minute, (start, end) = at.hour * 60 + at.minute, quiet
    return start <= minute < end if start < end else minute >= start or minute < end


def decide(pace: dict, seen: dict, now: float, watch: bool) -> tuple[bool, str]:
    """(whether to bring something now, why). `pace`: {last, other, scale, count, slow, quiet} for this
    surface, `other` being when another surface last brought something, `slow` the SLOW of the pace the person
    set and `quiet` their quiet hours or None; `seen` as `see` keeps it."""
    kind = seen["kind"] if watch else ""
    slow = pace["slow"]
    fewer = " (fewer)" if slow > 1 else ""
    if hushed(pace["quiet"], now):
        return False, "quiet hours"
    if seen["quiet"] or (watch and seen["video"]):
        return False, "quiet"
    if kind in NEVER:
        return False, kind
    if seen["idle"] >= AWAY_S:
        return False, "away"
    if typing(seen, now, watch):
        return False, "typing"
    if pace["count"] >= DAY_MAX // slow:
        return False, "day cap" + fewer
    if now - pace["other"] < SPACING_S:
        return False, "other surface"
    found = moment(seen, now, watch)
    if kind in WORK and not found and not (pace["count"] < DAY_FLOOR // slow
                                           and now - pace["last"] >= FLOOR_GAP_S * slow):
        return False, "deep work"
    # Back at the computer or off work: sooner. A pause is only when it may come, not sooner.
    need = max(FLOOR_S, gap(pace, kind) * (AT_MOMENT if found in ("back", "break") else 1))
    if now - pace["last"] < need:
        return False, f"gap {int(need // 60)}m{fewer}"
    return True, found or kind or "gap"


def outcome(row: dict, how: str) -> None:
    """How the last one ended moves the scale, once."""
    row["scale"] = min(SCALE_MAX, max(SCALE_MIN, row["scale"] * OUTCOMES[how]))
    row["done"] = how


def new_row() -> dict:
    return {"last": 0.0, "id": "", "done": "", "scale": 1.0, "day": "", "count": 0}


def today(row: dict, now: float) -> dict:
    """The row as of `now`'s day: a new day starts its count again and takes the scale halfway back to 1."""
    day = date.fromtimestamp(now).isoformat()
    if row["day"] != day:
        row.update(day=day, count=0, scale=math.sqrt(row["scale"]))
    return row


def settle(row: dict, surface: str, now: float) -> None:
    """A share no one answered within UNANSWERED_S was left unanswered; a card never ended says nothing."""
    if row["id"] and not row["done"] and now - row["last"] >= UNANSWERED_S:
        outcome(row, "unanswered" if surface == "chat" else "away")


def wants(runtime: Path) -> dict:
    """What the person set (profile.py): {"slow": SLOW of their pace, "quiet": (start, end) minutes or None}."""
    known = profile.load(runtime, False)
    hours = known["quiet_hours"]
    minutes = lambda clock: int(clock[:2]) * 60 + int(clock[3:])  # noqa: E731
    return {"slow": SLOW[known["pace"]], "quiet": hours and (minutes(hours["from"]), minutes(hours["to"]))}


def view(rows: dict, surface: str, slow: float = 1, quiet: tuple | None = None) -> dict:
    row = rows[surface]
    return {"last": row["last"], "scale": row["scale"], "count": row["count"], "slow": slow, "quiet": quiet,
            "other": max((r["last"] for s, r in rows.items() if s != surface), default=0.0)}


# ------------------------------------------------------------------- the app --

class Pacer:
    """The rule against this computer and this home: reads what is in front when asked, keeps pace.json."""

    def __init__(self, workspace):
        self.ws = workspace
        self.seen = fresh_seen()
        self._lock = threading.Lock()
        self._nudged = float("-inf")
        # Until when nothing is brought, as the pet's menu asked (life.clock seconds); kept while the app runs.
        self.snoozed = 0.0

    def _path(self) -> Path:
        return self.ws._runtime() / FILE

    def _rows(self, now: float) -> dict:
        try:
            saved = json.loads(self._path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = {}
        rows = {}
        for surface in SURFACES:
            row = new_row()
            row.update({k: v for k, v in (saved.get(surface) or {}).items() if k in row})
            rows[surface] = today(row, now)
            settle(rows[surface], surface, now)
        return rows

    def _save(self, rows: dict) -> None:
        atomic_write_text(self._path(), json.dumps(rows), fsync=False)

    def judge(self, now: float, got: activity.Sample | None = None) -> dict[str, tuple[bool, str]]:
        """Look at what is in front (or take the look the remarks loop just made), then the rule per surface."""
        state = remarks.load(self.ws._runtime())
        wanted = wants(self.ws._runtime())
        watch = state["on"]
        if got is None:
            got = activity.sense(state["ignore"]) if watch else activity.Sample("", activity.idle(), False)
        q = quiet.state()
        with self._lock:
            see(self.seen, now, got.activity if watch else "", got.idle_s, q["quiet"], q["video_front"],
                now - quiet.typed_ago())
            rows = self._rows(now)
            if now < self.snoozed:
                return dict.fromkeys(SURFACES, (False, "snoozed"))
            return {surface: decide(view(rows, surface, **wanted), self.seen, now, watch) for surface in SURFACES}

    def snooze(self, on: bool) -> float:
        """Do not disturb for SNOOZE_S from now, or no longer; when it ends (0 when off)."""
        self.snoozed = life.clock() + SNOOZE_S if on else 0.0
        return self.snoozed

    async def due(self, surface: str) -> bool:
        return (await asyncio.to_thread(self.judge, life.clock()))[surface][0]

    def shown(self, surface: str, ident: str) -> None:
        """Something was brought on `surface` now."""
        now = life.clock()
        with self._lock:
            rows = self._rows(now)
            row = rows[surface]
            row.update(last=now, id=ident, done="", count=row["count"] + 1)
            self._save(rows)

    def ended(self, ident: str, how: str, surface: str) -> None:
        """How the last thing a surface brought ended, the first time it is told."""
        now = life.clock()
        with self._lock:
            rows = self._rows(now)
            row = rows.get(surface)
            if row is None or row["id"] != ident or row["done"]:
                return
            outcome(row, how)
            self._save(rows)

    async def look(self, got: activity.Sample | None = None) -> None:
        """What is in front changed, or the remarks loop looked: at a good moment the pet looks, and the
        share step. At most once every NUDGE_S; in between only the look is kept."""
        now = life.clock()
        verdict = await asyncio.to_thread(self.judge, now, got)
        if now - self._nudged < NUDGE_S:
            return
        if verdict["card"][0] or verdict["chat"][0]:
            self._nudged = now
        if verdict["card"][0]:
            self.ws.news()
        if verdict["chat"][0]:
            self.ws._share_wake.set()
