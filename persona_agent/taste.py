"""The feed's model of its person.

One small Bayesian logistic regression per person (Chapelle and Li 2011,
Algorithm 3): a Gaussian prior N(m0, 1/q0) on each weight, a fit by cyclic
coordinate Newton on the person's reactions, a Laplace posterior N(m, 1/q) and
Thompson-sampled scores. The features are few and sparse: where a thing came
from (its source, or its site for a walk's find), its kind and length, whether
it is in a language the person reads, how fresh it is, what the character
thought of it and the topics the person picked.

Every event in feed.json keeps a snapshot of these as they were at that moment
(see `Reader.snapshot`), so the model and the replay learn from what the feed
knew then, and survive the library dropping old things. The fit runs in a
worker thread at most once a minute and writes `<runtime>/taste_model.json`;
ranking only reads it.

    python -m persona_agent.taste replay [--runtime DIR]

replays the person's own reactions day by day against the old point sum.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import random
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlsplit

from . import life, situation
from .library import Item, Library
from .sources import weights
from .storage import append_jsonl, atomic_write_text

logger = logging.getLogger("agent.taste")

MODEL_FILE = "taste_model.json"
SHOWN_FILE = "shown.jsonl"
SHOWN_MAX = 20_000
DAY = 86400
# Thompson draws at this share of the posterior's spread: below 1 does better over short runs.
ALPHA = 0.5
SWEEPS, STEP_MAX, TOLERANCE = 15, 1.0, 1e-4
# At most one fit this often, and a thing shown and left alone this long is a quiet no.
REFIT_S = 60
QUIET_S = DAY
# Each row counts half as much HALF_DAYS later.
HALF_DAYS = 45
# (label, confidence) of a thing's final mark. A play counts from PLAY_MIN_S seconds in the app's player.
HIDE, LIKE, SKIP, PLAY, OPEN = (0, 3.0), (1, 3.0), (0, 1.0), (1, 2.0), (1, 1.0)
PLAY_MIN_S = 60
# A quiet no from the pet's card or the main chat, and from a list the person scrolled past.
SHOWN_CARD, SHOWN_LIST = 0.3, 0.1
SURFACES = ("card", "list", "chat")
PROMINENT = ("card", "chat")
# Videos under 4 minutes are short, over 20 long; text by its characters.
VIDEO_SHORT, VIDEO_LONG = 240, 1200
TEXT_SHORT, TEXT_LONG = 600, 6000

# (m0, q0): q0 is roughly a quarter of the reactions' worth of evidence the prior counts for.
PRIORS = {"bias": (0.0, 1.0), "unread_lang": (-2.0, 2.0), "fresh": (1.5, 2.0), "judged": (0.0, 2.0),
          "char_fits": (1.0, 5.0), "char_love": (1.0, 5.0)}
# avoid:<t> is a topic the owner said no to in the profile; its prior comes from that rule.
FAMILIES = {"origin": (0.0, 1.0), "kind": (0.0, 1.0), "len": (0.0, 1.0), "topic": (1.5, 3.0), "tag": (0.0, 1.0),
            "avoid": (0.0, 1.0)}
# A source the person asked to see less of: the same form a person's own override takes.
HIDDEN = (-4.0, 100.0)

# The character's pick: in each WINDOW placed things, k_c go to its best loved unseen ones, by PICK_BY.
WINDOW, PICK_BY, PICK_LOVE = 20, 10, 2
# A reason is named only when its term is at least this, and "something new" when the draw lifted it this much.
REASON_MIN, EXPLORE_MIN = 0.2, 1.0
SERVED_MAX = 5000

# The line under the character's own sentence, by UI language (the language pass moves these).
LABELS = {
    "en": {"origin": "Like things you opened from {site}", "topic": "On {topic}",
           "explore": "Something new to try", "pick": "My pick"},
    "zh": {"origin": "像你在{site}打开过的那些", "topic": "关于{topic}", "explore": "换点新的试试", "pick": "我挑的"},
    "zh-Hant": {"origin": "像你在{site}打開過的那些", "topic": "關於{topic}", "explore": "換點新的試試",
                "pick": "我挑的"},
    "ja": {"origin": "{site}で開いたものに近いもの", "topic": "{topic}の話", "explore": "新しいものをひとつ",
           "pick": "わたしのおすすめ"},
    "ko": {"origin": "{site}에서 열어 본 것들과 비슷해요", "topic": "{topic} 이야기", "explore": "새로운 걸 한번",
           "pick": "내가 고른 것"},
    "ru": {"origin": "Похоже на то, что вы открывали на {site}", "topic": "Тема: {topic}",
           "explore": "Что-то новое на пробу", "pick": "Мой выбор"},
    "pt-BR": {"origin": "Parecido com o que você abriu em {site}", "topic": "Sobre {topic}",
              "explore": "Algo novo para experimentar", "pick": "Minha escolha"},
    "es": {"origin": "Como lo que abriste en {site}", "topic": "Sobre {topic}",
           "explore": "Algo nuevo para probar", "pick": "Mi elección"},
    "fr": {"origin": "Comme ce que tu as ouvert sur {site}", "topic": "Sur {topic}",
           "explore": "Quelque chose de nouveau à essayer", "pick": "Mon choix"},
    "de": {"origin": "Wie das, was du auf {site} geöffnet hast", "topic": "Zum Thema {topic}",
           "explore": "Mal etwas Neues", "pick": "Meine Wahl"},
}

_SCRIPTS = (("ja", re.compile(r"[぀-ヿ]")), ("ko", re.compile(r"[가-힯ᄀ-ᇿ]")),
            ("zh", re.compile(r"[一-鿿]")), ("ru", re.compile(r"[Ѐ-ӿ]")))


def _feed():
    # The feed imports this module; this one reads the feed's events and cards.
    from .panels import feed
    return feed


def _base(lang: str) -> str:
    return str(lang).split("-")[0].lower()


def _sigmoid(z: float) -> float:
    return 1 / (1 + math.exp(-z)) if z >= 0 else math.exp(z) / (1 + math.exp(z))


# ------------------------------------------------------------------ features --

def language(text: str, source_lang: str) -> str:
    """The language a thing is written in, from its script, its source's language telling Latin ones apart."""
    for code, script in _SCRIPTS:
        if script.search(text):
            # Han alone is Chinese or Japanese: the source says which, and which Chinese.
            return source_lang if code == "zh" and _base(source_lang) in ("zh", "ja") else code
    return source_lang if source_lang and _base(source_lang) not in ("zh", "ja", "ko", "ru") else "en"


