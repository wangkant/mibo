"""The one person the app's chat is with (runtime/person.json), read by every
chat on the page: short facts with a slot each, plans whose day code works out
from the words they were said in, the gist of the talk, how they want to be
treated, hashes of what they asked to have forgotten, and a trash for what they
rewrote themselves.

Nothing is overwritten: a new value in a slot leaves the old fact as past with
its `until` day, and day words are written as dates when a fact is kept
("今天下午拔了智齿" said on 27 Nov is "11-27下午拔了智齿"). The background fold
(consolidate.py) is the one writer of facts and plans; a sent reply only
marks the plans it asked about (`apply_turn`). No model call and no
Agent import."""
from __future__ import annotations

import hashlib
import re
import shutil
import unicodedata
from collections.abc import Callable, Iterable
from datetime import date, datetime, timedelta, tzinfo
from itertools import pairwise
from pathlib import Path

from . import chatlangs, memstore, ranking, timewords
from .chatlog import REFS_MAX
from .storage import num as _num
from .textproc import _focus_tokens

FILE = "person.json"
FORMAT = 1
#: What a fact can be about.
KINDS = ("who", "like", "dislike", "form", "life", "people", "health", "manner", "other")
#: The most facts one 记住 keeps; every other fact about them is the fold's.
OPS_MAX = 3
TEXT_MAX = 60
SLOT_MAX = 40
SUMMARY_MAX = 600
TOPICS_DAYS = 14
TOPICS_MAX = 40
TRASH_DAYS = 30
#: An open plan this many days past its day is over.
DONE_AFTER_DAYS = 7
#: A fact of one dated day ("11-27拔了智齿") is past this many days after it, and something they are
#: going through (kind life) once it has not been said again for LIFE_DAYS.
DAY_FACT_DAYS = 3
LIFE_DAYS = 30
#: Kinds that stay true until changed, dated or not: who someone in their life is outlasts the day it was
#: said with ("室友小雅…11-24跟她吵了一架").
LASTING_KINDS = ("who", "manner", "like", "dislike", "form", "people")
FACTS_MAX = 200
#: Past facts kept for "where did they live before" and for restore.
PAST_MAX = 200
#: Past facts a reply prompt may carry, when its message names them.
PAST_SHOWN = 3
PLANS_MAX = 60
NEVER_MAX = 500
#: The plans recall shows: due from 3 days ago to 2 weeks ahead.
WINDOW_DAYS = (-3, 14)
PLANS_SHOWN = 5
TOPICS_SHOWN = 5
#: Kinds every reply prompt carries, in this order when the budget runs short:
#: how to treat them, what they cannot have or do not want, who they are.
#: The rest are ranked by the message and placed while the budget lasts.
ALWAYS_KINDS = ("manner", "health", "dislike", "form", "who")
#: A fact is grounded when this share of its characters (CJK) or words
#: occurs in what the person said.
GROUND_SHARE = 0.6
#: A new fact without a slot replaces an old one whose words it carries.
SAME_FACT = 0.6
#: New words that overlap a forgotten thing this much are refused.
TOMB_SHARE = 0.5

# Leading slot parts that say nothing: "family.brother" is "brother".
_SLOT_DROP = frozenset({"user", "person", "owner", "personal", "info", "me", "my", "her",
                        "his", "family", "self", "profile", "the_person", "them"})
# Words that make a plan come round every year.
_YEARLY = re.compile(r"生日|生辰|birthday|誕生日|생일|cumpleaños|anniversaire|geburtstag"
                     r"|aniversário|день рождения", re.IGNORECASE)
# Characters that carry no content, left out of the grounding share.
_STOP_CHARS = frozenset("的了是在我你他她它们們和也就都还還很这這那个個吧呢啊吗嗎呀哦嗯着著过過要会會能说說对對把被给給让讓")
_CJK = re.compile(r"[぀-ヿ㐀-鿿가-힯]")
_WORD = re.compile(r"[^\W_]{2,}|\d+", re.UNICODE)
# A date the model wrote into a plan's words: the plan keeps its own day.
_DATE_IN_TEXT = re.compile(r"[（(]?\s*(?:\d{4}[-/年.])?\d{1,2}[-/月.]\d{1,2}(?:日|号|號)?"
                           r"(?:\s*[（(]?(?:周|星期|週)[一二三四五六日天][)）]?)?\s*[)）]?")
# Verbs that open a like or a dislike, left off the topic the profile gets; "不喜欢看动漫解说" is 动漫解说.
_LIKE_LEAD = re.compile(r"^(?:最近|也|很|超|特别|特別|非常|挺|还|還|不太|不怎么|不怎麼)*(?:迷上了?|喜欢|喜歡|爱看|愛看|爱吃|愛吃|爱|愛"
                        r"|讨厌|討厭|不喜欢|不喜歡|不爱|不愛|不想看|不看|不吃|怕|受不了|烦|煩|看腻了?|看膩了?"
                        r"|想多?看(?:一?[点點些])?"
                        r"|(?:别|別|不要|不想)再?(?:给我|給我)?(?:推荐?|推薦|推|看|要)了?)(?:看|吃|听|聽|玩|读|讀)?"
                        r"|^(?:really |also )?(?:likes?|loves?|enjoys?|is into|hates?|dislikes?|can'?t stand"
                        r"|(?:don'?t|do not) (?:like|want|enjoy)"
                        r"|wants? (?:to (?:see|read|watch) )?more(?: of| about)?)\s+",
                        re.IGNORECASE)
