"""Scheduled tasks: their rhythms, when each next falls, the words that say them, and the store.

A task is something the person asked for once that the character then does on its own: a reminder
said back in words, a piece of work run as a turn of the character, or a condition checked on a
rhythm that speaks only when it holds. The page process keeps the store and runs them
(panels/schedule.py); the character's tools reach the page (schedule_tool.py).

Times: a one-time task keeps its instant; a repeating one keeps its wall time ("08:00 on weekdays")
in the person's zone, and dateutil's rrule finds the next one, zoneinfo (tzdata on Windows) turning it
into an instant with daylight saving. A wall time skipped in spring falls an hour later; one that
comes twice in autumn happens once, at the first.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
import uuid
from datetime import date, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo

import tzlocal
from dateutil import rrule as du

from . import life, timewords
from .storage import atomic_write_text

FILE = "schedule.json"
KINDS = ("remind", "task", "watch")
# The one kind of act a task may be allowed when it is made: working in the app's browser. Sending,
# posting and buying there still wait for a press on a card (web/operate.py).
ACTS = ("browser",)
# Ceilings, and why. Switched on at once: 20 (Gemini keeps 10, ChatGPT 3 to 15, Grok Bot 50; more than
# 20 is more than anyone reads). Kept in all: 50. The shortest rhythm: 30 minutes, since each run
# costs a model turn and a check every 30 minutes is already 48 a day. Model runs a day across all
# tasks: 48, the same day's worth. Reminders need no model and count only against the floor.
ACTIVE_MAX = 20
STORED_MAX = 50
FLOOR_MIN = 30
DAY_RUNS_MAX = 48
# More model runs a day than this, or any allowed act: the task is offered on a card first.
ASK_ABOVE = 2
RETRY_S = 15 * 60
# Later than this after its time, a run says when it was due.
LATE_S = 120
RUNS_KEPT = 20
TITLE_MAX = 40
REQUEST_MAX = 600
REPEATS = ("once", "daily", "weekdays", "weekly", "monthly", "every", "rrule")


# ---- zones ---------------------------------------------------------------------

def zone_name(offset_hours: float | None, now: float) -> str:
    """The person's zone: this computer's named zone, daylight saving kept; a fixed offset when
    PERSONA_TZ_OFFSET_HOURS names another one than this computer's now."""
    name = tzlocal.get_localzone_name() or "UTC"
    if offset_hours is None:
        return name
    # Either of this zone's offsets in the year (-8 for Los Angeles is its winter one): the named zone, so
    # its summer time still counts.
    year = datetime.fromtimestamp(now, timezone.utc).year
    offsets = {datetime(year, month, 15, 12, tzinfo=ZoneInfo(name)).utcoffset().total_seconds() / 3600
               for month in (1, 7)}
    if any(abs(here - offset_hours) < 0.01 for here in offsets):
        return name
    minutes = round(offset_hours * 60)
    return f"UTC{'+' if minutes >= 0 else '-'}{abs(minutes) // 60:02d}:{abs(minutes) % 60:02d}"


def zone(name: str) -> tzinfo:
    fixed = re.fullmatch(r"UTC([+-])(\d\d):(\d\d)", name or "")
    if fixed:
        sign = 1 if fixed.group(1) == "+" else -1
        return timezone(sign * timedelta(hours=int(fixed.group(2)), minutes=int(fixed.group(3))))
    return ZoneInfo(name or "UTC")


def _epoch(wall: datetime, tz: tzinfo) -> float:
    # fold 0: a time that comes twice is the first; a skipped one is read with the offset before the
    # change, which puts it an hour later.
    return wall.replace(tzinfo=tz, fold=0).timestamp()


def _wall(at: float, tz: tzinfo) -> datetime:
    return datetime.fromtimestamp(at, tz).replace(tzinfo=None)


# ---- rhythms -------------------------------------------------------------------

def _hm(text: str) -> tuple[int, int]:
    h, m = str(text or "09:00").split(":")
    return int(h), int(m)