def _length(item: Item, shaped: dict) -> str:
    if shaped["kind"] == "video":
        n = item.length
        return "" if not n else "short" if n < VIDEO_SHORT else "mid" if n <= VIDEO_LONG else "long"
    n = len(item.text) or len(shaped["text"])
    return "short" if n < TEXT_SHORT else "mid" if n < TEXT_LONG else "long"


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def hosts(item: Item, shaped: dict) -> set[str]:
    """The hosts a thing needs: its page's and its player's (`situation.gate` takes each as its platform,
    so www.youtube-nocookie.com counts as youtube.com)."""
    return {_host(item.url), _host(shaped["player"]) if shaped["player"] else ""} - {""}


def readable(runtime: Path) -> set[str]:
    return {_base(lang) for lang in situation.readable(runtime)}


class Reader:
    """What a snapshot needs from the runtime, read once: the picked topics, the topics the owner said no
    to, and the sources' languages."""

    def __init__(self, runtime: Path, topics: Optional[list[str]] = None):
        from . import profile
        from .sources import catalog
        feed = _feed()
        self.runtime = Path(runtime)
        topics = feed.load_topics(self.runtime / feed.TASTE_FILE) if topics is None else topics
        self.topics = [(t.casefold(), feed.topic_matcher([t])) for t in topics]
        self.avoid = [(t.casefold(), feed.topic_matcher([t])) for t in profile.avoided(self.runtime)]
        self.langs = {k: s.lang for k, s in catalog.all_sources(catalog.load_choice(self.runtime)["own"]).items()}

    def snapshot(self, item: Item, shaped: dict, now: float) -> dict:
        """The facts the model reads, as they are at `now`; kept in the event as they are."""
        text = " ".join((shaped["title"], shaped["text"], shaped["site"])).casefold()
        return {"origin": "src:" + item.source if item.source else "site:" + shaped["site"],
                "kind": shaped["kind"], "len": _length(item, shaped),
                "lang": language(shaped["title"] + " " + shaped["text"][:200], self.langs.get(item.source, "")),
                "fresh": round(0.5 ** (max(0.0, now - item.seen_at) / DAY), 4),
                "judged": bool(item.judged or item.love >= 0), "fits": bool(item.fits), "love": item.love,
                "topics": [name for name, matcher in self.topics if matcher.search(text)],
                "avoid": [name for name, matcher in self.avoid if matcher.search(text)],
                "tags": [str(t) for t in item.tags][:8], "host": _host(item.url), "site": shaped["site"]}


def vector(snap: dict, read: set[str], families: tuple = ()) -> dict[str, float]:
    """A snapshot as sparse features. `families` adds the ones still waiting on the replay ("tags")."""
    x = {"bias": 1.0, "origin:" + snap["origin"]: 1.0, "kind:" + snap["kind"]: 1.0, "fresh": snap["fresh"]}
    if snap["len"]:
        x["len:" + snap["len"]] = 1.0
    if _base(snap["lang"]) not in read:
        x["unread_lang"] = 1.0
    if snap["judged"]:
        x["judged"] = 1.0
    if snap["fits"]:
        x["char_fits"] = 1.0
    if snap["love"] > 0:
        x["char_love"] = snap["love"] / 3
    for topic in snap["topics"]:
        x["topic:" + topic] = 1.0
    for topic in snap.get("avoid", ()):
        x["avoid:" + topic] = 1.0
    if "tags" in families:
        for tag in snap["tags"]:
            x["tag:" + tag] = 1.0
    return x


