"""Time words in the ten chat languages, read without a model call.

`resolve("what did we do last week", now)` is the local-time range the
words name, or None; `resolve_future("下周三", said_at)` the day a plan
falls on. A wrong match only moves a ranking bonus; it never
writes anything. Bare weekday names ("on Saturday") are not read: too many
false positives. `NEGATION` serves the consolidation's negation check, where
a false hit can only refuse a change."""
from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime, timedelta, tzinfo
from typing import NamedTuple

from .ranking import day_label

Range = tuple[float, float]

_CJK_NUM = {"一": 1, "二": 2, "两": 2, "兩": 2, "三": 3, "四": 4, "五": 5,
            "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
_WORD_NUM = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
             "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "deux": 2, "trois": 3,
             "quatre": 4, "zwei": 2, "drei": 3, "vier": 4, "fünf": 5, "dois": 2,
             "duas": 2, "três": 3, "два": 2, "две": 2, "три": 3, "четыре": 4,
             "пять": 5}

#: Weekday words, Monday first.
_WEEKDAYS = {
    "en": ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
           "sunday"),
    "zh": ("一", "二", "三", "四", "五", "六", "日|天"),
    "ja": ("月", "火", "水", "木", "金", "土", "日"),
    "ko": ("월", "화", "수", "목", "금", "토", "일"),
    "es": ("lunes", "martes", "miércoles|miercoles", "jueves", "viernes",
           "sábado|sabado", "domingo"),
    "fr": ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi",
           "dimanche"),
    "de": ("montag", "dienstag", "mittwoch", "donnerstag", "freitag",
           "samstag|sonnabend", "sonntag"),
    "pt-BR": ("segunda(?:-feira)?", "terça(?:-feira)?|terca(?:-feira)?",
              "quarta(?:-feira)?", "quinta(?:-feira)?", "sexta(?:-feira)?",
              "sábado|sabado", "domingo"),
    "ru": ("понедельник", "вторник", "среду", "четверг", "пятницу", "субботу",
           "воскресенье"),
}
_WEEKDAYS["zh-TW"] = _WEEKDAYS["zh"]


def _alts(words) -> str:
    return "(" + "|".join(words) + ")"


def _wd(lang: str) -> str:
    return _alts(_WEEKDAYS[lang])


def _index(words: tuple, word: str, first: int = 0) -> int | None:
    """The place of `word` among `words` (each a regex of alternatives), counted from `first`; None if absent."""
    return next((i for i, alts in enumerate(words, first) if re.fullmatch(alts, word, re.IGNORECASE)), None)


def _first_hit(text: str, table: dict, langs: Iterable[str] | None, read):
    """`read(lang, handler, match)` of the first match in `text` it does not refuse: `langs` first, then every
    language; the earliest match wins, the longest at one place. None when none is read."""
    wanted = [lang for lang in (langs or ()) if lang in table]
    for group in ([wanted] if wanted else []) + [list(table)]:
        hits = [(m.start(), -(m.end() - m.start()), lang, handler, m)
                for lang in group for pat, handler in table[lang] for m in pat.finditer(text)]
        for *_, lang, handler, m in sorted(hits, key=lambda h: h[:2]):
            found = read(lang, handler, m)
            if found:
                return found
    return None


_N = r"(\d{1,2}|[一二两兩三四五六七八九十]{1,2})"
_EN_N = r"(\d{1,2}|two|three|four|five|six|seven)"