# Words that make a "like" a dislike: "超讨厌香菜" filed as a like is not one.
_DISLIKE = re.compile(r"讨厌|討厭|不(?:太|怎么|怎麼)?喜(?:欢|歡)|不爱|不愛|不敢|受不了|\bhates?\b|\bdislikes?\b"
                      r"|can['’]?t stand|(?:don['’]?t|do not) (?:like|enjoy)",
                      re.IGNORECASE)
#: Words of not wanting a thing; a "dislike" without them ("反手高远球打不到底线") is no rule for the finds.
_REFUSE = re.compile(_DISLIKE.pattern + r"|腻|别|別|不想|不要|没意思|沒意思|不感兴趣|不感興趣|怕|烦|煩|跳过|跳過"
                     r"|\bavoid|\bno more\b|\bstop\b|\btired of\b|\bboring\b|\bdon['’]?t want\b", re.IGNORECASE)


def refuses(text: str) -> bool:
    return bool(_REFUSE.search(str(text or "")))


# Words of the body's health: an allergy, an illness, a treatment.
_HEALTH = re.compile(r"过敏|過敏|不耐受|生病|病了|疾病|症|药|藥|医院|醫院|医生|醫生|看病|手术|手術|抑郁|抑鬱|焦虑|焦慮|失眠"
                     r"|怀孕|懷孕|牙医|牙醫|智齿|智齒|发烧|發燒|感冒|治疗|治療|复诊|複診|体检|體檢"
                     r"|allerg|intoleran|\bill\b|illness|sick|disease|medicat|\bmeds?\b|hospital|doctor|surgery"
                     r"|diagnos|depress|anxiety|insomnia|pregnan|therapy|アレルギー|病院|薬|알레르기|병원|약을", re.IGNORECASE)


def health(kind: str, text: str) -> bool:
    """A health detail: filed as health, or words of an allergy, an illness or a treatment whatever it was filed under."""
    return kind == "health" or bool(_HEALTH.search(str(text or "")))


# A first person that opens a fact ("我住在闵行"), left off so the page reads it as a note about them.
_FIRST_LEAD = re.compile(r"^(?:我(?![们們])(?:的)?|(?:私|僕|俺|わたし|あたし)(?:は|が|の)|(?:저|나)는\s*|(?:제|내)\s+)")
# Another assistant's way of naming them ("用户喜欢爬山", "User's name is Lin").
_USER_LEAD = re.compile(r"^(?:该?用户(?:的)?|使用者|ユーザー(?:は|の)?|사용자(?:는|의)?\s*|(?:the )?user(?:'s)?\s+)",
                        re.IGNORECASE)


def neutral(text: str) -> str:
    """A fact as it is kept and listed: without the first person or another assistant's "user" that opens it
    ("我对芒果过敏" is "对芒果过敏", "User's name is Lin" is "Name is Lin")."""
    text = str(text or "").strip()
    bare = _USER_LEAD.sub("", _FIRST_LEAD.sub("", text, count=1), count=1).strip(" ，,:：")
    if not bare:
        return text
    return bare[0].upper() + bare[1:] if bare[0].isascii() else bare

#: What a forgotten line becomes in every chat's record, per chat language.
FORGOTTEN = {"en": "(forgotten)", "zh": "（已忘记）", "zh-TW": "（已忘記）", "ja": "（忘れた）",
             "ko": "(잊음)", "es": "(olvidado)", "fr": "(oublié)", "de": "(vergessen)",
             "pt-BR": "(esquecido)", "ru": "(забыто)"}


def _compiled(attr: str) -> list[tuple[str, re.Pattern]]:
    """Each chat language's patterns named `attr` (one source or a tuple of them), compiled."""
    sources = ((code, getattr(spec, attr)) for code, spec in chatlangs.SPECS.items())
    return [(code, re.compile(source, re.IGNORECASE)) for code, value in sources
            for source in (value if isinstance(value, tuple) else (value,)) if source]


_UNSAID_RE = _compiled("unsaid")
_FORGET_THAT_RE = _compiled("forget_that")


def unsaid(text: str) -> re.Match | None:
    """The words of a "don't keep this" anywhere in `text`, in any chat language."""
    for _code, pat in _UNSAID_RE:
        m = pat.search(str(text or ""))
        if m:
            return m
    return None


def forget_that(text: str) -> bool:
    """"Forget what I just said": a forget that names nothing."""
    return any(pat.search(str(text or "").strip()) for _code, pat in _FORGET_THAT_RE)