def features(item: Item, shaped: dict, runtime: Path, now: float) -> dict[str, float]:
    return vector(Reader(runtime).snapshot(item, shaped, now), readable(runtime))


class Priors:
    """(m0, q0) per feature: the defaults, a hidden source pushed down, the owner's own "not this"
    rules from the profile, then the situation's. The replay passes the sources hidden by then and
    leaves the profile's rules out, since it cannot tell when each was made."""

    def __init__(self, runtime: Path, hidden: Optional[set[str]] = None, rules: bool = True):
        from . import profile
        self.table = dict(PRIORS)
        if hidden is None:
            hidden = {key for key, row in weights.load(runtime).items() if row["hides"]}
        if rules:
            hidden = set(hidden) | profile.hidden_sources(runtime)
            for topic in profile.avoided(runtime):
                self.table["avoid:" + topic.casefold()] = self.table["topic:" + topic.casefold()] = profile.AVOID_TOPIC
        self.table.update({"origin:src:" + key: HIDDEN for key in hidden})
        self.table.update(situation.priors(runtime))

    def __call__(self, name: str) -> tuple[float, float]:
        return self.table.get(name) or FAMILIES.get(name.split(":", 1)[0], (0.0, 1.0))


# -------------------------------------------------------------------- labels --

def history(events: list, until: float = math.inf) -> dict[str, dict]:
    """Per thing, what had happened to it by `until`: its first snapshot, slot and surface, and the reactions."""
    found: dict[str, dict] = {}
    for at, ident, action, site, kind, *extra in events:
        if at > until:
            continue
        extra = extra[0] if extra and isinstance(extra[0], dict) else {}
        h = found.get(ident)
        if h is None:
            h = found[ident] = {"f": extra.get("f"), "at": at, "s": extra.get("s", ""), "p": extra.get("p", ""),
                                "r": extra.get("r"), "site": site, "kind": kind, "open": False, "like": False,
                                "skip": False, "hide": False, "play": 0.0, "acted": None}
        h["f"] = h["f"] or extra.get("f")
        if action == "seen":
            h["s"] = h["s"] or extra.get("s", "")
            continue
        h["acted"] = at
        if action == "open":
            h["open"] = True
        elif action == "like":
            h["like"], h["skip"] = True, False
        elif action == "unlike":
            h["like"] = False
        elif action == "skip":
            h["skip"] = True
        elif action == "hide_source":
            h["like"], h["skip"], h["hide"] = False, True, True
        elif action == "play":
            h["play"] = max(h["play"], float(extra.get("play_s") or 0))
    return found


def reacted(h: dict) -> Optional[int]:
    """1 for a thing opened, played or liked, 0 for one skipped or hidden, None when nothing was done."""
    if h["hide"] or h["like"] or h["skip"]:
        return int(h["like"])
    return 1 if h["open"] or h["play"] > 0 else None


def label(h: dict, until: float) -> Optional[tuple[int, float, float]]:
    """(y, confidence, when) from a thing's final mark by `until`, or None while it says nothing yet."""
    if h["hide"]:
        y, c = HIDE
    elif h["like"]:
        y, c = LIKE
    elif h["skip"]:
        y, c = SKIP
    elif h["play"] >= PLAY_MIN_S:
        y, c = PLAY
    elif h["open"] or h["play"] > 0:
        # A short play in the app's player is an open: play time only ever adds confidence.
        y, c = OPEN
    elif until - h["at"] >= QUIET_S:
        return 0, SHOWN_CARD if h["s"] in PROMINENT else SHOWN_LIST, h["at"] + QUIET_S
    else:
        return None
    return y, c, h["acted"]


def rows(events: list, until: float, read: set[str], rebuild: Callable[[str, float], Optional[dict]],
         families: tuple = ()) -> tuple[list, int]:
    """One training row (x, y, c, id) per thing with a label by `until`, and how many could not be rebuilt:
    an old event without a snapshot whose thing the library no longer has."""
    found, lost = [], 0
    for ident, h in history(events, until).items():
        got = label(h, until)
        if got is None:
            continue
        snap = h["f"] or rebuild(ident, h["at"])
        if snap is None:
            lost += 1
            continue
        y, c, at = got
        found.append((vector(snap, read, families), y, c * 0.5 ** (max(0.0, until - at) / DAY / HALF_DAYS), ident))
    return found, lost


# ----------------------------------------------------------------------- fit --