#: Per chat language: (pattern, kind). Kinds: today, morning, yesterday,
#: last_night, day_before, days_ago (group 1 = N), few_days, this_week,
#: last_week, last_weekend, last_weekday (group 1 = weekday), this_month,
#: last_month; week_before_last, weeks_ago and months_ago (group 1 = N, none
#: for "a").
_RULES: dict[str, list[tuple[str, str]]] = {
    "en": [
        (r"\btoday\b", "today"),
        (r"\b(?:this morning|earlier today)\b", "morning"),
        (r"\byesterday\b", "yesterday"),
        (r"\blast night\b", "last_night"),
        (r"\bthe day before yesterday\b", "day_before"),
        (rf"\b{_EN_N} days ago\b", "days_ago"),
        (r"\b(?:a few|a couple of|several) days ago\b", "few_days"),
        (r"\bthis week\b", "this_week"),
        (r"\blast week\b", "last_week"),
        (r"\blast weekend\b", "last_weekend"),
        (rf"\blast {_wd('en')}\b", "last_weekday"),
        (r"\bthe week before last\b", "week_before_last"),
        (rf"\b(?:a|{_EN_N}) weeks? ago\b", "weeks_ago"),
        (r"\bthis month\b", "this_month"),
        (r"\blast month\b", "last_month"),
        (rf"\b(?:a|{_EN_N}) months? ago\b", "months_ago"),
    ],
    "zh": [
        (r"今天|今日", "today"),
        (r"今早|今天早上|(?<![明后昨每])早上", "morning"),
        (r"昨天|昨日", "yesterday"),
        (r"昨晚|昨夜|昨天晚上", "last_night"),
        (r"前天", "day_before"),
        (rf"{_N}天(?:以)?前", "days_ago"),
        (r"前几天|前些天|几天前", "few_days"),
        (r"这周|这星期|这个星期|这礼拜|这个礼拜|本周", "this_week"),
        (r"上周(?![期末一二三四五六日天])|上个?星期(?![一二三四五六日天])"
         r"|上个?礼拜(?![一二三四五六日天])", "last_week"),
        (r"上周末|上个周末", "last_weekend"),
        (rf"(?:上周|上个?星期|上个?礼拜){_wd('zh')}", "last_weekday"),
        (r"上上周(?![末一二三四五六日天])|上上个?星期(?![一二三四五六日天])|上上个?礼拜(?![一二三四五六日天])",
         "week_before_last"),
        (rf"{_N}个?(?:周|星期|礼拜)(?:以)?前", "weeks_ago"),
        (r"这个月|这月|本月", "this_month"),
        (r"上个月|上月", "last_month"),
        (rf"{_N}个月(?:以)?前", "months_ago"),
    ],
    "zh-TW": [
        (r"今天|今日", "today"),
        (r"今早|今天早上", "morning"),
        (r"昨天|昨日", "yesterday"),
        (r"昨晚|昨夜|昨天晚上", "last_night"),
        (r"前天", "day_before"),
        (rf"{_N}天(?:以)?前", "days_ago"),
        (r"前幾天|前些天|幾天前", "few_days"),
        (r"這週|這周|這星期|這個星期|這禮拜|本週|本周", "this_week"),
        (r"上[週周](?![期末一二三四五六日天])|上個?星期(?![一二三四五六日天])"
         r"|上個?禮拜(?![一二三四五六日天])", "last_week"),
        (r"上[週周]末|上個週末", "last_weekend"),
        (rf"(?:上[週周]|上個?星期|上個?禮拜){_wd('zh-TW')}", "last_weekday"),
        (r"上上[週周](?![末一二三四五六日天])|上上個?星期(?![一二三四五六日天])|上上個?禮拜(?![一二三四五六日天])",
         "week_before_last"),
        (rf"{_N}個?(?:[週周]|星期|禮拜)(?:以)?前", "weeks_ago"),
        (r"這個月|本月", "this_month"),
        (r"上個月|上月", "last_month"),
        (rf"{_N}個月(?:以)?前", "months_ago"),
    ],
    "ja": [
        (r"今日|きょう", "today"),
        (r"今朝", "morning"),
        (r"(?<!一)昨日|きのう", "yesterday"),
        (r"昨夜|昨晩|ゆうべ", "last_night"),
        (r"一昨日|おととい", "day_before"),
        (rf"{_N}日前", "days_ago"),
        (r"数日前|何日か前", "few_days"),
        (r"今週", "this_week"),
        (r"先週(?!末|の?[月火水木金土日]曜)", "last_week"),
        (r"先週末", "last_weekend"),
        (rf"先週の?{_wd('ja')}曜", "last_weekday"),
        (r"今月", "this_month"),
        (r"先月", "last_month"),
    ],
    "ko": [
        (r"오늘", "today"),
        (r"오늘\s*아침", "morning"),
        (r"어제(?!밤)", "yesterday"),
        (r"어젯밤|어제\s*밤", "last_night"),
        (r"그저께|그제", "day_before"),
        (r"(\d{1,2})\s*일\s*전", "days_ago"),
        (r"며칠\s*전", "few_days"),
        (r"이번\s*주(?!말)", "this_week"),
        (r"지난\s*주(?!말)", "last_week"),
        (r"지난\s*주말", "last_weekend"),
        (rf"지난\s*주?\s*{_wd('ko')}요일", "last_weekday"),
        (r"이번\s*달", "this_month"),
        (r"지난\s*달", "last_month"),
    ],
    "es": [
        (r"\bhoy\b", "today"),
        (r"\besta mañana\b", "morning"),
        (r"\bayer\b", "yesterday"),
        (r"\banoche\b", "last_night"),
        (r"\b(?:anteayer|antier|antes de ayer)\b", "day_before"),
        (r"\bhace (\d{1,2}|dos|tres|cuatro|cinco) días\b", "days_ago"),
        (r"\bhace (?:unos|unos pocos|algunos) días\b", "few_days"),
        (r"\besta semana\b", "this_week"),
        (r"\bla semana pasada\b", "last_week"),
        (r"\bel fin de semana pasado\b", "last_weekend"),
        (rf"\bel {_wd('es')} pasado\b", "last_weekday"),
        (r"\beste mes\b", "this_month"),
        (r"\bel mes pasado\b", "last_month"),
    ],
    "fr": [
        (r"\baujourd'hui\b|\baujourd’hui\b", "today"),
        (r"\bce matin\b", "morning"),
        (r"(?<![-\w])hier(?! soir)\b", "yesterday"),
        (r"\bhier soir\b", "last_night"),
        (r"\bavant-hier\b", "day_before"),
        (r"\bil y a (\d{1,2}|deux|trois|quatre) jours\b", "days_ago"),
        (r"\bil y a quelques jours\b", "few_days"),
        (r"\bcette semaine\b", "this_week"),
        (r"\bla semaine dernière\b", "last_week"),
        (r"\b(?:le )?week-?end dernier\b", "last_weekend"),
        (rf"\b{_wd('fr')} dernier\b", "last_weekday"),
        (r"\bce mois-ci\b", "this_month"),
        (r"\ble mois dernier\b", "last_month"),
    ],
    "de": [
        (r"\bheute\b(?! morgen)", "today"),
        (r"\bheute morgen\b|\bheute früh\b", "morning"),
        (r"\bgestern\b(?! abend)", "yesterday"),
        (r"\bgestern abend\b", "last_night"),
        (r"\bvorgestern\b", "day_before"),
        (r"\bvor (\d{1,2}|zwei|drei|vier|fünf) tagen\b", "days_ago"),
        (r"\bvor (?:ein paar|einigen) tagen\b", "few_days"),
        (r"\bdiese woche\b", "this_week"),
        (r"\bletzte woche\b", "last_week"),
        (r"\bletztes wochenende\b", "last_weekend"),
        (rf"\bletzten {_wd('de')}\b", "last_weekday"),
        (r"\bdiesen monat\b", "this_month"),
        (r"\bletzten monat\b", "last_month"),
    ],
    "pt-BR": [
        (r"\bhoje\b(?! de manhã| cedo)", "today"),
        (r"\bhoje de manhã\b|\bhoje cedo\b", "morning"),
        (r"\bontem\b(?! à noite| a noite)", "yesterday"),
        (r"\bontem à noite\b|\bontem a noite\b", "last_night"),
        (r"\banteontem\b", "day_before"),
        (r"\bhá (\d{1,2}|dois|duas|três) dias\b|\b(\d{1,2}) dias atrás\b", "days_ago"),
        (r"\bhá (?:alguns|uns) dias\b|\balguns dias atrás\b", "few_days"),
        (r"\b(?:esta|essa) semana\b", "this_week"),
        (r"\bsemana passada\b", "last_week"),
        (r"\bfim de semana passado\b", "last_weekend"),
        (rf"\b{_wd('pt-BR')} passad[ao]\b", "last_weekday"),
        (r"\b(?:este|esse) mês\b", "this_month"),
        (r"\bmês passado\b", "last_month"),
    ],
    "ru": [
        (r"\bсегодня\b(?! утром)", "today"),
        (r"\bсегодня утром\b", "morning"),
        (r"\bвчера\b(?! вечером)", "yesterday"),
        (r"\bвчера вечером\b", "last_night"),
        (r"\bпозавчера\b", "day_before"),
        (r"\b(\d{1,2}|два|две|три|четыре|пять) (?:дня|дней) назад\b", "days_ago"),
        (r"\bнесколько дней назад\b", "few_days"),
        (r"\bна этой неделе\b", "this_week"),
        (r"\bна прошлой неделе\b", "last_week"),
        (r"\bв прошлые выходные\b", "last_weekend"),
        (rf"\bв прошл(?:ый|ую|ое) {_wd('ru')}\b", "last_weekday"),
        (r"\bв этом месяце\b", "this_month"),
        (r"\bв прошлом месяце\b", "last_month"),
    ],
}