def dated(text: str, at: float, tz, langs: Iterable[str] = (), said: str | None = None,
          now: float = 0.0) -> tuple[str, str]:
    """`text` with each day word that names one past day written as that day, counted from `at`
    ("今天下午拔了智齿" is "11-27下午拔了智齿"), and the ISO day of the first; (text, "") when none does.
    Words for a longer span ("上周") stay as said. With `said`, a day word not in it was written by
    whoever reworded the line on the day `now` ("昨天" for a line's "今天" read the morning after) and
    counts from `now`."""
    first = ""

    def day_of(m: re.Match, lang: str) -> str:
        nonlocal first
        # "每天早上" is a habit, not a day.
        if re.search(r"(?:每|天天|every|each)\s*\S?$", m.string[max(0, m.start() - 4):m.start()], re.IGNORECASE):
            return m.group(0)
        base = at if said is None or m.group(0) in said else now
        span = timewords.resolve(m.group(0), base, tz, (lang,))
        start = datetime.fromtimestamp(span[0], tz) if span else None
        # One day: "today" and "yesterday"; "last night" runs past midnight and is its evening's day.
        if start is None or span[1] - span[0] > 86400:
            return m.group(0)
        first = first or start.date().isoformat()
        return start.strftime("%m-%d")
    for lang in dict.fromkeys([*langs, *timewords.TABLE]):
        for pat, _kind in timewords.TABLE[lang]:
            text = pat.sub(lambda m, lang=lang: day_of(m, lang), text)
    return " ".join(text.split()), first


def slot_key(slot) -> str:
    """A slot as code compares it: lower case, dot-separated, without the
    leading parts that say nothing."""
    s = re.sub(r"[\s/:>\-]+", ".", str(slot or "").strip().lower())
    parts = [p for p in re.sub(r"[^\w.]+", "", s).split(".") if p]
    while len(parts) > 1 and parts[0] in _SLOT_DROP:
        parts.pop(0)
    return ".".join(parts)[:SLOT_MAX]


def _same_slot(a: str, b: str) -> bool:
    """One slot, or one inside the other ("brother" and "brother.grade")."""
    return bool(a and b) and (a == b or a.startswith(b + ".") or b.startswith(a + "."))


def _units(text: str) -> set[str]:
    """What grounding compares: CJK characters that carry content, and words."""
    text = str(text or "").lower()
    chars = {c for c in _CJK.findall(text) if c not in _STOP_CHARS}
    words = {w for w in _WORD.findall(_CJK.sub(" ", text)) if len(w) >= 3 or w.isdigit()}
    return chars | words


def _same_stem(a: str, b: str) -> bool:
    """Two forms of one word: a shared start of four letters or more, all but the last two of the shorter
    ("lives" and "live", "trabaja" and "trabajo", "работаю" and "работает")."""
    n = 0
    while n < min(len(a), len(b)) and a[n] == b[n]:
        n += 1
    return n >= max(4, min(len(a), len(b)) - 2)


def grounded(text: str, sources: str) -> bool:
    """Is `text` made of the words in `sources`: GROUND_SHARE of its content characters and words, a word also in
    another form of it, and for CJK at least one pair of characters in a row."""
    units = _units(text)
    if not units:
        return False
    hay = str(sources or "").lower()
    words = {w for w in _WORD.findall(_CJK.sub(" ", hay)) if len(w) >= 4}

    def found(u: str) -> bool:
        return u in hay or (len(u) >= 5 and not u.isdigit() and not _CJK.match(u)
                            and any(_same_stem(u, w) for w in words))
    if sum(1 for u in units if found(u)) / len(units) < GROUND_SHARE:
        return False
    run = [c for c in str(text).lower() if _CJK.match(c)]
    pairs = {a + b for a, b in pairwise(run)}
    return not pairs or any(p in hay for p in pairs)


_ELLIPSIS = re.compile(r"\.{3,}|…+")


def _plain(text: str) -> str:
    """Words only: NFKC, case folded, punctuation and spacing made one space."""
    return " ".join(re.sub(r"[\W_]+", " ", unicodedata.normalize("NFKC", str(text or "")).casefold()).split())


def holds(line: str, quote: str) -> bool:
    """`quote` is in `line` word for word, case, punctuation and spacing aside; a "..." in it may leave words out
    between its pieces, which come in order. A quote with no content word holds nothing."""
    pieces = [p for p in map(_plain, _ELLIPSIS.split(str(quote or ""))) if p]
    if not pieces or not _units(" ".join(pieces)):
        return False
    hay, at = _plain(line), 0
    for piece in pieces:
        while True:
            i = hay.find(piece, at)
            if i < 0:
                return False
            at = i + 1
            # A piece starts and ends on a word's edge, unless it is CJK, which has no spaces.
            if ((i == 0 or hay[i - 1] == " " or _CJK.match(piece[0]))
                    and (i + len(piece) == len(hay) or hay[i + len(piece)] == " " or _CJK.match(piece[-1]))):
                at = i + len(piece)
                break
    return True