def solve(data: list, prior: Callable[[str], tuple[float, float]], start: Optional[dict] = None
          ) -> tuple[dict[str, float], dict[str, float]]:
    """Cyclic coordinate Newton on ½Σq0(w-m0)² + Σc[log(1+e^z) - yz]: posterior means and precisions."""
    cols: dict[str, list] = {}
    for j, row in enumerate(data):
        for k, v in row[0].items():
            cols.setdefault(k, []).append((j, v))
    start = start or {}
    w = {k: start.get(k, prior(k)[0]) for k in cols}
    z = [sum(w[k] * v for k, v in row[0].items()) for row in data]
    ys, cs = [row[1] for row in data], [row[2] for row in data]

    def newton(k: str) -> tuple[float, float]:
        m0, q0 = prior(k)
        g, h = q0 * (w[k] - m0), q0
        for j, v in cols[k]:
            p = _sigmoid(z[j])
            g += cs[j] * (p - ys[j]) * v
            h += cs[j] * p * (1 - p) * v * v
        return g, h

    for _ in range(SWEEPS):
        moved = 0.0
        for k in sorted(cols):
            g, h = newton(k)
            step = max(-STEP_MAX, min(STEP_MAX, -g / h))
            w[k] += step
            for j, v in cols[k]:
                z[j] += step * v
            moved = max(moved, abs(step))
        if moved < TOLERANCE:
            break
    return w, {k: newton(k)[1] for k in cols}


def loss(data: list, w: dict, prior: Callable) -> float:
    """The objective `solve` lowers, for checking that it does."""
    total = sum(0.5 * prior(k)[1] * (v - prior(k)[0]) ** 2 for k, v in w.items())
    for x, y, c, *_ in data:
        z = sum(w.get(k, prior(k)[0]) * v for k, v in x.items())
        total += c * (max(z, 0) + math.log1p(math.exp(-abs(z))) - y * z)
    return total


class _Rebuild:
    """An old event's snapshot rebuilt from the thing as the library has it now."""

    def __init__(self, runtime: Path, reader: Reader):
        self.items = {item.id: item for item in Library(runtime).items()}
        self.reader = reader

    def __call__(self, ident: str, at: float) -> Optional[dict]:
        item = self.items.get(ident)
        shaped = _feed().shape(item, {}) if item else None
        return self.reader.snapshot(item, shaped, at) if shaped else None


def _model_path(runtime: Path) -> Path:
    return Path(runtime) / MODEL_FILE


_models: dict[Path, tuple[int, dict]] = {}
# The last few fits this process has read, so a cursor's later pages rank with the fit its first page had.
_kept: dict[Path, list[dict]] = {}
KEPT_FITS = 8


def load(runtime: Path) -> dict:
    """The last fit: {at, rows, lost, m, q}; an empty one before the first."""
    path = _model_path(runtime)
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        empty = {"at": 0.0, "rows": 0, "lost": 0, "m": {}, "q": {}}
        _kept.setdefault(path, [empty])
        return empty
    hit = _models.get(path)
    if hit is None or hit[0] != stamp:
        hit = _models[path] = (stamp, json.loads(path.read_text(encoding="utf-8")))
        _kept[path] = (_kept.get(path, []) + [hit[1]])[-KEPT_FITS:]
    return hit[1]


def load_at(runtime: Path, at: float) -> dict:
    """The newest fit made by `at` that this process still has, else the last one."""
    last = load(runtime)
    made = [m for m in _kept.get(_model_path(runtime), []) if m["at"] <= at]
    return max(made, key=lambda m: m["at"]) if made else last


def train(runtime: Path, now: Optional[float] = None) -> dict:
    """Fit on every reaction so far and write the model; what was written."""
    runtime = Path(runtime)
    now = life.clock() if now is None else now
    feed = _feed()
    events = feed._load(runtime / feed.TASTE_FILE)
    data, lost = rows(events, now, readable(runtime), _Rebuild(runtime, Reader(runtime)))
    m, q = solve(data, Priors(runtime), load(runtime)["m"])
    model = {"at": now, "rows": len(data), "lost": lost, "m": {k: round(v, 5) for k, v in m.items()},
             "q": {k: round(v, 5) for k, v in q.items()}}
    atomic_write_text(_model_path(runtime), json.dumps(model, ensure_ascii=False), fsync=False)
    return model


_fitting = threading.Lock()
_pending: dict[str, threading.Timer] = {}
_last: dict[str, float] = {}


def fit(runtime: Path) -> None:
    """Refit soon in a worker thread, at most once every REFIT_S; never inside the feed's lock."""
    key = str(Path(runtime))
    with _fitting:
        if key in _pending:
            return
        wait = max(0.0, _last.get(key, -REFIT_S) + REFIT_S - time.monotonic())
        timer = _pending[key] = threading.Timer(wait, _refit, (Path(runtime), key))
        timer.daemon = True
        timer.start()


def _refit(runtime: Path, key: str) -> None:
    with _fitting:
        del _pending[key]
        _last[key] = time.monotonic()
    try:
        train(runtime)
    except Exception:
        logger.exception("taste: the fit failed; the last model stays")