def _rule_of(rule: dict, around: datetime):
    """The dateutil rule of a wall-time rhythm, started a day before `around`."""
    h, m = _hm(rule.get("time"))
    start = (around - timedelta(days=1)).replace(hour=h, minute=m, second=0, microsecond=0)
    base = {"dtstart": start, "byhour": h, "byminute": m, "bysecond": 0}
    repeat = rule["repeat"]
    if repeat == "daily":
        return du.rrule(du.DAILY, **base)
    if repeat == "weekdays":
        return du.rrule(du.WEEKLY, byweekday=(0, 1, 2, 3, 4), **base)
    if repeat == "weekly":
        return du.rrule(du.WEEKLY, byweekday=tuple(rule["days"]), **base)
    if repeat == "monthly":
        day = int(rule["day"])
        if day == -1 or day > 28:
            # The 31st in a short month is its last day.
            return du.rrule(du.MONTHLY, bymonthday=(day, -1) if day > 0 else (-1,), bysetpos=1, **base)
        return du.rrule(du.MONTHLY, bymonthday=day, **base)
    # A written rule counts from the day it was made, so INTERVAL=2 keeps its weeks.
    since = datetime.fromisoformat(rule.get("since") or around.date().isoformat())
    return du.rrulestr(rule["rrule"], dtstart=since.replace(hour=h, minute=m))


def next_after(rule: dict, after: float, tz: tzinfo) -> float | None:
    """The first time of `rule` later than `after`; None when it has none left."""
    repeat = rule["repeat"]
    if repeat == "once":
        return rule["at"] if rule["at"] > after else None
    if repeat == "every":
        step, anchor = int(rule["minutes"]) * 60, float(rule["anchor"])
        if after < anchor:
            return anchor
        return anchor + (math.floor((after - anchor) / step) + 1) * step
    wall = _wall(after, tz)
    found = _rule_of(rule, wall)
    # From three hours back: a spring time pushed an hour later still counts today.
    probe = wall - timedelta(hours=3)
    for _ in range(400):
        nxt = found.after(probe)
        if nxt is None:
            return None
        at = _epoch(nxt, tz)
        if at > after:
            return at
        probe = nxt
    return None


def caught_up(rule: dict, due: float, now: float, tz: tzinfo) -> tuple[float, int]:
    """After the app was closed: the last time at or before `now` from `due` on, and how many fell."""
    last, count = due, 1
    for _ in range(2000):
        nxt = next_after(rule, last, tz)
        if nxt is None or nxt > now:
            break
        last, count = nxt, count + 1
    return last, count


def _sample(rule: dict, now: float, tz: tzinfo, days: int = 400) -> list[float]:
    out, at = [], now
    while len(out) < 3000:
        at = next_after(rule, at, tz)
        if at is None or at > now + days * 86400:
            break
        out.append(at)
    return out


def per_day(rule: dict, now: float, tz: tzinfo) -> int:
    """The most runs it makes on any one day in the coming year."""
    if rule["repeat"] in ("once", "daily", "weekdays", "weekly", "monthly"):
        return 1
    if rule["repeat"] == "every":
        return math.ceil(1440 / int(rule["minutes"]))
    days: dict = {}
    for at in _sample(rule, now, tz):
        key = _wall(at, tz).date()
        days[key] = days.get(key, 0) + 1
    return max(days.values(), default=0)


def problem(rule: dict, now: float, tz: tzinfo) -> str:
    """Why a rhythm cannot be kept: "past", "too_often", "none" or ""."""
    if rule["repeat"] == "once":
        return "past" if rule["at"] <= now else ""
    if rule["repeat"] == "every":
        return "too_often" if int(rule["minutes"]) < FLOOR_MIN else ""
    if rule["repeat"] != "rrule":
        return ""
    times = _sample(rule, now, tz)
    if not times:
        return "none"
    if any(b - a < FLOOR_MIN * 60 - 1 for a, b in zip(times, times[1:])):
        return "too_often"
    return ""