def said_part(text: str, ok: Callable[[str], bool]) -> str:
    """`text` when `ok`; else its clauses that are ("住徐汇，咖啡店打工" from "搬到徐汇了": 住徐汇), "" for none."""
    if not text or ok(text):
        return text
    return ("，" if _CJK.search(text) else ", ").join(p for p in re.split(r"\s*[，,；;]\s*", text) if p and ok(p))


def _tokens(text: str) -> set[str]:
    return _focus_tokens(str(text or ""), "zh")


def _share(a: str, b: str) -> float:
    """The part of `a`'s tokens that `b` carries."""
    ta = _tokens(a)
    return len(ta & _tokens(b)) / len(ta) if ta else 0.0


def _clip(text) -> str:
    text = " ".join(str(text or "").split())
    return text[:TEXT_MAX]


def _day(t: float, tz) -> date:
    return datetime.fromtimestamp(t, tz).date()


def _lapses(f: dict, tz) -> float:
    """When an active fact stops being true by itself: a dated day's DAY_FACT_DAYS on, or what they are
    going through LIFE_DAYS after they last said it; 0 for a lasting fact."""
    if f.get("kind") in LASTING_KINDS:
        return 0.0
    if f.get("day"):
        d = date.fromisoformat(f["day"]) + timedelta(days=DAY_FACT_DAYS + 1)
        return datetime(d.year, d.month, d.day, tzinfo=tz).timestamp()
    return _num(f.get("at")) + LIFE_DAYS * 86400 if f.get("kind") == "life" else 0.0