def due(runtime: Path, events: list, now: float) -> bool:
    """A thing shown before has since become a quiet no the last fit did not count."""
    at = load(runtime)["at"]
    return any(e[2] == "seen" and at < e[0] + QUIET_S <= now for e in events)


def enabled(runtime: Path) -> bool:
    """The model ranks unless the person's FEED_MODEL switch (the situation row "feed_model") is off;
    then the old point sum does."""
    return situation.value(runtime, "feed_model") is not False


# --------------------------------------------------------------------- score --

class Sampler:
    """One Thompson draw of the weights, the same for every thing scored with one seed."""

    def __init__(self, model: dict, prior: Callable, seed: int):
        self.m, self.q, self.prior, self.seed = model["m"], model["q"], prior, seed
        self.drawn: dict[str, float] = {}

    def mean(self, k: str) -> float:
        return self.m[k] if k in self.m else self.prior(k)[0]

    def theta(self, k: str) -> float:
        if k not in self.drawn:
            q = self.q.get(k) or self.prior(k)[1]
            self.drawn[k] = self.mean(k) + ALPHA * random.Random(f"{self.seed}:{k}").gauss(0, 1) / math.sqrt(q)
        return self.drawn[k]

    def score(self, x: dict) -> tuple[float, float]:
        """The sampled score and the posterior mean's."""
        return sum(self.theta(k) * v for k, v in x.items()), sum(self.mean(k) * v for k, v in x.items())


def score(runtime: Path, feats: dict[str, float], seed: int) -> float:
    return Sampler(load(runtime), Priors(runtime), seed).score(feats)[0]


def pick_share(events: list) -> int:
    """k_c: how many of each WINDOW go to the character's picks, from how its picks did against the model's."""
    n = {"character": [0, 0], "model": [0, 0]}
    for h in history(events).values():
        slot = "character" if h["p"] == "character" else "model" if h["p"] in ("model", "explore") else ""
        if slot:
            n[slot][0] += 1
            n[slot][1] += bool(h["open"] or h["like"] or h["play"] >= PLAY_MIN_S)
    r_c, r_m = ((1 + pos) / (2 + count) for count, pos in (n["character"], n["model"]))
    if r_c > 1.2 * r_m:
        return 2
    return 0 if n["character"][0] >= 10 and r_c < 0.5 * r_m else 1


def labels(lang: str) -> dict:
    lang = "zh-Hant" if lang == "zh-TW" else lang
    return LABELS.get(lang) or LABELS.get(_base(lang)) or LABELS["en"]


def _topic_name(topic: str, lang: str) -> str:
    names = _feed().SUGGESTED.get(topic, ((topic, topic), ()))[0]
    return names[1] if _base(lang) == "zh" else names[0]


# What the ranking last served of each thing, for the events and shown.jsonl to say where it stood.
served: dict[str, dict] = {}
_serving = threading.Lock()