def clean_rule(raw: dict, now: float, tz: tzinfo) -> dict | None:
    """A rule as the model or the form sent it, kept to the fields its rhythm has; None when unreadable."""
    if not isinstance(raw, dict) or raw.get("repeat") not in REPEATS:
        return None
    repeat = raw["repeat"]
    try:
        if repeat == "once":
            at = raw.get("at")
            if isinstance(at, str):
                wall = datetime.fromisoformat(at.strip().replace(" ", "T"))
                at = wall.timestamp() if wall.tzinfo else _epoch(wall, tz)
            return {"repeat": "once", "at": float(at)}
        if repeat == "every":
            minutes = int(raw.get("minutes") or 0)
            return {"repeat": "every", "minutes": minutes, "anchor": float(raw.get("anchor") or now)} \
                if minutes > 0 else None
        h, m = _hm(raw.get("time") or "09:00")
        if not (0 <= h < 24 and 0 <= m < 60):
            return None
        rule = {"repeat": repeat, "time": f"{h:02d}:{m:02d}"}
        if repeat == "weekly":
            days = sorted({int(d) for d in raw.get("days") or []} & set(range(7)))
            if not days:
                return None
            rule["days"] = days
        if repeat == "monthly":
            day = int(raw.get("day") or 0)
            if not (day == -1 or 1 <= day <= 31):
                return None
            rule["day"] = day
        if repeat == "rrule":
            text = str(raw.get("rrule") or "").strip().upper().removeprefix("RRULE:")
            du.rrulestr(text, dtstart=datetime(2026, 1, 1))
            rule.update(rrule=text, since=str(raw.get("since") or _wall(now, tz).date().isoformat()))
        return rule
    except (TypeError, ValueError, OverflowError):
        return None


# ---- words ---------------------------------------------------------------------

_CN = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8,
       "九": 9, "十": 10}
_N = r"[0-9]{1,2}|[零〇一二两三四五六七八九十]{1,3}"


def _num(text: str) -> int:
    if text.isdigit():
        return int(text)
    if "十" in text:
        tens, _, ones = text.partition("十")
        return (_CN[tens] if tens else 1) * 10 + (_CN[ones] if ones else 0)
    return _CN[text[0]]


_ZH_PART = r"凌晨|清晨|早上|早晨|上午|中午|午后|下午|傍晚|晚上|夜里|夜间|半夜|今晚|明晚|明早|早|晚"
_ZH_TIME = re.compile(rf"({_ZH_PART})?\s*({_N})\s*(?:点钟|点|时|:|：)\s*(?:(半)|(一刻)|(三刻)|({_N})\s*分?)?")
_ZH_ALONE = {"凌晨": 6, "清晨": 7, "早上": 8, "早晨": 8, "明早": 8, "早": 8, "上午": 9, "中午": 12, "午后": 14,
             "下午": 15, "傍晚": 18, "晚上": 20, "今晚": 20, "明晚": 20, "晚": 20, "夜里": 22, "夜间": 22}
_LATER = ("下午", "午后", "傍晚", "晚上", "夜里", "夜间", "今晚", "明晚", "晚")
_EN_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_EN_DAY = r"(?:mon|tues?|wed(?:nes)?|thu(?:rs?)?|fri|sat(?:ur)?|sun)(?:day)?s?\b"
# Night words whose 12 o'clock is midnight and whose 1 to 4 o'clock is after it ("晚上12点", "夜里两点").
_NIGHT = ("晚上", "夜里", "夜间", "半夜", "今晚", "明晚", "晚")
_EN_ALONE = {"morning": 8, "noon": 12, "afternoon": 15, "evening": 20, "tonight": 20, "night": 21}


def _time_of(text: str) -> tuple[int, int] | None:
    """The time of day the words give, in 24 hours; None when they give none. An hour past 24 is that
    hour after the coming midnight ("今晚12点" is 24:00, the next day's 00:00)."""
    low = text.lower()
    # "7:30pm" before the Chinese reading, which would take "7:30" alone.
    hit = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\b\.?", low)
    if hit:
        h, m = int(hit.group(1)) % 12, int(hit.group(2) or 0)
        return (h + 12 if hit.group(3) == "p" else h), m
    hit = _ZH_TIME.search(text)
    if hit:
        part, h = hit.group(1) or "", _num(hit.group(2))
        m = 30 if hit.group(3) else 15 if hit.group(4) else 45 if hit.group(5) else \
            _num(hit.group(6)) if hit.group(6) else 0
        if part in _NIGHT and (h == 12 or 1 <= h <= 4):
            h = 24 + h % 12
        elif (part in _LATER and h < 12) or (part == "中午" and h < 11):
            h += 12
        elif part == "凌晨" and h == 12:
            h = 0
        if (h < 24 or part in _NIGHT) and m < 60:
            return h, m
    hit = re.search(r"\b(\d{1,2}):(\d{2})\b", low) or re.search(
        r"\bat\s+(\d{1,2})\b(?!\s*(?:minutes?|mins?|hours?|hrs?|days?|%))()", low)
    if hit:
        h, m = int(hit.group(1)), int(hit.group(2) or 0)
        if h < 12 and re.search(r"evening|tonight|night|afternoon", low):
            h += 12
        if h < 24 and m < 60:
            return h, m
    for word, hour in _ZH_ALONE.items():
        if word in text:
            return hour, 0
    for word, hour in _EN_ALONE.items():
        if re.search(rf"\b{word}\b", low):
            return hour, 0
    if "midnight" in low or "午夜" in text:
        return 0, 0
    return None