class Person:
    """runtime/person.json, loaded on first use. A damaged file raises
    memstore.MemoryFileDamaged, as memory.json does."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._data: dict | None = None

    @property
    def data(self) -> dict:
        if self._data is None:
            self.load()
        return self._data

    def load(self) -> dict:
        raw = memstore._read_strict(self.path, lambda d: isinstance(d, dict)) or {}
        name = raw.get("name") if isinstance(raw.get("name"), dict) else {}
        talk = raw.get("talk") if isinstance(raw.get("talk"), dict) else {}
        fold = raw.get("fold") if isinstance(raw.get("fold"), dict) else {}
        use = raw.get("use") if isinstance(raw.get("use"), dict) else {}

        def rows(key: str) -> list[dict]:
            value = raw.get(key)
            return [r for r in value if isinstance(r, dict)] if isinstance(value, list) else []

        self._data = {
            "format": FORMAT,
            "name": {"name": str(name.get("name") or ""), "call_me": str(name.get("call_me") or "")},
            "facts": [r for r in rows("facts") if isinstance(r.get("text"), str)],
            "plans": [r for r in rows("plans") if isinstance(r.get("text"), str)],
            "talk": {"summary": str(talk.get("summary") or "")[:SUMMARY_MAX],
                     "at": _num(talk.get("at")),
                     "topics": [t for t in talk.get("topics") or [] if isinstance(t, dict)]},
            "never": [r for r in rows("never") if isinstance(r.get("h"), list)],
            "trash": rows("trash"),
            "fold": fold,
            # Settings › 记忆: whether memory is used and kept at all, and whether health details are.
            "use": {"on": use.get("on") is not False, "health": use.get("health") is not False},
            "followed_day": str(raw.get("followed_day") or ""),
            "migrated": bool(raw.get("migrated")),
            "bak_day": str(raw.get("bak_day") or ""),
        }
        return self._data

    def save(self) -> None:
        """Written whole; the first write of a local day keeps the file as it
        was in `person.json.bak`."""
        today = date.today().isoformat()
        if self.data["bak_day"] != today and self.path.is_file():
            shutil.copy2(self.path, self.path.with_name(self.path.name + ".bak"))
            self.data["bak_day"] = today
        memstore.save_json(self.path, self.data)

    # ---- reading ---------------------------------------------------------------

    def facts(self, active: bool = True) -> list[dict]:
        return [f for f in self.data["facts"] if not active or f.get("status", "active") == "active"]

    def plans(self, *status: str) -> list[dict]:
        return [p for p in self.data["plans"] if not status or p.get("status", "open") in status]

    def get(self, item_id: str) -> dict | None:
        return next((r for r in self.data["facts"] + self.data["plans"]
                     if r.get("id") == item_id), None)

    def name(self) -> str:
        """What to call them: the name they asked for, else their name."""
        name = self.data["name"]
        return name.get("call_me") or name.get("name") or ""

    def manner(self) -> list[str]:
        return [f["text"] for f in self.facts() if f.get("kind") == "manner"]

    @property
    def on(self) -> bool:
        """Memory is used and kept (Settings › 记忆 › 使用并更新记忆); off, what is kept stays and nothing is read or added."""
        return self.data["use"]["on"]

    def keeps(self, kind: str, text: str) -> bool:
        """Whether a new fact may be kept: memory is on, and a health detail only while they keep those."""
        return self.on and (self.data["use"]["health"] or not health(kind, text))

    def signature(self) -> str:
        """Changes whenever an active fact does."""
        text = "\n".join(sorted(f"{f.get('kind')}:{f['text']}" for f in self.facts()))
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    def _ids(self) -> set[str]:
        return {str(r.get("id")) for r in self.data["facts"] + self.data["plans"] + self.data["trash"]}

    # ---- writing ---------------------------------------------------------------

    def _trash(self, kind: str, item: dict, why: str, now: float) -> None:
        self.data["trash"].append({"id": memstore.new_id("t", self._ids()), "kind": kind,
                                   "item": dict(item), "why": why, "at": now})

    def _set_name(self, slot: str, text: str) -> None:
        """A name fact also names them: "name" or "call_me" with short words, from its first clause
        ("叫小晓，全名林晓": the first of the names); a later clause only when it says what to call them
        ("我叫林晓，叫我小晓就行" sets both)."""
        for i, clause in enumerate(re.split(r"[，,、;；。]", text.strip())):
            clause = clause.strip()
            # "叫我阿杰" is what to call them, whatever slot it came in.
            called = bool(_CALL_LEAD.search(clause))
            if i and not called:
                continue
            value = _NAME_LEAD.sub("", _CALL_LEAD.sub("", clause)).strip(" ，,。.")
            value = re.sub(r"^(?:叫|我是|名字是|名字叫|本名|全名|真名|i'm)\s*", "", value, flags=re.IGNORECASE)
            value = re.sub(r"(?:就行|就好|就可以|好了|吧|です|だよ|입니다|이에요|예요|と呼んで.*|(?:이)?라고 불러.*)$", "",
                           value).strip()
            # "别叫鱼片" names what not to call them.
            if not value or len(value) > 12 or timewords.has_negation(value):
                continue
            if called or slot in ("call_me", "name.call", "name.call_me", "nickname", "name.nickname"):
                self.data["name"]["call_me"] = value
            elif slot in ("name", "name.full", "name.real"):
                self.data["name"]["name"] = value

    def put_fact(self, kind: str, slot: str, text: str, now: float, *, src: str = "fold",
                 conv: str = "", refs: Iterable[int] = (), imp: int = 3, day: str = "") -> tuple[dict, list[dict]]:
        """Keep one fact: (its row, the facts it ended). A fact in a slot ends the active one of its kind
        there, or one inside it in much the same words; one without a slot ends an older one whose words
        it carries. An ended fact stays as past with its `until`. `day`: the one day the fact is of."""
        kind = kind if kind in KINDS else "other"
        kind = "dislike" if kind == "like" and _DISLIKE.search(text) else kind
        # Kept without the first person that opens it; the name is read from the words as said.
        said, slot, text = _clip(text), slot_key(slot), _clip(neutral(text))
        # The same words, or fewer of them in the same slot ("研二" beside "华东师大研二"): nothing new.
        same = next((f for f in self.facts() if f["text"] == text or (slot and text in f["text"]
                     and _same_slot(slot_key(f.get("slot")), slot))), None)
        if same is not None:
            same["at"] = now
            if slot and not same.get("slot"):
                same["slot"] = slot
            return same, []
        # Its words already kept as the same kind in another slot ("橘猫" beside "年糕，家里养的橘猫"): nothing new.
        held = next((f for f in self.facts() if f.get("kind") == kind and _share(text, f["text"]) >= SAME_FACT
                     and not (slot and _same_slot(slot_key(f.get("slot")), slot))
                     and timewords.has_negation(text) == timewords.has_negation(f["text"])), None)
        if held is not None:
            held["at"] = now
            return held, []
        if slot:
            # "cat" and "cat.health" are one thing only in much the same words, and never for what happened
            # on one day ("mother" and "mother.visit"). A reply's fact of another kind in the slot is the
            # fold's to file again.
            old = [f for f in self.facts() if (f.get("kind") in (kind, "other") or f.get("src") == "turn") and (
                slot_key(f.get("slot")) == slot or (_same_slot(slot_key(f.get("slot")), slot)
                and not (day or f.get("day")) and _share(f["text"], text) >= 0.3))]
        else:
            old = [f for f in self.facts() if not f.get("slot") and f.get("kind") in (kind, "other")
                   and _tokens(f["text"]) and _share(f["text"], text) >= SAME_FACT]
        for f in old:
            self.end_fact(f, now, "replaced")
        row = {"id": memstore.new_id("f", self._ids()), "kind": kind, "slot": slot, "text": text,
               "at": now, "born": now, "src": src, "imp": imp, "uses": 0, "used": 0.0,
               "status": "active", "conv": conv, "refs": list(refs)[-REFS_MAX:], **({"day": day} if day else {})}
        self.data["facts"].append(row)
        if kind in ("who", "manner"):
            self._set_name(slot, said)
        self._cap(now)
        return row, old

    def end_fact(self, row: dict, now: float, why: str = "ended") -> None:
        """No longer true from `now`: kept as past, with why ("replaced" by a newer value, else "ended")."""
        row.update(status="past", until=now, why=why)

    def put_plan(self, text: str, due: timewords.Due, now: float, *, by: str = "them",
                 conv: str = "", refs: Iterable[int] = ()) -> dict:
        """Keep a dated plan; one already open that says the same thing gets
        the new day and words instead."""
        text = _clip(_DATE_IN_TEXT.sub("", text)) or _clip(text)
        bare = text.replace(due.words, "") if due.words else text
        # Said again on the same day: some words in common beyond the day's own.
        same = next((p for p in self.plans("open", "asked")
                     if _tokens(p["text"]) and (_share(p["text"], text) >= 0.5
                                                or _share(text, p["text"]) >= 0.5
                                                or (p.get("due") == due.due and _share(
                                                    bare, p["text"].replace(str(p.get("said") or "\0"), "")) > 0))),
                    None)
        fields = {"due": due.due, "due_kind": due.kind, "until": due.until, "said": due.words,
                  "said_at": now}
        if same is not None:
            if same.get("due") != due.due:
                self._trash("plan", same, "replaced", now)
                same.update(fields, status="open", asked_at=0.0)
            same["text"] = text if len(text) >= len(same["text"]) else same["text"]
            return same
        row = {"id": memstore.new_id("p", self._ids()), "text": text, **fields,
               "status": "open", "asked_at": 0.0, "by": by, "yearly": bool(_YEARLY.search(text)),
               "conv": conv, "refs": list(refs)[-REFS_MAX:], "born": now}
        self.data["plans"].append(row)
        self._cap(now)
        return row

    def mark_asked(self, row: dict, now: float) -> None:
        row["status"], row["asked_at"] = "asked", now

    def _cap(self, now: float) -> None:
        facts = self.facts()
        while len(facts) > FACTS_MAX:
            worst = min(facts, key=lambda f: ranking.retention(
                f.get("imp"), f.get("uses"), max(_num(f.get("at")), _num(f.get("used"))), now))
            self.data["facts"].remove(worst)
            facts.remove(worst)
        past = sorted((f for f in self.data["facts"] if f.get("status") == "past"), key=lambda f: _num(f.get("until")))
        for f in past[:max(0, len(past) - PAST_MAX)]:
            self.data["facts"].remove(f)
        plans = self.data["plans"]
        if len(plans) > PLANS_MAX:
            gone = sorted((p for p in plans if p.get("status") in ("done", "cancelled")),
                          key=lambda p: str(p.get("due")))[:len(plans) - PLANS_MAX]
            self.data["plans"] = [p for p in plans if p not in gone]

    # ---- forgetting ------------------------------------------------------------

    def tomb(self, text: str, now: float) -> None:
        """Keep hashes of `text`'s words, never the words."""
        hashes = memstore.token_hashes(text)
        if hashes:
            self.data["never"].append({"h": hashes, "at": now})
            del self.data["never"][:-NEVER_MAX]

    def tombed(self, text: str) -> bool:
        """Do `text`'s words overlap a forgotten thing by TOMB_SHARE or more?"""
        mine = set(memstore.token_hashes(text))
        if not mine:
            return False
        return any(len(mine & set(row["h"])) / len(mine) >= TOMB_SHARE for row in self.data["never"])

    def forget(self, hit: Callable[[str], bool], now: float) -> list[dict]:
        """Remove every fact, plan, trash row and topic `hit` names, and the
        summary sentences it names; nothing goes to the trash, and the words
        are kept only as hashes. Returns what went."""
        data = self.data
        gone = [r for r in data["facts"] + data["plans"] if hit(r["text"]) or hit(str(r.get("said") or ""))]
        data["facts"] = [r for r in data["facts"] if r not in gone]
        data["plans"] = [r for r in data["plans"] if r not in gone]
        data["trash"] = [r for r in data["trash"] if not hit(str((r.get("item") or {}).get("text") or ""))]
        topics = data["talk"]["topics"]
        data["talk"]["topics"] = [t for t in topics if not hit(str(t.get("words") or ""))]
        summary = data["talk"]["summary"]
        if summary and hit(summary):
            parts = re.split(r"(?<=[。！？；.!?;\n])\s*", summary)
            data["talk"]["summary"] = "".join(p for p in parts if not hit(p))
        for row in gone:
            self.tomb(row["text"], now)
            if row.get("kind") in ("who", "manner"):
                for key in ("name", "call_me"):
                    if data["name"][key] and data["name"][key] in row["text"]:
                        data["name"][key] = ""
        return gone

    def forget_all(self, now: float) -> int:
        """Everything about them goes; the tombstones stay."""
        data = self.data
        n = len(data["facts"]) + len(data["plans"])
        for row in data["facts"] + data["plans"]:
            self.tomb(row["text"], now)
        data.update(facts=[], plans=[], trash=[], name={"name": "", "call_me": ""},
                    talk={"summary": "", "at": 0.0, "topics": []})
        return n

    def restore(self, tid: str, now: float) -> dict | None:
        """Put a past fact, or a fact or plan from before a rewrite, back; what holds its slot now
        becomes past in its place."""
        past = next((f for f in self.data["facts"] if f.get("id") == tid and f.get("status") == "past"), None)
        if past is not None:
            self.data["facts"].remove(past)
            put, _old = self.put_fact(past.get("kind", "other"), past.get("slot", ""), past["text"], now,
                                      src="edit", conv=past.get("conv", ""), refs=past.get("refs") or ())
            put["born"] = _num(past.get("born")) or put["born"]
            return put
        row = next((t for t in self.data["trash"] if t.get("id") == tid), None)
        if row is None:
            return None
        self.data["trash"].remove(row)
        item = dict(row["item"])
        if row["kind"] == "plan":
            self.data["plans"].append(item)
            return item
        put, _old = self.put_fact(item.get("kind", "other"), item.get("slot", ""), item["text"], now,
                                  src="edit", conv=item.get("conv", ""), refs=item.get("refs") or ())
        put["born"] = _num(item.get("born")) or put["born"]
        return put

    def edit(self, item_id: str, text: str, now: float) -> dict | None:
        """The person's own rewrite of one fact or plan; its slot stays."""
        row = self.get(item_id)
        text = _clip(text)
        if row is None or not text:
            return None
        self._trash("plan" if item_id.startswith("p") else "fact", row, "edited", now)
        row.update(text=text, at=now, src="edit")
        return row

    # ---- the daily tidy, code only -----------------------------------------------

    def tidy(self, now: float, tz: tzinfo | None = None) -> bool:
        """Plans long past are done, birthdays come round again, a fact of a day
        long gone and what they were going through and no longer say are past,
        old topics and trash go. Whether anything changed."""
        today = _day(now, tz)
        changed = False
        for f in self.facts():
            lapses = _lapses(f, tz)
            if 0 < lapses <= now:
                self.end_fact(f, lapses)
                changed = True
        for plan in self.plans("open", "asked"):
            try:
                end = date.fromisoformat(plan.get("until") or plan["due"])
            except (KeyError, ValueError):
                continue
            if (today - end).days <= DONE_AFTER_DAYS:
                continue
            changed = True
            if plan.get("yearly"):
                due = date.fromisoformat(plan["due"])
                while due < today:
                    due = due.replace(year=due.year + 1)
                plan.update(due=due.isoformat(), until="", status="open", asked_at=0.0)
            else:
                plan["status"] = "done"
        cutoff = (today - timedelta(days=TOPICS_DAYS)).isoformat()
        topics = self.data["talk"]["topics"]
        kept = [t for t in topics if str(t.get("day") or "") >= cutoff][-TOPICS_MAX:]
        trash = [t for t in self.data["trash"] if now - _num(t.get("at")) < TRASH_DAYS * 86400]
        changed = changed or len(kept) != len(topics) or len(trash) != len(self.data["trash"])
        self.data["talk"]["topics"], self.data["trash"] = kept, trash
        return changed