#: Compiled per language; the keys are chatlangs.SPECS's.
TABLE: dict[str, list[tuple[re.Pattern, str]]] = {
    lang: [(re.compile(p, re.IGNORECASE), kind) for p, kind in rules]
    for lang, rules in _RULES.items()}

NEGATION = re.compile(
    r"\b(?:not|never|no longer|nobody|nothing)\b|n['’]t\b"
    r"|[不没沒别別未非]"
    r"|ない|ません|じゃない"
    r"|(?:^|\s)안(?=\s)|않|못"
    r"|\b(?:no|nunca|ya no|jamás|ni)\b"
    r"|\b(?:ne|n['’]|pas|jamais|plus|aucun|aucune)\b"
    r"|\b(?:nicht|kein\w*|nie|niemals)\b"
    r"|\b(?:não|nem)\b"
    r"|\b(?:не|нет|никогда|ни)\b",
    re.IGNORECASE)


def has_negation(text: str) -> bool:
    return bool(NEGATION.search(str(text or "")))


def _int(raw: str) -> int | None:
    """1 to 99 in digits, in Chinese numerals ("十五", "二十三") or in words."""
    raw = (raw or "").strip().lower()
    if raw.isdigit():
        return int(raw)
    if raw in _WORD_NUM:
        return _WORD_NUM[raw]
    if raw and all(ch in _CJK_NUM for ch in raw):
        if "十" not in raw:
            return _CJK_NUM[raw] if len(raw) == 1 else None
        tens, _, ones = raw.partition("十")
        if len(tens) > 1 or len(ones) > 1:
            return None
        return (_CJK_NUM[tens] if tens else 1) * 10 + (_CJK_NUM[ones] if ones else 0)
    return None


def _weekday(lang: str, word: str) -> int | None:
    return _index(_WEEKDAYS[lang], word)


def _range(kind: str, m: re.Match, lang: str, now_dt: datetime) -> tuple[datetime, datetime] | None:
    day0 = now_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    day = timedelta(days=1)
    monday = day0 - timedelta(days=day0.weekday())
    if kind == "today":
        return day0, now_dt
    if kind == "morning":
        return day0, min(day0 + timedelta(hours=12), now_dt)
    if kind == "yesterday":
        return day0 - day, day0
    if kind == "last_night":
        return day0 - day + timedelta(hours=18), day0 + timedelta(hours=6)
    if kind == "day_before":
        return day0 - 2 * day, day0 - day
    if kind == "days_ago":
        n = _int(next((g for g in m.groups() if g), ""))
        if not n or n > 60:
            return None
        return day0 - n * day, day0 - (n - 1) * day
    if kind == "few_days":
        return day0 - 6 * day, day0 - day
    if kind == "this_week":
        return monday, now_dt
    if kind == "last_week":
        return monday - 7 * day, monday
    if kind == "last_weekend":
        return monday - 2 * day, monday
    if kind == "last_weekday":
        wd = _weekday(lang, m.group(1) or "")
        if wd is None:
            return None
        start = monday - 7 * day + wd * day
        return start, start + day
    if kind == "this_month":
        return day0.replace(day=1), now_dt
    if kind == "last_month":
        first = day0.replace(day=1)
        prev = (first - day).replace(day=1)
        return prev, first
    if kind == "week_before_last":
        return monday - 14 * day, monday - 7 * day
    if kind in ("weeks_ago", "months_ago"):
        # About N weeks (three days either way) or N months (half a month either way) back; "a" is one.
        raw = next((g for g in m.groups() if g), "")
        n = _int(raw) if raw else 1
        if not n or n > 12:
            return None
        middle, half = (7 * n, 3) if kind == "weeks_ago" else (30 * n, 15)
        return day0 - (middle + half) * day, day0 - (middle - half - 1) * day
    return None


def resolve(text: str, now: float, tz: tzinfo | None = None,
            langs: Iterable[str] | None = None) -> Range | None:
    """(start, end) epoch seconds of the first time words in `text`, read in
    `langs` first and then in every language; None when there are none.
    Days are local to `tz` (the system's when None)."""
    text = str(text or "")
    if not text.strip():
        return None
    now_dt = datetime.fromtimestamp(now, tz)
    span = _first_hit(text, TABLE, langs, lambda lang, kind, m: _range(kind, m, lang, now_dt))
    return (span[0].timestamp(), span[1].timestamp()) if span else None