def _zh_days(text: str) -> list[int]:
    days: list[int] = []
    names = "一二三四五六日"
    for a, b in re.findall(r"([一二三四五六日天1-7])\s*(?:到|至|-|~|－)\s*(?:周|星期|礼拜)?([一二三四五六日天1-7])", text):
        x, y = (names.index(c.replace("天", "日")) if not c.isdigit() else int(c) - 1 for c in (a, b))
        days += list(range(x, y + 1)) if x <= y else []
    for c in re.findall(r"[一二三四五六日天1-7]", text):
        days.append(int(c) - 1 if c.isdigit() else names.index(c.replace("天", "日")))
    return sorted(set(days))


def _leap_day(text: str, today: datetime) -> date | None:
    """29 February in the words (which timewords leaves out in a year without one): that day in the year
    named, else the next year that has one."""
    if not re.search(r"(?:2|二)\s*月\s*(?:29|二十九)\s*[日号]|\bfeb(?:ruary)?\.?\s*29(?:th)?\b|\b29(?:th)?\s+(?:of\s+)?feb",
                     text, re.IGNORECASE):
        return None
    named = re.search(r"\b(20\d\d)\b|(20\d\d)\s*年", text)
    year = int(named.group(1) or named.group(2)) if named else today.year
    while True:
        try:
            day = date(year, 2, 29)
        except ValueError:
            year += 1
            continue
        if named or day >= today.date():
            return day
        year += 1