# ---- the turn's operations -----------------------------------------------------

def apply_turn(store: Person, reply: str, at: float, tz: tzinfo | None) -> list[dict]:
    """The open plans a sent reply asked about: those due by today that the reply shares two words with.
    What the person says of themselves is the fold's. Never saves."""
    asked = []
    today = _day(at, tz).isoformat()
    said = _tokens(reply)
    for plan in store.plans("open"):
        if str(plan.get("due") or "9") <= today and len(_tokens(plan["text"]) & said) >= 2:
            store.mark_asked(plan, at)
            asked.append(plan)
    return asked


def denies(fact: str, said: str) -> bool:
    """Do their words deny the fact right where they name it ("不住闵行了" for 住闵行)?"""
    nots = [r"(?:不|没|沒|别|別)(?:再|是|在)?" + re.escape(t) for t in _tokens(fact) if t]
    # Not a "not" the fact says itself ("乳糖不耐受", "不敢看").
    return any(re.search(n, said) and not re.search(n, fact) for n in nots)


def denied(fact: dict, said: str) -> bool:
    """Do their words deny what the fact says first ("不住闵行了" for "住闵行，离学校近"), whatever kind or
    slot it was kept under? Never a dislike or a fact with a "not" of its own: "别放香菜" agrees with one."""
    if fact.get("kind") == "dislike" or timewords.has_negation(fact["text"]):
        return False
    head = re.split(r"[，,；;。]", fact["text"])[0]
    return any(grounded(head, m.group(1)) for m in re.finditer(r"(?:不|没|沒|别|別)(?:再|是|在)?([^，,。；;！!？?\n]+)", said))