def phrase(span: Range, lang: str = "en", tz: tzinfo | None = None) -> str:
    """The range in the prompt's internal English: "Mon 3 Nov" or
    "Mon 3 Nov to Sun 9 Nov"."""
    start, end = span
    last = max(start, end - 1)
    if day_label(start, tz) == day_label(last, tz):
        return day_label(start, tz)
    return f"{day_label(start, tz)} to {day_label(last, tz)}"


# ---- the days ahead: when a plan is due ----------------------------------------

class Due(NamedTuple):
    """When a plan falls: `due` (an ISO day), how sure ("exact"; "approx" for
    early/mid/late in a month or "in a few days"; "range" for a weekend, a
    week or a month), the last day of an approx or range one, and the
    words that said it."""
    due: str
    kind: str
    until: str = ""
    words: str = ""


_MONTHS = {
    "en": ("jan(?:uary)?", "feb(?:ruary)?", "mar(?:ch)?", "apr(?:il)?", "may",
           "june?", "july?", "aug(?:ust)?", "sep(?:t(?:ember)?)?", "oct(?:ober)?",
           "nov(?:ember)?", "dec(?:ember)?"),
    "es": ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
           "agosto", "septiembre|setiembre", "octubre", "noviembre", "diciembre"),
    "fr": ("janvier", "février|fevrier", "mars", "avril", "mai", "juin",
           "juillet", "août|aout", "septembre", "octobre", "novembre",
           "décembre|decembre"),
    "de": ("januar", "februar", "märz|maerz", "april", "mai", "juni", "juli",
           "august", "september", "oktober", "november", "dezember"),
    "pt-BR": ("janeiro", "fevereiro", "março|marco", "abril", "maio", "junho",
              "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"),
    "ru": ("января", "февраля", "марта", "апреля", "мая", "июня", "июля",
           "августа", "сентября", "октября", "ноября", "декабря"),
}
# Weekday words said of a day ahead: Russian takes the accusative.
_AHEAD_WEEKDAYS = dict(_WEEKDAYS)
_AHEAD_WEEKDAYS["ru"] = ("понедельник", "вторник", "среду|среда", "четверг",
                         "пятницу|пятница", "субботу|суббота", "воскресенье")


def _month_of(lang: str, word: str) -> int | None:
    return _index(_MONTHS[lang], word, 1)


def _ahead_weekday(lang: str, word: str) -> int | None:
    return _index(_AHEAD_WEEKDAYS[lang], word)