def parse_when(text: str, now: float, tz: tzinfo) -> dict | None:
    """The rhythm in the person's words ("明天下午三点", "每个工作日早上八点", "every 2 hours"), as a
    rule; None when the words name no time the app reads, and the model gives the rule instead."""
    text = unicodedata.normalize("NFKC", str(text or "")).strip()
    if not text:
        return None
    low = text.lower()
    hm = _time_of(text)
    clock = f"{hm[0] % 24:02d}:{hm[1]:02d}" if hm else "09:00"
    today = _wall(now, tz)

    if re.search(r"每年|\bevery\s+year\b|\beach\s+year\b|\byearly\b|\bannually\b", low):
        due = timewords.resolve_future(re.sub(r"每年|every\s+year|each\s+year|yearly|annually", "", text, flags=re.I),
                                       now, tz)
        if _leap_day(text, today):
            # 29 February each year: the 28th in a year without one.
            return {"repeat": "rrule", "time": clock, "rrule": "FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=29,-1;BYSETPOS=1",
                    "since": today.date().isoformat()}
        if due and due.kind == "exact":
            day = date.fromisoformat(due.due)
            return {"repeat": "rrule", "time": clock, "rrule": f"FREQ=YEARLY;BYMONTH={day.month};BYMONTHDAY={day.day}",
                    "since": today.date().isoformat()}
        return None
    # Every n weeks ("每两周的周一", "every other Monday"), counted from today's week.
    hit = re.search(rf"每(?:隔)?\s*({_N})\s*(?:个)?\s*(?:周|星期|礼拜)((?:\s*的?\s*(?:周|星期|礼拜)?[一二三四五六日天1-7])*)",
                    text)
    every = re.search(rf"\bevery\s+(other|\d+)\s*(?:weeks?\s*(?:on\s+)?)?((?:{_EN_DAY}\s*(?:,|and|&)?\s*)*)", low)
    n, days = 1, []
    if hit:
        n, days = _num(hit.group(1)), _zh_days(hit.group(2))
    elif every and (every.group(2) or "week" in every.group(0)):
        n = 2 if every.group(1) == "other" else int(every.group(1))
        days = sorted({_EN_DAYS.index(d[:3]) for d in re.findall(_EN_DAY, every.group(2))})
    if n > 1:
        days = days or [today.weekday()]
        names = ",".join(("MO", "TU", "WE", "TH", "FR", "SA", "SU")[d] for d in days)
        # Counted from the first of those days from today on, so "every other Monday" starts this coming one.
        first = next(today.date() + timedelta(days=k) for k in range(7) if (today.weekday() + k) % 7 in days)
        return {"repeat": "rrule", "time": clock, "rrule": f"FREQ=WEEKLY;INTERVAL={n};BYDAY={names}",
                "since": first.isoformat()}

    hit = re.search(rf"每(?:隔)?\s*({_N}|半)\s*(?:个)?\s*(分钟|分|小时|钟头|个钟)", text)
    if hit:
        n = 0.5 if hit.group(1) == "半" else _num(hit.group(1))
        return {"repeat": "every", "minutes": int(n * (1 if hit.group(2).startswith("分") else 60)), "anchor": now}
    if re.search(r"每(?:一)?分钟", text):
        return {"repeat": "every", "minutes": 1, "anchor": now}
    if re.search(r"每(?:一|个)?小时|每个钟", text):
        return {"repeat": "every", "minutes": 60, "anchor": now}
    hit = re.search(r"\bevery\s+(\d+|half\s+an?|an?)\s*(minutes?|mins?|hours?|hrs?)\b", low)
    if hit:
        n = 0.5 if hit.group(1).startswith("half") else 1 if hit.group(1) in ("a", "an") else int(hit.group(1))
        return {"repeat": "every", "minutes": int(n * (1 if hit.group(2).startswith("m") else 60)), "anchor": now}
    if re.search(r"\bhourly\b|\bevery\s+hour\b", low):
        return {"repeat": "every", "minutes": 60, "anchor": now}
    hit = re.search(rf"每隔\s*({_N})\s*天", text) or re.search(r"\bevery\s+(\d+)\s+days\b", low)
    if hit:
        return {"repeat": "rrule", "time": clock, "rrule": f"FREQ=DAILY;INTERVAL={_num(hit.group(1))}",
                "since": today.date().isoformat()}

    if re.search(r"工作日|周一(?:到|至|-|~)周五|星期一(?:到|至)星期五|\bweekdays?\b|monday\s+(?:to|through|-)\s+friday",
                 low):
        return {"repeat": "weekdays", "time": clock}
    if re.search(r"每(?:个)?(?:周末|星期六日)|\bweekends?\b", low):
        return {"repeat": "weekly", "days": [5, 6], "time": clock}
    hit = re.search(r"每(?:个)?(?:周|星期|礼拜)((?:\s*[、，,和与及到至\-~－]?\s*(?:周|星期|礼拜)?[一二三四五六日天1-7])*)", text)
    if hit:
        days = _zh_days(hit.group(1))
        # No day named ("每周", "每个星期二和第四周…"): a guess, which a rule from the model replaces.
        return {"repeat": "weekly", "days": days or [today.weekday()], "time": clock, "guess": not days}
    # "every Monday" and "on Mondays" repeat; "on Monday" is once, read below.
    hit = re.search(rf"\b(?:every\s+|on\s+(?=\w+days\b))({_EN_DAY}(?:\s*(?:,|and|&)\s*{_EN_DAY})*)", low)
    if hit:
        days = sorted({_EN_DAYS.index(d[:3]) for d in re.findall(_EN_DAY, hit.group(1))})
        return {"repeat": "weekly", "days": days, "time": clock}
    if re.search(r"\bweekly\b|\bevery\s+week\b", low):
        return {"repeat": "weekly", "days": [today.weekday()], "time": clock, "guess": True}

    hit = re.search(rf"每(?:个)?月\s*(?:的)?\s*({_N})\s*[号日]", text) or re.search(
        r"\b(?:every|each)\s+month\s+on\s+the\s+(\d{1,2})(?:st|nd|rd|th)?\b", low) or re.search(
        r"\bon\s+the\s+(\d{1,2})(?:st|nd|rd|th)?\s+of\s+(?:every|each)\s+month", low)
    if hit:
        return {"repeat": "monthly", "day": _num(hit.group(1)), "time": clock}
    if re.search(r"每(?:个)?月(?:的)?(?:最后一天|底|末)|月底|月末|last\s+day\s+of\s+(?:every|each|the)\s+month", low):
        return {"repeat": "monthly", "day": -1, "time": clock}
    if re.search(r"每(?:个)?月(?:初|第一天)|月初", text):
        return {"repeat": "monthly", "day": 1, "time": clock}
    if re.search(r"每(?:个)?月|\bmonthly\b|\bevery\s+month\b", low):
        return {"repeat": "monthly", "day": today.day, "time": clock, "guess": True}

    if re.search(r"每天|每日|天天|每晚|每早|每个?(?:早上|晚上|早晨|上午|下午|中午)|"
                 r"\bdaily\b|\bevery\s*day\b|\beach\s+day\b|\bevery\s+(?:morning|evening|night|afternoon)\b", low):
        return {"repeat": "daily", "time": clock}

    hit = re.search(rf"(?:({_N})\s*个\s*(?=半))?({_N}|半)\s*(?:个)?\s*(分钟|小时|钟头)\s*(?:后|以后|之后)", text)
    if hit:
        # "一个半小时后" is an hour and a half.
        n = (0.5 if hit.group(2) == "半" else _num(hit.group(2))) + (_num(hit.group(1)) if hit.group(1) else 0)
        return {"repeat": "once", "at": now + n * (60 if hit.group(3) == "分钟" else 3600)}
    hit = re.search(r"\bin\s+(\d+|half\s+an?|an?)\s*(minutes?|mins?|hours?|hrs?)\b", low)
    if hit:
        n = 0.5 if hit.group(1).startswith("half") else 1 if hit.group(1) in ("a", "an") else int(hit.group(1))
        return {"repeat": "once", "at": now + n * (60 if hit.group(2).startswith("m") else 3600)}

    day: date | None = None
    if re.search(r"今天|今晚|今早|\btoday\b|\btonight\b", low):
        day = today.date()
    else:
        due = timewords.resolve_future(text, now, tz)
        if due and due.kind == "exact":
            day = date.fromisoformat(due.due)
            if day == today.date() + timedelta(days=7) and hm and (hm[0] >= 24 or today.replace(
                    hour=hm[0], minute=hm[1]) > today) and not re.search(r"下|next", due.words, re.I):
                # A bare weekday that is today ("周五下午三点" said on Friday morning): today, while the time is ahead.
                day = today.date()
        day = day or _leap_day(text, today)
    if day is None and hm is None:
        return None
    h, m = hm or (9, 0)
    # A time of day alone ("九点"): a change to a repeating task keeps its rhythm at that time.
    bare = day is None
    if h >= 24:
        h -= 24
        day = day + timedelta(days=1) if day else None
    if day is None:
        day = today.date()
        if _epoch(datetime.combine(day, datetime.min.time()).replace(hour=h, minute=m), tz) <= now:
            day += timedelta(days=1)
    at = _epoch(datetime.combine(day, datetime.min.time()).replace(hour=h, minute=m), tz)
    return {"repeat": "once", "at": at, **({"bare": True} if bare else {})}