def topic_of(text: str) -> str:
    """A like's or a dislike's thing, without the verb: "喜欢羽毛球" is 羽毛球, "想多看猫的内容" is 猫."""
    # "我不喜欢看动漫解说": not the person either.
    bare = re.sub(r"^(?:我(?![们們])|i\s+(?=\w))", "", str(text or "").strip(), flags=re.IGNORECASE)
    # "动漫解说，看腻了": the thing, not why.
    topic = re.split(r"[，,；;。（(]", _LIKE_LEAD.sub("", bare).strip(" ，,。."))[0]
    topic = re.sub(r"(?<=[^\x00-\x7f])(?:的?(?:内容|內容|东西|東西)|了|啦)$|\s+(?:content|stuff|things)$", "", topic,
                   flags=re.IGNORECASE)
    return topic.strip() or str(text or "")


def form_of(text: str) -> tuple[bool | None, str | None]:
    """(short, kind) a form fact asks for: short or long things, videos or text."""
    low = str(text or "").lower()
    short = (True if re.search(r"短|几分钟|幾分鐘|别太长|別太長|short|brief|quick", low)
             else False if re.search(r"长视频|長視頻|长文|長文|long", low) else None)
    # "不爱看长文章" wants short things.
    short = True if short is False and timewords.has_negation(low) else short
    kind = ("video" if re.search(r"视频|視頻|video|片子", low)
            else "text" if re.search(r"文章|文字|帖子|article|text|read", low) else None)
    # "视频太长，短点的" is about length: the videos are what they watch, not a wish against text.
    return short, None if short is not None else kind