def _end_of_month(d):
    return (d.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


def _month_start(today, months_ahead: int):
    y, m = today.year, today.month + months_ahead
    return today.replace(year=y + (m - 1) // 12, month=(m - 1) % 12 + 1, day=1)


def _day(d) -> Due | None:
    return Due(d.isoformat(), "exact") if d else None


def _span(a, b, kind: str = "range") -> Due:
    return Due(a.isoformat(), kind, b.isoformat())


def _week_day(today, wd: int | None, weeks: int):
    """Weekday `wd` (Monday 0) of the week `weeks` after this one."""
    if wd is None:
        return None
    return today - timedelta(days=today.weekday()) + timedelta(days=7 * weeks + wd)


def _next_weekday(today, wd: int | None):
    """The next `wd` after today: said on a Monday, "Monday" is a week on."""
    if wd is None:
        return None
    return today + timedelta(days=(wd - today.weekday()) % 7 or 7)


def _this_weekday(today, wd: int | None):
    """`wd` of this week, or of the next once it has gone by."""
    d = _week_day(today, wd, 0)
    return d if d is None or d >= today else d + timedelta(days=7)


def _dated(today, month: int | None, day: int | None):
    """That day this year, or next year once it has gone by."""
    if not month or not day:
        return None
    try:
        d = today.replace(month=month, day=day)
        return d if d >= today else d.replace(year=today.year + 1)
    except ValueError:
        return None


def _nth(today, day: int | None):
    """The next `day`-th of a month, this month's while it is still ahead."""
    if not day or not 1 <= day <= 31:
        return None
    for ahead in range(3):
        start = _month_start(today, ahead)
        if day <= _end_of_month(start).day and start.replace(day=day) >= today:
            return start.replace(day=day)
    return None


_PARTS = {"early": (1, 7), "mid": (11, 20), "late": (21, 31)}


def _part(today, month: int | None, part: str, *, roll: bool = True):
    """Early, mid or late in `month`: this year's, or next year's once over."""
    if not month or not 1 <= month <= 12:
        return None
    start = today.replace(month=month, day=1)
    if roll and _end_of_month(start) < today:
        start = start.replace(year=today.year + 1)
    a, b = _PARTS[part]
    return _span(start.replace(day=a), start.replace(day=min(b, _end_of_month(start).day)), "approx")


def _part_ahead(today, part: str, months_ahead: int | None = None):
    """Early/mid/late in a month said without its name: "月初" said late in
    a month is the next one's start."""
    if months_ahead is None:
        months_ahead = int((part == "early" and today.day > 7) or (part == "mid" and today.day > 20))
    start = _month_start(today, months_ahead)
    return _part(start, start.month, part, roll=False)


def _weekend(today, weeks: int):
    sat = _week_day(today, 5, weeks)
    if weeks == 0 and sat + timedelta(days=1) < today:
        sat += timedelta(days=7)
    return _span(sat, sat + timedelta(days=1))


def _week(today, weeks: int):
    mon = _week_day(today, 0, weeks)
    return _span(mon, mon + timedelta(days=6))


def _month(today, months_ahead: int):
    start = _month_start(today, months_ahead)
    return _span(start, _end_of_month(start))


def _in_days(today, n: int | None):
    return _day(today + timedelta(days=n)) if n and 0 < n <= 400 else None


def _few_days(today):
    return _span(today + timedelta(days=2), today + timedelta(days=5), "approx")


def _in_weeks(today, n: int | None):
    """"两周后": about n weeks on, three days either way."""
    if not n or not 0 < n <= 52:
        return None
    mid = today + timedelta(days=7 * n)
    return _span(mid - timedelta(days=3), mid + timedelta(days=3), "approx")


def _next_year_month(today, month: int | None):
    if not month or not 1 <= month <= 12:
        return None
    return _month(today.replace(year=today.year + 1, month=month, day=1), 0)


def _in_next_month(today, day: int | None):
    start = _month_start(today, 1)
    return _day(start.replace(day=day)) if day and 1 <= day <= _end_of_month(start).day else None


_ZN = r"(\d{1,2}|[一二两兩三四五六七八九十]{1,3})"
_ZWD = r"([一二三四五六日天])"
_ZWEEK = r"(?:周|星期|礼拜|週|禮拜)"
_ZPART = {"初": "early", "上旬": "early", "中": "mid", "中旬": "mid", "底": "late",
          "末": "late", "下旬": "late"}
_JPART = {"初め": "early", "上旬": "early", "中旬": "mid", "下旬": "late", "末": "late"}


def _zwd(word: str) -> int:
    return "一二三四五六".find(word) if word in "一二三四五六" else 6


def _late_or(word: str, table: dict) -> str:
    return table.get(word.lower(), "late")


# (pattern, handler(match, today)) per language; the earliest match in the
# text wins, the longest at one place, and one that names no day gives way.
_AHEAD: dict[str, list[tuple[str, object]]] = {
    "zh": [
        (r"大后天|大後天", lambda m, t: _in_days(t, 3)),
        (r"(?<!大)后天|(?<!大)後天", lambda m, t: _in_days(t, 2)),
        (r"明天|明日|明早|明晚|明儿", lambda m, t: _in_days(t, 1)),
        (r"今天|今晚|今早|今日|今儿", lambda m, t: _day(t)),
        (rf"下下个?{_ZWEEK}{_ZWD}", lambda m, t: _day(_week_day(t, _zwd(m.group(1)), 2))),
        (rf"(?<!下)下个?{_ZWEEK}{_ZWD}", lambda m, t: _day(_week_day(t, _zwd(m.group(1)), 1))),
        (rf"(?:这|這|本)个?{_ZWEEK}{_ZWD}", lambda m, t: _day(_this_weekday(t, _zwd(m.group(1))))),
        (rf"(?<![上下这這本个個]){_ZWEEK}{_ZWD}", lambda m, t: _day(_next_weekday(t, _zwd(m.group(1))))),
        (r"下个?(?:周末|週末)", lambda m, t: _weekend(t, 1)),
        (r"(?<![上下])(?:这个?|這個?|本)?(?:周末|週末)", lambda m, t: _weekend(t, 0)),
        (rf"下下个?{_ZWEEK}(?![一二三四五六日天末])", lambda m, t: _week(t, 2)),
        (rf"(?<![上下])下个?{_ZWEEK}(?![一二三四五六日天末])", lambda m, t: _week(t, 1)),
        (rf"(?:过|過){_ZN}个?{_ZWEEK}|{_ZN}个?{_ZWEEK}(?:之|以)?[后後]",
         lambda m, t: _in_weeks(t, _int(m.group(1) or m.group(2)))),
        (rf"下个?月{_ZN}(?:号|號|日)", lambda m, t: _in_next_month(t, _int(m.group(1)))),
        (r"下个?月(初|上旬|中旬|中|底|末|下旬)", lambda m, t: _part_ahead(t, _ZPART[m.group(1)], 1)),
        (r"下个?月(?![初中底末上下\d一二三四五六七八九十])", lambda m, t: _month(t, 1)),
        (rf"明年{_ZN}月", lambda m, t: _next_year_month(t, _int(m.group(1)))),
        (rf"{_ZN}月{_ZN}(?:号|號|日)?", lambda m, t: _day(_dated(t, _int(m.group(1)), _int(m.group(2))))),
        (rf"{_ZN}月(初|上旬|中旬|中|底|末|下旬)", lambda m, t: _part(t, _int(m.group(1)), _ZPART[m.group(2)])),
        (r"(?<![月\d])(\d{1,2})(?:号|號|日)|(?<![月\d一二三四五六七八九十])([一二三四五六七八九十]{1,3})(?:号|號)",
         lambda m, t: _day(_nth(t, _int(m.group(1) or m.group(2))))),
        (r"(?<!下)(?<!下个)(?:这个|這個|本)?月(初|中旬|中|底|末)(?![\d一二三四五六七八九十])",
         lambda m, t: _part_ahead(t, _ZPART[m.group(1)])),
        (r"年底|年末", lambda m, t: _span(t.replace(month=12, day=20), t.replace(month=12, day=31), "approx")),
        (rf"{_ZN}天(?:之|以)?[后後]", lambda m, t: _in_days(t, _int(m.group(1)))),
        (r"过几天|過幾天|过两天|過兩天|几天[后後]|幾天[后後]", lambda m, t: _few_days(t)),
    ],
    "en": [
        (r"\bthe day after tomorrow\b", lambda m, t: _in_days(t, 2)),
        (r"\btomorrow\b", lambda m, t: _in_days(t, 1)),
        (r"\b(?:today|tonight|this (?:morning|afternoon|evening))\b", lambda m, t: _day(t)),
        (rf"\bnext {_alts(_WEEKDAYS['en'])}\b", lambda m, t: _day(_week_day(t, _weekday('en', m.group(1)), 1))),
        (rf"\bthis (?:coming )?{_alts(_WEEKDAYS['en'])}\b",
         lambda m, t: _day(_this_weekday(t, _weekday('en', m.group(1))))),
        (rf"(?<!last )(?<!next )(?<!this )(?<!coming )\b{_alts(_WEEKDAYS['en'])}\b",
         lambda m, t: _day(_next_weekday(t, _weekday('en', m.group(1))))),
        (r"\bnext weekend\b", lambda m, t: _weekend(t, 1)),
        (r"\b(?:this|the) weekend\b", lambda m, t: _weekend(t, 0)),
        (r"\bnext week\b", lambda m, t: _week(t, 1)),
        (r"\bnext month\b", lambda m, t: _month(t, 1)),
        (rf"\bin {_EN_N} days\b", lambda m, t: _in_days(t, _int(m.group(1)))),
        (r"\bin a (?:few|couple of) days\b", lambda m, t: _few_days(t)),
        (rf"\bin {_EN_N} weeks?\b", lambda m, t: _in_weeks(t, _int(m.group(1)))),
        (r"\bin a week\b", lambda m, t: _in_weeks(t, 1)),
        (rf"\b(early|mid|late|end of)[ -](?:in )?{_alts(_MONTHS['en'])}\b", lambda m, t: _part(
            t, _month_of('en', m.group(2)), _late_or(m.group(1), {"early": "early", "mid": "mid"}))),
        (rf"\b{_alts(_MONTHS['en'])}\.? (\d{{1,2}})(?:st|nd|rd|th)?\b",
         lambda m, t: _day(_dated(t, _month_of('en', m.group(1)), int(m.group(2))))),
        (rf"\b(\d{{1,2}})(?:st|nd|rd|th)? (?:of )?{_alts(_MONTHS['en'])}\b",
         lambda m, t: _day(_dated(t, _month_of('en', m.group(2)), int(m.group(1))))),
        (r"\b(?:the )?end of (?:the|this) month\b", lambda m, t: _part_ahead(t, "late", 0)),
        (r"\bthe (\d{1,2})(?:st|nd|rd|th)\b", lambda m, t: _day(_nth(t, int(m.group(1))))),
    ],
    "ja": [
        (r"明後日|あさって", lambda m, t: _in_days(t, 2)),
        (r"明日|あした|あす", lambda m, t: _in_days(t, 1)),
        (r"今日|今夜|今晩|きょう", lambda m, t: _day(t)),
        (rf"再来週の?{_wd('ja')}曜", lambda m, t: _day(_week_day(t, _weekday('ja', m.group(1)), 2))),
        (rf"(?<!再)来週の?{_wd('ja')}曜", lambda m, t: _day(_week_day(t, _weekday('ja', m.group(1)), 1))),
        (rf"今週の?{_wd('ja')}曜", lambda m, t: _day(_this_weekday(t, _weekday('ja', m.group(1))))),
        (rf"(?<![週の]){_wd('ja')}曜日?", lambda m, t: _day(_next_weekday(t, _weekday('ja', m.group(1))))),
        (r"来週末", lambda m, t: _weekend(t, 1)),
        (r"(?<![先来])(?:今週末|週末)", lambda m, t: _weekend(t, 0)),
        (r"来週(?![の月火水木金土日末])", lambda m, t: _week(t, 1)),
        (r"来月", lambda m, t: _month(t, 1)),
        (r"(\d{1,2})月(\d{1,2})日", lambda m, t: _day(_dated(t, int(m.group(1)), int(m.group(2))))),
        (r"(\d{1,2})月(初め|上旬|中旬|下旬|末)", lambda m, t: _part(t, int(m.group(1)), _JPART[m.group(2)])),
        (r"(?<![月\d])(\d{1,2})日(?!前|後|間)", lambda m, t: _day(_nth(t, int(m.group(1))))),
        (r"(\d{1,2})日後", lambda m, t: _in_days(t, int(m.group(1)))),
        (r"数日後", lambda m, t: _few_days(t)),
    ],
    "ko": [
        (r"글피", lambda m, t: _in_days(t, 3)),
        (r"모레", lambda m, t: _in_days(t, 2)),
        (r"내일", lambda m, t: _in_days(t, 1)),
        (r"오늘", lambda m, t: _day(t)),
        (rf"다다음\s*주\s*{_wd('ko')}요일", lambda m, t: _day(_week_day(t, _weekday('ko', m.group(1)), 2))),
        (rf"(?<!다)다음\s*주\s*{_wd('ko')}요일", lambda m, t: _day(_week_day(t, _weekday('ko', m.group(1)), 1))),
        (rf"이번\s*주\s*{_wd('ko')}요일", lambda m, t: _day(_this_weekday(t, _weekday('ko', m.group(1))))),
        (rf"(?<![주\s]){_wd('ko')}요일", lambda m, t: _day(_next_weekday(t, _weekday('ko', m.group(1))))),
        (r"다음\s*주말", lambda m, t: _weekend(t, 1)),
        (r"(?<!지난)(?<!지난\s)(?<!다음)(?<!다음\s)(?:이번\s*)?주말", lambda m, t: _weekend(t, 0)),
        (r"다음\s*주(?!\s*[월화수목금토일말])", lambda m, t: _week(t, 1)),
        (r"다음\s*달", lambda m, t: _month(t, 1)),
        (r"(\d{1,2})월\s*(\d{1,2})일", lambda m, t: _day(_dated(t, int(m.group(1)), int(m.group(2))))),
        (r"(\d{1,2})월\s*(초|중순|말)", lambda m, t: _part(
            t, int(m.group(1)), _late_or(m.group(2), {"초": "early", "중순": "mid"}))),
        (r"(?<![월\d\s])(\d{1,2})일(?!\s*(?:전|후|뒤|동안))", lambda m, t: _day(_nth(t, int(m.group(1))))),
        (r"(\d{1,2})\s*일\s*(?:후|뒤)", lambda m, t: _in_days(t, int(m.group(1)))),
        (r"며칠\s*(?:후|뒤)", lambda m, t: _few_days(t)),
    ],
    "es": [
        (r"\bpasado mañana\b", lambda m, t: _in_days(t, 2)),
        (r"(?<!pasado )\bmañana\b", lambda m, t: _in_days(t, 1)),
        (r"\b(?:hoy|esta noche|esta tarde)\b", lambda m, t: _day(t)),
        (rf"\b(?:el )?(?:próximo|proximo) {_wd('es')}\b|\bel {_wd('es')} que viene\b",
         lambda m, t: _day(_week_day(t, _weekday('es', m.group(1) or m.group(2)), 1))),
        (rf"\beste {_wd('es')}\b", lambda m, t: _day(_this_weekday(t, _weekday('es', m.group(1))))),
        (rf"\b(?:el|los) {_wd('es')}\b(?! pasado| que viene)",
         lambda m, t: _day(_next_weekday(t, _weekday('es', m.group(1))))),
        (r"\bel (?:próximo|proximo) fin de semana\b|\bel fin de semana que viene\b", lambda m, t: _weekend(t, 1)),
        (r"\beste fin de semana\b|\bel fin de semana\b(?! pasado)", lambda m, t: _weekend(t, 0)),
        (r"\bla (?:próxima|proxima) semana\b|\bla semana que viene\b", lambda m, t: _week(t, 1)),
        (r"\bel (?:próximo|proximo) mes\b|\bel mes que viene\b", lambda m, t: _month(t, 1)),
        (r"\b(?:en|dentro de) (\d{1,2}|dos|tres|cuatro|cinco) días\b", lambda m, t: _in_days(t, _int(m.group(1)))),
        (r"\ben unos (?:pocos )?días\b", lambda m, t: _few_days(t)),
        (rf"\ba (principios|mediados|finales) de {_alts(_MONTHS['es'])}\b", lambda m, t: _part(
            t, _month_of('es', m.group(2)), _late_or(m.group(1), {"principios": "early", "mediados": "mid"}))),
        (rf"\b(\d{{1,2}}) de {_alts(_MONTHS['es'])}\b",
         lambda m, t: _day(_dated(t, _month_of('es', m.group(2)), int(m.group(1))))),
        (r"\bel (?:día )?(\d{1,2})\b(?! de)", lambda m, t: _day(_nth(t, int(m.group(1))))),
    ],
    "fr": [
        (r"\baprès-demain\b|\bapres-demain\b", lambda m, t: _in_days(t, 2)),
        (r"(?<!-)\bdemain\b", lambda m, t: _in_days(t, 1)),
        (r"\baujourd['’]hui\b|\bce soir\b", lambda m, t: _day(t)),
        (rf"\b{_wd('fr')} prochain\b", lambda m, t: _day(_week_day(t, _weekday('fr', m.group(1)), 1))),
        (rf"\bce {_wd('fr')}\b", lambda m, t: _day(_this_weekday(t, _weekday('fr', m.group(1))))),
        (rf"(?<!ce )\b{_wd('fr')}\b(?! prochain| dernier)",
         lambda m, t: _day(_next_weekday(t, _weekday('fr', m.group(1))))),
        (r"\ble week-?end prochain\b", lambda m, t: _weekend(t, 1)),
        (r"\bce week-?end\b", lambda m, t: _weekend(t, 0)),
        (r"\bla semaine prochaine\b", lambda m, t: _week(t, 1)),
        (r"\ble mois prochain\b", lambda m, t: _month(t, 1)),
        (r"\bdans (\d{1,2}|deux|trois|quatre) jours\b", lambda m, t: _in_days(t, _int(m.group(1)))),
        (r"\bdans quelques jours\b", lambda m, t: _few_days(t)),
        (rf"\b(début|debut|mi|fin)[ -]{_alts(_MONTHS['fr'])}\b", lambda m, t: _part(
            t, _month_of('fr', m.group(2)), _late_or(m.group(1), {"début": "early", "debut": "early", "mi": "mid"}))),
        (rf"\b(\d{{1,2}})(?:er)? {_alts(_MONTHS['fr'])}\b",
         lambda m, t: _day(_dated(t, _month_of('fr', m.group(2)), int(m.group(1))))),
        (r"\ble (\d{1,2})\b(?! jours)", lambda m, t: _day(_nth(t, int(m.group(1))))),
    ],
    "de": [
        (r"\bübermorgen\b", lambda m, t: _in_days(t, 2)),
        (r"(?<!heute )\bmorgen\b(?! früh)", lambda m, t: _in_days(t, 1)),
        (r"\bheute\b", lambda m, t: _day(t)),
        (rf"\bnächste[nm]? {_wd('de')}\b|\bnächste woche {_wd('de')}\b",
         lambda m, t: _day(_week_day(t, _weekday('de', m.group(1) or m.group(2)), 1))),
        (rf"\bdiese[nm]? {_wd('de')}\b", lambda m, t: _day(_this_weekday(t, _weekday('de', m.group(1))))),
        (rf"\bam {_wd('de')}\b", lambda m, t: _day(_next_weekday(t, _weekday('de', m.group(1))))),
        (r"\bnächstes wochenende\b", lambda m, t: _weekend(t, 1)),
        (r"\b(?:am|dieses) wochenende\b", lambda m, t: _weekend(t, 0)),
        (r"\bnächste woche\b", lambda m, t: _week(t, 1)),
        (r"\bnächsten monat\b", lambda m, t: _month(t, 1)),
        (r"\bin (\d{1,2}|zwei|drei|vier|fünf) tagen\b", lambda m, t: _in_days(t, _int(m.group(1)))),
        (r"\bin ein paar tagen\b", lambda m, t: _few_days(t)),
        (rf"\b(anfang|mitte|ende) {_alts(_MONTHS['de'])}\b", lambda m, t: _part(
            t, _month_of('de', m.group(2)), _late_or(m.group(1), {"anfang": "early", "mitte": "mid"}))),
        (rf"\b(\d{{1,2}})\. ?{_alts(_MONTHS['de'])}\b",
         lambda m, t: _day(_dated(t, _month_of('de', m.group(2)), int(m.group(1))))),
        (r"\bam (\d{1,2})\.", lambda m, t: _day(_nth(t, int(m.group(1))))),
    ],
    "pt-BR": [
        (r"\bdepois de amanhã\b", lambda m, t: _in_days(t, 2)),
        (r"(?<!de )\bamanhã\b", lambda m, t: _in_days(t, 1)),
        (r"\bhoje\b", lambda m, t: _day(t)),
        (rf"\b(?:na |no )?(?:próxima|próximo|proxima|proximo) {_wd('pt-BR')}|\b{_wd('pt-BR')} que vem\b",
         lambda m, t: _day(_week_day(t, _weekday('pt-BR', m.group(1) or m.group(2)), 1))),
        (rf"\b(?:nesta|nessa|neste|nesse|esta|essa) {_wd('pt-BR')}",
         lambda m, t: _day(_this_weekday(t, _weekday('pt-BR', m.group(1))))),
        (rf"\b(?:na|no) {_wd('pt-BR')}(?! passad| que vem)",
         lambda m, t: _day(_next_weekday(t, _weekday('pt-BR', m.group(1))))),
        (r"\b(?:no )?próximo fim de semana\b|\bfim de semana que vem\b", lambda m, t: _weekend(t, 1)),
        (r"\b(?:neste|nesse|no) fim de semana\b(?! passado)", lambda m, t: _weekend(t, 0)),
        (r"\bsemana que vem\b|\bpróxima semana\b", lambda m, t: _week(t, 1)),
        (r"\bmês que vem\b|\bpróximo mês\b", lambda m, t: _month(t, 1)),
        (r"\b(?:daqui a|em) (\d{1,2}|dois|duas|três) dias\b", lambda m, t: _in_days(t, _int(m.group(1)))),
        (r"\b(?:daqui a|em) (?:alguns|uns) dias\b", lambda m, t: _few_days(t)),
        (rf"\b(começo|início|inicio|meados|final|fim) de {_alts(_MONTHS['pt-BR'])}\b", lambda m, t: _part(
            t, _month_of('pt-BR', m.group(2)),
            _late_or(m.group(1), {"começo": "early", "início": "early", "inicio": "early", "meados": "mid"}))),
        (rf"\b(\d{{1,2}}) de {_alts(_MONTHS['pt-BR'])}\b",
         lambda m, t: _day(_dated(t, _month_of('pt-BR', m.group(2)), int(m.group(1))))),
        (r"\bdia (\d{1,2})\b(?! de)", lambda m, t: _day(_nth(t, int(m.group(1))))),
    ],
    "ru": [
        (r"\bпослезавтра\b", lambda m, t: _in_days(t, 2)),
        (r"(?<!после)\bзавтра\b", lambda m, t: _in_days(t, 1)),
        (r"\bсегодня\b", lambda m, t: _day(t)),
        (rf"\bв следующ(?:ий|ую|ее) {_alts(_AHEAD_WEEKDAYS['ru'])}",
         lambda m, t: _day(_week_day(t, _ahead_weekday('ru', m.group(1)), 1))),
        (rf"\bв эт(?:от|у|о) {_alts(_AHEAD_WEEKDAYS['ru'])}",
         lambda m, t: _day(_this_weekday(t, _ahead_weekday('ru', m.group(1))))),
        (rf"\bв(?:о)? {_alts(_AHEAD_WEEKDAYS['ru'])}",
         lambda m, t: _day(_next_weekday(t, _ahead_weekday('ru', m.group(1))))),
        (r"\bна следующих выходных\b", lambda m, t: _weekend(t, 1)),
        (r"\bна выходных\b|\bв эти выходные\b", lambda m, t: _weekend(t, 0)),
        (r"\bна следующей неделе\b", lambda m, t: _week(t, 1)),
        (r"\bв следующем месяце\b", lambda m, t: _month(t, 1)),
        (r"\bчерез (\d{1,2}|два|две|три|четыре|пять) (?:дня|дней)\b", lambda m, t: _in_days(t, _int(m.group(1)))),
        (r"\bчерез несколько дней\b", lambda m, t: _few_days(t)),
        (rf"\bв (начале|середине|конце) {_alts(_MONTHS['ru'])}", lambda m, t: _part(
            t, _month_of('ru', m.group(2)), _late_or(m.group(1), {"начале": "early", "середине": "mid"}))),
        (rf"\b(\d{{1,2}}) {_alts(_MONTHS['ru'])}", lambda m, t: _day(_dated(t, _month_of('ru', m.group(2)), int(m.group(1))))),
        (r"\b(\d{1,2})(?:-го| числа)", lambda m, t: _day(_nth(t, int(m.group(1))))),
    ],
}
_AHEAD["zh-TW"] = _AHEAD["zh"]

#: Compiled per language, like TABLE.
AHEAD: dict[str, list[tuple[re.Pattern, object]]] = {
    lang: [(re.compile(p, re.IGNORECASE), fn) for p, fn in rules]
    for lang, rules in _AHEAD.items()}


def resolve_future(text: str, said_at: float, tz: tzinfo | None = None,
                   langs: Iterable[str] | None = None) -> Due | None:
    """When the time words in `text` fall, counted from `said_at` (epoch
    seconds) in `tz`: the first words read in `langs` first and then in every
    language; None when there are none. "下周三" said on Monday 23 Nov is
    Wednesday 2 Dec; a bare weekday is its next one; "12月初" is 1 to 7 Dec;
    "15号" is the next 15th."""
    text = str(text or "")
    if not text.strip():
        return None
    today = datetime.fromtimestamp(said_at, tz).date()

    def read(_lang: str, fn, m: re.Match) -> Due | None:
        due = fn(m, today)
        return due._replace(words=m.group(0)) if due else None

    return _first_hit(text, AHEAD, langs, read)