# ---- saying it back --------------------------------------------------------------

_ZH_WEEK = "一二三四五六日"
_EN_WEEK = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_EN_MONTH = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def when_text(at: float, tz: tzinfo, lang: str = "zh") -> str:
    """"11月21日 周六 08:00" / "Sat 21 Nov 08:00"."""
    wall = _wall(at, tz)
    # The year only when it is not this one.
    other = wall.year != _wall(life.clock(), tz).year
    if lang == "zh":
        return f"{f'{wall.year}年' if other else ''}{wall.month}月{wall.day}日 周{_ZH_WEEK[wall.weekday()]} {wall:%H:%M}"
    return f"{_EN_WEEK[wall.weekday()]} {wall.day} {_EN_MONTH[wall.month - 1]}{f' {wall.year}' if other else ''} {wall:%H:%M}"


def describe(rule: dict, tz: tzinfo, lang: str = "zh") -> str:
    """The rhythm in a few words: "每天 08:00", "每周一、三、五 08:00", "Every 2 hours"."""
    zh, repeat, clock = lang == "zh", rule["repeat"], rule.get("time", "")
    if repeat == "once":
        return ("仅一次 · " if zh else "Once · ") + when_text(rule["at"], tz, lang)
    if repeat == "every":
        n = int(rule["minutes"])
        if n % 60 == 0:
            return (f"每 {n // 60} 小时" if n > 60 else "每小时") if zh else \
                (f"Every {n // 60} hours" if n > 60 else "Hourly")
        return f"每 {n} 分钟" if zh else f"Every {n} minutes"
    if repeat == "daily":
        return f"每天 {clock}" if zh else f"Daily {clock}"
    if repeat == "weekdays":
        return f"每个工作日 {clock}" if zh else f"Weekdays {clock}"
    if repeat == "weekly":
        days = rule["days"]
        if len(days) == 7:
            return f"每天 {clock}" if zh else f"Daily {clock}"
        return ("每周" + "、".join(_ZH_WEEK[d] for d in days) + f" {clock}") if zh else \
            (", ".join(_EN_WEEK[d] for d in days) + f" {clock}")
    if repeat == "monthly":
        if rule["day"] == -1:
            return f"每月最后一天 {clock}" if zh else f"Last day of each month {clock}"
        return f"每月 {rule['day']} 日 {clock}" if zh else f"Monthly on day {rule['day']} {clock}"
    interval = re.search(r"FREQ=DAILY;INTERVAL=(\d+)$", rule["rrule"])
    if interval:
        return f"每 {interval.group(1)} 天 {clock}" if zh else f"Every {interval.group(1)} days {clock}"
    weeks = re.fullmatch(r"FREQ=WEEKLY;INTERVAL=(\d+);BYDAY=((?:MO|TU|WE|TH|FR|SA|SU)(?:,(?:MO|TU|WE|TH|FR|SA|SU))*)",
                         rule["rrule"])
    if weeks:
        days = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
        picked = [days.index(d) for d in weeks.group(2).split(",")]
        return (f"每 {weeks.group(1)} 周的周" + "、".join(_ZH_WEEK[d] for d in picked) + f" {clock}") if zh else \
            (f"Every {weeks.group(1)} weeks on " + ", ".join(_EN_WEEK[d] for d in picked) + f" {clock}")
    yearly = re.fullmatch(r"FREQ=YEARLY;BYMONTH=(\d+);BYMONTHDAY=(\d+)(?:,-1;BYSETPOS=1)?", rule["rrule"])
    if yearly:
        month, day = int(yearly.group(1)), int(yearly.group(2))
        return f"每年 {month}月{day}日 {clock}" if zh else f"Every year on {day} {_EN_MONTH[month - 1]} {clock}"
    return (f"自定义周期 {clock}（{rule['rrule']}）" if zh else f"Custom {clock} ({rule['rrule']})")


# ---- the store -----------------------------------------------------------------

def new_id() -> str:
    return uuid.uuid4().hex[:10]


class Store:
    """runtime/desktop/schedule.json: the tasks, the zone the times were worked out in, and which
    notices were shown. Only the page process writes it, and every change is written at once."""

    def __init__(self, runtime: Path) -> None:
        self.path = Path(runtime) / "desktop" / FILE
        # A file that cannot be read (edited by hand) is put aside, never written over.
        self.broken = False
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except OSError:
            data = {}
        except ValueError:
            data = None
        if not isinstance(data, dict) or not isinstance(data.get("tasks", []), list) or \
                not isinstance(data.get("told", {}), dict):
            self.path.replace(self.path.with_name("schedule.unreadable.json"))
            self.broken, data = True, {}
        self.data = data
        self.data.setdefault("tasks", [])
        self.data.setdefault("told", {})

    @property
    def tasks(self) -> list[dict]:
        return self.data["tasks"]

    def get(self, ident: str) -> dict | None:
        return next((t for t in self.tasks if t["id"] == ident), None)

    def save(self) -> None:
        atomic_write_text(self.path, json.dumps(self.data, ensure_ascii=False, indent=1))