def about_of(slot: str, text: str) -> str:
    """What a dislike is about, for the profile: topic, source, kind or length.
    A kind only when the thing itself is one ("不看视频"), not a topic's videos."""
    low = f"{slot} {text}".lower()
    if re.search(r"length|长度|長度|太长|太長|长视频|長視頻|\bshort\b|\blong\b", low):
        return "length"
    if re.search(r"source|site|channel|来源|來源|网站|網站|up主|频道|頻道", low):
        return "source"
    if re.fullmatch(r"(?:看|读|讀)?(?:视频|視頻|文章|长文|長文|图文|圖文|videos?|articles?)", topic_of(text).lower()):
        return "kind"
    return "topic"


# Their name and what to call them, in the ten chat languages (`Person._set_name`, personsaid.py).
_NAME_LEAD = re.compile(r"^(?:我的名字(?:是|叫)|我名字(?:是|叫)|我全名(?:是|叫)|我叫|my name is|my name's|i'?m called"
                        r"|je m'appelle|mon nom est|ich hei(?:ß|ss)e|mein name ist|me llamo|mi nombre es"
                        r"|(?:eu )?me chamo|meu nome é|меня зовут|мо[её] имя|(?:私|僕|俺|わたし|あたし)?の?名前は"
                        r"|(?:제|내) 이름은)\s*", re.IGNORECASE)
_CALL_LEAD = re.compile(r"^(?:以后|以後|今后|今後)?(?:请|請)?(?:就)?(?:叫|喊|称呼|稱呼)(?:我|她|他|ta)(?:为|為)?\s*"
                        r"|^(?:please )?call me\s+|^appelle-moi\s+|^nenn mich\s+|^llámame\s+|^me chame de\s+"
                        r"|^зови меня\s+|と呼んで(?:ください|ね)?$|(?:이)?라고 불러(?:줘|주세요)?$", re.IGNORECASE)


def scrub(line: str, hit: Callable[[str], bool], code: str) -> str:
    """`line` with each sentence `hit` names put as the forgotten mark (one mark for a run of them); the
    whole line when only all of it together names the thing."""
    mark = FORGOTTEN.get(code, FORGOTTEN["en"])
    out, held = [], False
    for piece in re.split(r"(?<=[。！？；\n])|(?<=[.!?;] )|(?<=[!?;])(?=\S)", line):
        if piece.strip() and hit(piece):
            if not held:
                out.append(mark + (" " if piece.endswith(" ") else ""))
            held = True
        else:
            out.append(piece)
            held = held and not piece.strip()
    text = "".join(out).strip()
    return mark if text == line.strip() else text


# ---- forgetting everywhere: what a line must lose ------------------------------

def forget_hit(words: Iterable[str], texts: Iterable[str] = ()) -> Callable[[str], bool]:
    """Whether a chat line holds forgotten words: one of `words` as written
    (two or more characters in CJK, a whole word of three or more letters
    otherwise), or most of one of `texts` (a forgotten fact said again)."""
    words = [w.strip() for w in words if w and w.strip()]
    pats = []
    for w in words:
        if _CJK.search(w):
            if len(w) >= 2:
                pats.append(re.compile(re.escape(w)))
        elif len(w) >= 3:
            pats.append(re.compile(rf"(?<!\w){re.escape(w)}(?!\w)", re.IGNORECASE))
    texts = [t for t in texts if len(_tokens(t)) >= 2]

    def hit(line: str) -> bool:
        line = str(line or "")
        if any(p.search(line) for p in pats):
            return True
        return any(_share(t, line) >= SAME_FACT for t in texts)
    return hit