class Ranker:
    """Scores, reasons and the character's slot for one ranking at `at`."""

    def __init__(self, runtime: Path, topics: list[str], at: float, seed: int, lang: str = "",
                 hidden: Optional[set[str]] = None):
        self.reader = Reader(runtime, list(topics))
        self.read = readable(runtime)
        self.prior = Priors(runtime, hidden)
        self.sampler = Sampler(load_at(runtime, at), self.prior, seed)
        self.at, self.labels, self.lang = at, labels(lang), lang
        self.info: dict[str, dict] = {}

    def score(self, item: Item, shaped: dict) -> float:
        x = vector(self.reader.snapshot(item, shaped, self.at), self.read)
        s, mean = self.sampler.score(x)
        # Each term as the posterior mean has it and as the draw that placed the thing had it.
        self.info[item.id] = {"s": s, "mean": mean, "terms": {k: self.sampler.mean(k) * v for k, v in x.items()},
                              "drawn": {k: self.sampler.theta(k) * v for k, v in x.items()}}
        return s

    def reason(self, ident: str, shaped: dict) -> tuple[str, str]:
        """The label for the largest term the score used besides the character's own: a site or a topic
        the person's reactions or picks lifted, in the posterior and in this draw alike, or the draw itself;
        ("", "") when none says enough."""
        info = self.info[ident]
        best, key = REASON_MIN, ""
        for k, term in info["terms"].items():
            if k.startswith(("origin:", "topic:")) and term > best and info["drawn"][k] > REASON_MIN:
                best, key = term, k
        if key.startswith("origin:"):
            return "origin", self.labels["origin"].format(site=shaped["site"])
        if key.startswith("topic:"):
            return "topic", self.labels["topic"].format(topic=_topic_name(key[6:], self.lang))
        if info["s"] - info["mean"] > EXPLORE_MIN:
            return "explore", self.labels["explore"]
        return "", ""

    def picks(self, rows: list, k: int) -> tuple[list, set[str]]:
        """`rows` (seen first-flag, ..., item last) with k of each WINDOW given to the best loved unseen
        things not placed yet, moved up to PICK_BY in their window when they stood lower."""
        unseen = sum(1 for row in rows if not row[0])
        candidates = sorted((row for row in rows if not row[0] and row[-1].love >= PICK_LOVE),
                            key=lambda row: -row[-1].love)
        rows, chosen = list(rows), set()
        targets = [PICK_BY - 1] if k == 1 else [PICK_BY // 2 - 1, PICK_BY - 1][:k]
        for start in range(0, unseen, WINDOW):
            for target in targets:
                place = {id(row): n for n, row in enumerate(rows)}
                row = next((r for r in candidates if r[-1].id not in chosen and place[id(r)] >= start), None)
                if row is None:
                    return rows, chosen
                chosen.add(row[-1].id)
                target = min(start + target, unseen - 1)
                if place[id(row)] > target:
                    rows.remove(row)
                    rows.insert(target, row)
        return rows, chosen

    def finish(self, shaped: dict, rank: int, pick: bool) -> None:
        """Mark a served thing with its reason, pick and slot, and remember where it stood."""
        key, text = self.reason(shaped["id"], shaped)
        slot = "character" if pick else "explore" if key == "explore" else "model"
        shaped.update(reason=text, reason_key=key, is_pick=pick, pick=self.labels["pick"] if pick else "",
                      slot=slot)
        info = self.info[shaped["id"]]
        top = sorted(info["terms"].items(), key=lambda kv: -kv[1])[:3]
        with _serving:
            served.pop(shaped["id"], None)
            served[shaped["id"]] = {"r": rank, "p": slot, "s": round(info["s"], 4),
                                    "lift": round(info["s"] - info["mean"], 4),
                                    "top": [[k, round(v, 3)] for k, v in top]}
            while len(served) > SERVED_MAX:
                served.pop(next(iter(served)))


def shown(runtime: Path, item: Item, surface: str, rank: Optional[int], now: float, host: str,
          slot: str = "") -> None:
    """One line in shown.jsonl for a thing the person was shown; the file keeps the last SHOWN_MAX."""
    path = Path(runtime) / SHOWN_FILE
    there = served.get(item.id, {})
    append_jsonl(path, {"at": now, "id": item.id, "surface": surface, "rank": there.get("r") if rank is None else rank,
                        "s": there.get("s"), "lift": there.get("lift"), "top": there.get("top", []),
                        "slot": slot or there.get("p", ""), "host": host,
                        "gated": bool(host) and not situation.gate(runtime, host=host)})
    # About 300 bytes a line: trimmed back once it is well past the cap.
    if path.stat().st_size > SHOWN_MAX * 450:
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        atomic_write_text(path, "".join(lines[-SHOWN_MAX:]), fsync=False)


# ------------------------------------------------------------------- numbers --

def numbers(runtime: Path, now: Optional[float] = None, days: int = 7) -> dict:
    """The week in numbers, for settings: what each surface's showings led to, play time, how much of the
    list's opens came from its top 5, the character's picks against the model's, and its learned weights."""
    runtime = Path(runtime)
    now = life.clock() if now is None else now
    feed = _feed()
    since = now - days * DAY
    events = feed._load(runtime / feed.TASTE_FILE)
    recent = [e for e in events if e[0] >= since]
    surfaces: dict[str, dict] = {}
    top5 = opens = 0
    for h in history(recent).values():
        row = surfaces.setdefault(h["s"] or "other", {"shown": 0, "open": 0, "like": 0, "skip_hide": 0})
        row["shown"] += 1
        row["open"] += h["open"] or h["play"] >= PLAY_MIN_S
        row["like"] += h["like"]
        row["skip_hide"] += h["skip"]
        if h["open"] and h["s"] == "list":
            opens += 1
            top5 += h["r"] is not None and h["r"] < 5
    for row in surfaces.values():
        for k in ("open", "like", "skip_hide"):
            row[k + "_rate"] = round(row[k] / row["shown"], 3)
    played = sum(float(e[5].get("play_s") or 0) for e in recent if e[2] == "play" and len(e) > 5)
    picks = {"character": [0, 0], "model": [0, 0]}
    for h in history(recent).values():
        slot = "character" if h["p"] == "character" else "model" if h["p"] in ("model", "explore") else ""
        if slot:
            picks[slot][0] += 1
            picks[slot][1] += h["like"]
    model = load(runtime)
    prior = Priors(runtime)
    learned = {}
    for k in ("char_fits", "char_love", "judged"):
        q = model["q"].get(k) or prior(k)[1]
        learned[k] = {"mean": round(model["m"].get(k, prior(k)[0]), 3), "sd": round(1 / math.sqrt(q), 3)}
    try:
        shown_lines = (runtime / SHOWN_FILE).read_text(encoding="utf-8").splitlines()
    except OSError:
        shown_lines = []
    gated_hosts = 0
    for line in shown_lines[-SHOWN_MAX:]:
        row = json.loads(line)
        # Whether its host was down when it was shown, not now.
        gated_hosts += row["at"] >= since and bool(row.get("gated"))
    return {"days": days, "surfaces": surfaces, "play_s": round(played), "list_opens": opens,
            "list_opens_top5_share": round(top5 / opens, 3) if opens else None,
            "picks": {slot: {"shown": n, "liked": pos, "like_rate": round(pos / n, 3) if n else None}
                      for slot, (n, pos) in picks.items()},
            "k_c": pick_share(events), "learned": learned, "model": {"at": model["at"], "rows": model["rows"]},
            "shown_on_gated_hosts": gated_hosts, "on": enabled(runtime)}


# -------------------------------------------------------------------- replay --

def auc(pairs: list[tuple[float, int]]) -> Optional[float]:
    """The chance a random positive outscores a random negative, ties counted half."""
    pos = sum(y for _, y in pairs)
    neg = len(pairs) - pos
    if not pos or not neg:
        return None
    ordered = sorted(pairs, key=lambda p: p[0])
    rank_sum, n = 0.0, 0
    while n < len(ordered):
        end = n
        while end < len(ordered) and ordered[end][0] == ordered[n][0]:
            end += 1
        rank_sum += (n + end + 1) / 2 * sum(y for _, y in ordered[n:end])
        n = end
    return (rank_sum - pos * (pos + 1) / 2) / (pos * neg)


def _logloss(p: float, y: int) -> float:
    p = min(1 - 1e-6, max(1e-6, p))
    return -math.log(p if y else 1 - p)


def _metrics(days: list[list[dict]], name: str) -> dict:
    flat = [row for day in days for row in day]
    top = [row["y"] for day in days for row in sorted(day, key=lambda r: -r[name + "_s"])[:5]]
    return {"auc": auc([(row[name + "_s"], row["y"]) for row in flat]),
            "logloss": sum(_logloss(row[name + "_p"], row["y"]) for row in flat) / len(flat) if flat else None,
            "top5": sum(top) / len(top) if top else None}


def _ci(values: list[float]) -> list[Optional[float]]:
    values = sorted(v for v in values if v is not None)
    if not values:
        return [None, None]
    return [round(values[int(0.025 * (len(values) - 1))], 4), round(values[int(0.975 * (len(values) - 1))], 4)]


def _day_start(at: float) -> float:
    return datetime.combine(datetime.fromtimestamp(at).date(), datetime.min.time()).timestamp()


def replay(runtime: Path, resamples: int = 1000, seed: int = 0, families: tuple = ("tags",)) -> dict:
    """Prequential replay over the person's own reactions in time order: each day is predicted by models fit
    only on what was known when it began: the old point sum against this model's posterior mean, and this
    model with each family still waiting on the replay. AUC (opened, played or liked against skipped or
    hidden), log loss (each score calibrated on the days before) and the top-5 positive rate, each with a
    day-block bootstrap 95% CI."""
    runtime = Path(runtime)
    feed = _feed()
    events = sorted(feed._load(runtime / feed.TASTE_FILE), key=lambda e: e[0])
    reader = Reader(runtime)
    rebuild = _Rebuild(runtime, reader)
    read = readable(runtime)
    by_source = {}
    for ident, h in history(events).items():
        snap = h["f"] or rebuild(ident, h["at"])
        if snap and snap["origin"].startswith("src:"):
            by_source[ident] = snap["origin"][4:]
    starts = sorted({_day_start(e[0]) for e in events})
    days: list[list[dict]] = []
    calibration: dict[str, list] = {}
    warm: dict[str, dict] = {"model": {}, "tags": {}}
    lost_ids: set[str] = set()
    for start in starts:
        end = start + DAY
        test = []
        for ident, h in history(events, end).items():
            y = reacted(h)
            if y is None or not start <= h["acted"] < end:
                continue
            snap = h["f"] or rebuild(ident, h["at"])
            if snap is None:
                lost_ids.add(ident)
                continue
            test.append((ident, h, snap, y))
        if not test:
            continue
        # What the person had hidden when the day began; the profile's rules are left out (see Priors).
        prior = Priors(runtime, {by_source[e[1]] for e in events
                                 if e[2] == "hide_source" and e[0] < start and e[1] in by_source}, rules=False)
        fits = {}
        for name, fam in (("model", ()), ("tags", ("tags",))):
            if name != "model" and name not in families:
                continue
            data, _ = rows(events, start, read, rebuild, fam)
            fits[name] = solve(data, prior, warm[name])[0]
            warm[name] = fits[name]
        # The old point sum, as feed.score had it when the day began.
        then = feed._marks(events, start)[0]
        old_taste = feed._taste(then)
        acted = sum(1 for mark in then.values() if mark["open"] or mark["like"] or mark["skip"])
        topical = feed.TOPIC * 0.5 ** (acted / feed.TOPIC_HALF)
        learned = feed._by_source(then, by_source)
        # Each score becomes a probability the same way, by a logistic fit on the days before's reacted
        # things: the old sum has no scale, and the model is fit on quiet noes the test leaves out.
        platt = {name: solve(rows_, lambda k: (0.0, 1.0))[0] if rows_ else {} for name, rows_ in calibration.items()}
        day = []
        for ident, h, snap, y in test:
            days_old = math.log(max(snap["fresh"], 1e-9)) / math.log(0.5)
            row = {"y": y, "old_s": feed.score({"site": snap["site"], "kind": snap["kind"]},
                                               int(h["at"] - days_old * DAY), snap["fits"], old_taste, h["at"],
                                               topical if snap["topics"] else 0,
                                               feed.source_points(learned.get(by_source.get(ident))))}
            for name, w in fits.items():
                x = vector(snap, read, ("tags",) if name == "tags" else ())
                row[name + "_s"] = sum(w.get(k, prior(k)[0]) * v for k, v in x.items())
            for name in ("old", *fits):
                a = platt.get(name, {})
                row[name + "_p"] = _sigmoid(a.get("bias", 0.0) + a.get("s", 0.0) * row[name + "_s"])
                calibration.setdefault(name, []).append(({"bias": 1.0, "s": row[name + "_s"]}, y, 1.0))
            day.append(row)
        days.append(day)
    rng = random.Random(seed)
    names = ["old", "model"] + [f for f in families if f in warm]
    point = {name: _metrics(days, name) for name in names}
    boot = {name: {"auc": [], "logloss": [], "top5": []} for name in names}
    delta = {name: {"auc": [], "logloss": []} for name in names if name != "old"}
    for _ in range(resamples if days else 0):
        sample = [days[rng.randrange(len(days))] for _ in days]
        got = {name: _metrics(sample, name) for name in names}
        for name in names:
            for k in ("auc", "logloss", "top5"):
                boot[name][k].append(got[name][k])
        for name, base in (("model", "old"), *((f, "model") for f in names[2:])):
            if got[name]["auc"] is not None and got[base]["auc"] is not None:
                delta[name]["auc"].append(got[name]["auc"] - got[base]["auc"])
            delta[name]["logloss"].append(got[name]["logloss"] - got[base]["logloss"])
    n = sum(len(day) for day in days)
    report = {"reacted": n, "days": len(days), "lost": len(lost_ids),
              "scores": {name: {k: {"value": None if v is None else round(v, 4), "ci": _ci(boot[name][k])}
                                for k, v in point[name].items()} for name in names},
              "delta": {name: {k: _ci(v) for k, v in d.items()} for name, d in delta.items()}}
    low = report["delta"]["model"]["auc"][0] if n else None
    worse = (point["model"]["logloss"] or 0) > (point["old"]["logloss"] or 0)
    report["ship"] = {"enough": n >= 100, "auc_noninferior": low is not None and low > -0.02,
                      "logloss_no_worse": bool(n) and not worse}
    report["ship"]["passes"] = all(report["ship"].values())
    for name in names[2:]:
        d = report["delta"][name]
        lowers = (point[name]["logloss"] or 0) < (point["model"]["logloss"] or 0)
        report.setdefault("families", {})[name] = (
            "helps" if lowers and d["auc"][1] is not None and d["auc"][1] >= 0 else "no split")
    report.setdefault("families", {}).update({"sim": "not built", "ctx": "not built"})
    return report


def _print(report: dict) -> None:
    print(f"reacted things: {report['reacted']} over {report['days']} days; "
          f"{report['lost']} could not be rebuilt (old events whose things are gone)")
    print(f"{'':8}{'AUC':>24}{'log loss':>26}{'top-5 positive':>26}")
    for name, got in report["scores"].items():
        cells = [f"{got[k]['value']} [{got[k]['ci'][0]}, {got[k]['ci'][1]}]" for k in ("auc", "logloss", "top5")]
        print(f"{name:8}" + "".join(f"{c:>26}" for c in cells))
    for name, d in report["delta"].items():
        print(f"delta {name}: AUC {d['auc']}, log loss {d['logloss']}")
    ship = report["ship"]
    print(f"ship rule: >=100 reacted {ship['enough']}, AUC CI low > -0.02 {ship['auc_noninferior']}, "
          f"log loss no worse {ship['logloss_no_worse']} -> {'passes' if ship['passes'] else 'does not pass'}")
    print("families: " + ", ".join(f"{k} {v}" for k, v in report["families"].items()))


def main(argv: Optional[list[str]] = None) -> None:
    from .paths import runtime_dir
    parser = argparse.ArgumentParser(prog="python -m persona_agent.taste")
    parser.add_argument("command", choices=["replay"])
    parser.add_argument("--runtime", type=Path, default=None, help="the runtime folder (default: this home's)")
    parser.add_argument("--resamples", type=int, default=1000)
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)
    report = replay(args.runtime or runtime_dir(), args.resamples)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        _print(report)


if __name__ == "__main__":
    main()
