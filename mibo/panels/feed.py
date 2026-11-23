"""The feed: what the character found on its walks, ranked for its person by
what they do with it.

Every reaction from the pet's card, the chat or the 推荐记录 list is kept as an event in
the runtime database's `feed_events` table (db.py). Taste is read back from those events: the sites and
kinds of the things the person opened and liked count for a thing, the ones
they skipped count against it. The topics the person named on the first run
are kept beside them (`feed_topics`) and count before there is any behaviour to go on, and so do the platforms
they chose (`feed_platforms`, keys of platforms.py).
A thing a public source brought also counts what was learned of that source
(`sources.weights`, fed from `remember`), and no source fills more than
SOURCE_CAP of any PAGE_WINDOW things in a row.

The ranking itself is the person's model in `taste` (a Bayesian logistic
regression with Thompson draws, and the character's pick slot); `score` is the
old point sum, kept for the FEED_MODEL switch and for the replay to compare
against. Each event is [at, id, action, site, kind, extra], extra holding the
model's snapshot of the thing at that moment.
Things whose host cannot be reached now (`situation.gate`) are never shown.
The page's routes for all of it are in feedpage.py.
"""
from __future__ import annotations

import functools
import json
import re
from collections import Counter, deque
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from .. import browsed, db, life, platforms, profile, situation, subjects
from .. import taste as model
from ..library import DISMISSED, KEPT, Item, Library
from ..sources import weights
from ..web import signin

# "hide_source" is "less like this source": the thing is skipped and its source read and ranked far less.
# "play" carries the seconds the app's own player ran, sent when it stops or the card closes; "read" the
# seconds a find stayed in front in the app's own browser. "end" is how the pet's card went (ENDS), with
# the seconds it was out.
# "talk": the person answered the thing in the chat (welcome.py keeps it; the page does not send it).
ACTIONS = ("seen", "open", "like", "unlike", "skip", "hide_source", "play", "read", "end", "talk")
# Opened, liked, closed by the person (within QUICK_S it is "quick"), gone by itself, or put away with the
# pet (a game came to the front). One gone by itself while the person was away is kept as "away".
# "next": passed over for another at once (the card's "Another"). "known": the person had seen it already,
# which says nothing of their taste.
ENDS = ("open", "like", "close", "timeout", "hushed", "next", "known")
# What a no on a card or in the chat's menu was about: this thing, or its kind of topic (then the topic's
# feature leans to less, profile "leans"). "Less from this source" is the action "hide_source".
SAID_ABOUT = ("thing", "topic")
QUICK_S = 3
# The first run's round of sample finds, at most FIRST_PER_SOURCE from one source.
FIRST_MAX = 10
FIRST_PER_SOURCE = 2
# A sample find's summary is at least this wide, a Chinese character counting two (one of a video platform needs
# none: its title and cover say what it is).
SUMMARY_MIN = 60
# A title that is only a name and a version number ("llm-gemini 0.38"): a release, not a thing to read.
RELEASE = re.compile(r"[\w.-]+ v?\d+(\.\d+)+[a-z]*\d*", re.I)
# Shops and booking sites by their name: their pages are for buying and booking, not for reading.
ERRAND_SITES = frozenset({"taobao", "tmall", "jd", "pinduoduo", "yangkeduo", "suning", "amazon", "ebay", "aliexpress",
                          "etsy", "temu", "shein", "walmart", "bestbuy", "rakuten", "mercari", "coupang", "ozon",
                          "wildberries", "zalando", "mercadolivre", "mercadolibre", "meituan", "ele", "ctrip", "trip",
                          "fliggy", "ly", "qunar", "tuniu", "12306", "booking", "expedia", "agoda", "airbnb",
                          "skyscanner", "kayak", "hotels"})
# Query keys that only say where a visitor came from: a front page with them is still the front page.
TRACKING = ("utm_", "ref", "spm", "from", "source", "share")
# One event per item and action at most, so this holds a few thousand things; the oldest go past it.
EVENTS_MAX = 8000
LIMIT = 20
LIMIT_MAX = 100
# Points a site or kind earns for each thing of it liked, opened or skipped, and their bound.
LIKE, OPEN, SKIP = 2, 1, -2
TASTE_MAX = 6
# Worth this much when just found, half of it a day later, a quarter two days later.
FRESH = 4.0
# The character itself thought this one fits its person.
FITS = 2.0
# A thing on a topic the person named: above a fresh one from yesterday at first,
# half of that once they have reacted to TOPIC_HALF things, since by then what they do says more.
TOPIC = 5.0
TOPIC_HALF = 40
TOPICS_MAX = 30
TOPIC_LEN = 40
# Points per unit of a source's learned exponent (-3 to 2), and taken off for each "less like this source".
SOURCE = 1.0
SOURCE_HIDDEN = 12.0
# At most this many things from one source in any this many in a row.
SOURCE_CAP, PAGE_WINDOW = 3, LIMIT

# The topics offered on the first run, with their names and the words that find them in a title,
# an excerpt or a site's name (subjects.py holds them, each with the finer subjects under it). A topic the
# person typed is found as itself.
SUGGESTED = {key: (subjects.SUBJECTS[key][1], subjects.words(key)) for key in subjects.OFFERED}

# ------------------------------------------------------------------ events --

_EVENT = "SELECT at, id, action, site, kind, extra FROM feed_events"


def _rows(found: list) -> list:
    # Every extra in one parse: far quicker than one parse a row.
    extras = json.loads("[" + ",".join(row[5] for row in found) + "]")
    return [[*row[:5], extra] for row, extra in zip(found, extras)]


def events(runtime: Path, since: float = 0) -> list:
    """Every event (or those at `since` or later), oldest first: [at, id, action, site, kind, extra]."""
    return _rows(db.at(runtime).read(_EVENT + " WHERE at >= ? ORDER BY n", (since,)))


def of(runtime: Path, ident: str) -> list:
    """One thing's events, oldest first."""
    return _rows(db.at(runtime).read(_EVENT + " WHERE id = ? ORDER BY n", (ident,)))


def _numbered(conn, where: str = "", args=()) -> list:
    """Events oldest first, each with its row number last: [at, id, action, site, kind, extra, n]."""
    return [[at, ident, action, site, kind, json.loads(extra), n] for at, ident, action, site, kind, extra, n
            in conn.execute(f"SELECT at, id, action, site, kind, extra, n FROM feed_events {where} ORDER BY n", args)]


def _add(conn, event: list) -> None:
    """One event at the end; past EVENTS_MAX the oldest go."""
    conn.execute("INSERT INTO feed_events (at, id, action, site, kind, extra) VALUES (?,?,?,?,?,?)",
                 (*event[:5], json.dumps(event[5], ensure_ascii=False)))
    conn.execute("DELETE FROM feed_events WHERE n <= (SELECT n FROM feed_events ORDER BY n DESC LIMIT 1 OFFSET ?)",
                 (EVENTS_MAX,))


def load_topics(runtime: Path) -> list[str]:
    return [topic for topic, in db.at(runtime).read("SELECT topic FROM feed_topics ORDER BY n")]


def load_platforms(runtime: Path) -> list[str]:
    """The platforms the person chose, as platforms.py keys; none is no preference."""
    return [key for key, in db.at(runtime).read("SELECT key FROM feed_platforms ORDER BY n") if platforms.known(key)]


def _marks(events: list, until: float | None = None) -> tuple[dict, float]:
    """What the person had done with each thing by `until`, and when the
    desktop last showed something."""
    marks: dict[str, dict] = {}
    shown = 0.0
    for at, ident, action, site, kind, *extra in events:
        if until is not None and at > until:
            continue
        mark = marks.setdefault(ident, {"seen": False, "open": False, "like": False, "skip": False,
                                        "hide": False, "play": 0.0, "end": "", "site": site, "kind": kind,
                                        "walled": False})
        mark["seen"] = True
        if action == "seen":
            shown = max(shown, at)
        elif action == "walled":
            mark["walled"] = True
        elif action == "open":
            mark["open"] = True
        elif action == "like":
            mark["like"], mark["skip"] = True, False
        elif action == "unlike":
            mark["like"] = False
        elif action == "skip":
            mark["skip"] = True
        elif action == "hide_source":
            mark["like"], mark["skip"], mark["hide"] = False, True, True
        elif action in ("play", "read"):
            mark["play"] = max(mark["play"], float(extra[0].get(action + "_s") or 0))
        elif action == "end":
            mark["end"] = extra[0].get("end") or ""
    return marks, shown


def _taste(marks: dict) -> dict[str, float]:
    """Points per "site:<name>" and "kind:<name>", each kept within TASTE_MAX."""
    points: dict[str, float] = {}
    for mark in marks.values():
        earned = LIKE * mark["like"] + OPEN * mark["open"] + SKIP * mark["skip"]
        if earned:
            for key in ("site:" + mark["site"], "kind:" + mark["kind"]):
                points[key] = points.get(key, 0) + earned
    return {key: max(-TASTE_MAX, min(TASTE_MAX, value)) for key, value in points.items()}


def site_taste(runtime: Path) -> dict[str, float]:
    """Points per site from the person's reactions, for the walks to lean on."""
    taste = _taste(_marks(events(runtime))[0])
    return {key[5:]: value for key, value in taste.items() if key.startswith("site:")}


def _by_source(marks: dict, sources: dict[str, str]) -> dict[str, dict]:
    """What `weights` learns of each source, read from these marks: the same points, as of the marks' moment."""
    rows: dict[str, dict] = {}
    for ident, mark in marks.items():
        key = sources.get(ident)
        if key:
            row = rows.setdefault(key, {"items": 0, "points": 0.0, "hides": 0})
            row["items"] += 1
            row["points"] += weights.POINTS["seen"] + sum(weights.POINTS[a] for a in ("open", "like", "skip") if mark[a])
            row["hides"] += mark["hide"]
    return rows


def source_points(row: dict | None) -> float:
    """What was learned of the source that brought a thing, as points; 0 for a walk's find."""
    return SOURCE * weights.learned(row) - SOURCE_HIDDEN * (row["hides"] if row else 0)


def score(shaped: dict, found_at: int, fits: bool, taste: dict, now: float, topical: float = 0.0,
          source: float = 0.0) -> float:
    """Its site's points, half its kind's, freshness, FITS when the character said it fits,
    `topical` when it is on a topic the person named, and its source's points."""
    days = max(0.0, now - found_at) / 86400
    return (taste.get("site:" + shaped["site"], 0) + taste.get("kind:" + shaped["kind"], 0) / 2
            + FRESH * 0.5 ** days + (FITS if fits else 0) + topical + source)


def spread(rows: list, origin) -> list:
    """`rows` in their order, except that a row whose origin already has SOURCE_CAP of the
    last PAGE_WINDOW placed waits for the next row that may go; when none may, the best goes."""
    queues: dict = {}
    for n, row in enumerate(rows):
        queues.setdefault(origin(row), deque()).append((n, row))
    placed, recent, counts = [], deque(), {}
    while queues:
        allowed = [key for key in queues if counts.get(key, 0) < SOURCE_CAP]
        key = min(allowed or queues, key=lambda k: queues[k][0][0])
        placed.append(queues[key].popleft()[1])
        if not queues[key]:
            del queues[key]
        recent.append(key)
        counts[key] = counts.get(key, 0) + 1
        if len(recent) > PAGE_WINDOW:
            gone = recent.popleft()
            counts[gone] -= 1
    return placed


# ------------------------------------------------------------------ topics --

def _names(lang: str) -> int:
    return 1 if str(lang).startswith("zh") else 0


def suggested(lang: str) -> list[dict]:
    zh = _names(lang)
    return [{"key": key, "name": names[zh]} for key, (names, _) in SUGGESTED.items()]


def clean_topics(raw) -> list[str]:
    if not isinstance(raw, list):
        raise ValueError("feed_topics")
    topics, seen = [], set()
    for value in raw:
        topic = " ".join(str(value or "").split())[:TOPIC_LEN]
        if topic and topic.casefold() not in seen:
            seen.add(topic.casefold())
            topics.append(topic)
    return topics[:TOPICS_MAX]


def clean_platforms(raw) -> list[str]:
    """The platforms a page sent: every one a key platforms.py knows, or the whole list is refused, since what is
    kept steers what the app reads."""
    if not isinstance(raw, list) or not all(isinstance(key, str) and platforms.known(key) for key in raw):
        raise ValueError("feed_platforms")
    return list(dict.fromkeys(raw))


def offered_platforms(runtime: Path, lang: str) -> list[dict]:
    """The platforms to choose from for a reader of `lang` (platforms.offered), then any chosen that is not among
    them: {key, name, reach, connected}, connected when the person is signed in to it in the app's browser."""
    shown = platforms.offered([lang, *sorted(situation.readable(runtime))], situation.value(runtime, "region"))
    shown += [platforms.PLATFORMS[key] for key in load_platforms(runtime) if platforms.PLATFORMS[key] not in shown]
    saved = signin.load(runtime / "desktop")
    return [{"key": p.key, "name": p.name(lang), "reach": p.reach, "connected": _signed_in(saved, p.key)}
            for p in shown]


def _signed_in(saved: dict, key: str) -> bool:
    entry = saved.get(key) or {}
    return entry.get("state") == "in" and not entry.get("gone")


def _word(word: str) -> str:
    # A Latin word is found whole, so "ai" is not found in "said"; Chinese has no spaces to look for.
    if word.isascii():
        return r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])"
    return re.escape(word)


def topic_matcher(topics: list[str]) -> re.Pattern | None:
    """One pattern for every word the person's topics stand for, or None without topics."""
    named = {}
    for key, (names, words) in SUGGESTED.items():
        for name in (key, *names):
            named[name.casefold()] = words
    words = set()
    for topic in topics:
        words.update(named.get(topic.casefold(), (topic,)))
    if not words:
        return None
    # Longest first, so "open source" is tried before "source" would be.
    return re.compile("|".join(subjects._word(w.casefold()) for w in sorted(words, key=len, reverse=True)))


def on_topic(shaped: dict, matcher: re.Pattern | None) -> bool:
    return bool(matcher and matcher.search(" ".join((shaped["title"], shaped["text"], shaped["site"])).casefold()))


@functools.lru_cache(maxsize=8)
def _matchers(topics: tuple) -> tuple:
    # The person's own topics that no subject stands for: found as themselves.
    return tuple((t.casefold(), topic_matcher([t])) for t in topics if not subjects.named(t))


class Veins:
    """A thing's source (its site for a walk's find) and what it is about, its subjects and the person's
    own topics: no two in a row share either where there is a choice."""

    def __init__(self, topics: list[str]):
        self.matchers = _matchers(tuple(topics))

    def of(self, shaped: dict, item: Item) -> tuple[str, frozenset]:
        text = " ".join((shaped["title"], shaped["text"], shaped["site"])).casefold()
        about = subjects.of(shaped["title"], " ".join((shaped["text"], shaped["site"], *map(str, item.tags))))
        return (item.source or "site:" + shaped["site"],
                frozenset(about) | frozenset(name for name, matcher in self.matchers if matcher.search(text)))

    @staticmethod
    def same(a: tuple | None, b: tuple | None, topics: bool = True) -> bool:
        return bool(a and b and (a[0] == b[0] or (topics and a[1] & b[1])))

    def last(self, library: Library, events: list) -> tuple | None:
        """The vein of the last thing the pet's card or the main chat brought."""
        for _at, ident, action, *rest in reversed(events):
            extra = rest[2] if len(rest) > 2 else {}
            if action == "seen" and extra.get("s") in ("card", "chat"):
                item = library.get(ident)
                shaped = shape(item, {}) if item else None
                return self.of(shaped, item) if shaped else None
        return None

    def varied(self, rows: list, last: tuple | None = None, mix: bool = False) -> list:
        """(shaped, item) rows in their order, except that each goes after one from another source and on
        other topics where one is left; failing that, from another source. With `mix`, text and video take
        turns where both are left."""
        veins = {row[1].id: self.of(*row) for row in rows}
        left, placed, video = list(rows), [], None
        while left:
            apart = [r for r in left if not self.same(veins[r[1].id], last)]
            row = ((mix and next((r for r in apart if is_video(r[1], r[0]) != video), None))
                   or next(iter(apart), None)
                   or next((r for r in left if not self.same(veins[r[1].id], last, False)), left[0]))
            left.remove(row)
            placed.append(row)
            last, video = veins[row[1].id], is_video(row[1], row[0])
        return placed


def is_video(item: Item, shaped: dict) -> bool:
    return item.kind == "video" or shaped["kind"] == "video"


# ------------------------------------------------------------------- items --

def shape(item: Item, marks: dict) -> dict | None:
    """One thing as the feed draws it, from the same card the days and the chat use."""
    card = life.clean_card(item.card())
    if card is None:
        return None
    player = card["embed"]
    kind = "video" if item.kind == "video" and player else "page" if card["readable"] else "text"
    return {"id": item.id, "kind": kind, "title": card["title"], "words": " ".join(item.why.split()),
            "text": card["excerpt"], "site": card["site"], "url": card["url"], "player": player,
            "picture": card["picture"], "source": item.source,
            "at": datetime.fromtimestamp(item.seen_at).astimezone().isoformat(timespec="seconds"),
            "seen": bool(marks.get(item.id, {}).get("seen")), "liked": item.state == KEPT,
            # Set by `ranked`: the feature the ranking's reason rests on, and the slot that served it.
            "reason_term": "", "slot": ""}


def errand(url: str) -> bool:
    """A page to go to or to do something on rather than a thing to read: a site's front page, a sign-in,
    account or payment page, or a shop's or a booking site's page."""
    parts = urlsplit(url)
    query = [key for key, _ in parse_qsl(parts.query) if not key.lower().startswith(TRACKING)]
    return ((parts.path.strip("/").lower() in ("", "index.html", "index.htm", "index.php") and not query)
            or browsed.secret(url) or browsed.site_of(parts.hostname or "").split(".")[0] in ERRAND_SITES)


def presentable(shaped: dict, video: bool = False) -> bool:
    """A sample find for the first run: a real title, a summary that says something (not for one of a `video`
    platform) and a picture."""
    title = shaped["title"].strip()
    width = sum(2 if ord(c) > 0x2E80 else 1 for c in shaped["text"])
    return bool(title and title != shaped["site"] and not RELEASE.fullmatch(title)
                and (video or width >= SUMMARY_MIN) and shaped["picture"])


def ranked(library: Library, events: list, at: float, topics: list[str] = (), *, seed: int | None = None,
           picks: bool = True, since: float = 0) -> list[tuple[dict, Item]]:
    """Everything not dismissed, not skipped, found by `at` (and at `since` or later), reachable now and a thing
    to read (not an `errand`), unseen first, then by score:
    the model's draw seeded by `seed` (the cursor's ms unless given), with the character's picks placed
    when `picks`, or the old point sum when the FEED_MODEL switch is off; things on a topic the person said
    they do not want, then those of a source they hid, after all the rest. Reactions after `at` do not move
    anything, so a cursor's pages hold still."""
    runtime = library.root.parent
    then, _ = _marks(events, at)
    now, _ = _marks(events)
    items = library.items(since=since)
    learned = _by_source(then, library.sources())
    # A source the person asked to see less of: as it stood at `at`, like every other mark.
    hidden = {key for key, row in learned.items() if row["hides"]}
    ranker = None
    if model.enabled(runtime):
        ranker = model.Ranker(runtime, list(topics), at, int(at * 1000) if seed is None else seed, hidden, events)
        if model.due(runtime, events, life.clock()):
            model.fit(runtime)
    else:
        taste = _taste(then)
        matcher = topic_matcher(list(topics))
        acted = sum(1 for mark in then.values() if mark["open"] or mark["like"] or mark["skip"])
        topical = TOPIC * 0.5 ** (acted / TOPIC_HALF)
    reachable: dict[str, bool] = {}
    # A site and kind whose find opened to a sign-in or a check: held back while the person is signed out there.
    walls = {(mark["site"], mark["kind"]) for mark in now.values() if mark["walled"]}
    signed: dict[str, bool] = {}

    def up(host: str) -> bool:
        if host not in reachable:
            reachable[host] = situation.gate(runtime, host=host)
        return reachable[host]

    def held(shaped: dict) -> bool:
        if (shaped["site"], shaped["kind"]) not in walls:
            return False
        if shaped["site"] not in signed:
            signed[shaped["site"]] = signin.signed_in(runtime / "desktop", shaped["url"])
        return not signed[shaped["site"]]

    rows = []
    for item in items:
        if item.state == DISMISSED or item.seen_at > at or then.get(item.id, {}).get("skip") \
                or now.get(item.id, {}).get("walled"):
            continue
        shaped = shape(item, now)
        if shaped is None or errand(shaped["url"]) or held(shaped):
            continue
        # A thing whose page or player cannot be reached is held back, not shown and not counted against.
        if all(up(host) for host in model.hosts(item, shaped)):
            seen = bool(then.get(item.id, {}).get("seen"))
            if ranker:
                points = ranker.score(item, shaped)
            else:
                points = score(shaped, item.seen_at, item.fits, taste, at,
                               topical if on_topic(shaped, matcher) else 0, source_points(learned.get(item.source)))
            rows.append((seen, -points, -item.seen_at, item.id, shaped, item))
    rows.sort(key=lambda row: row[:4])
    # A topic the person said they do not want is a rule, not a weight: its things go after everything
    # else, whatever a draw gives them.
    avoid = None if ranker else topic_matcher(profile.avoided(runtime))
    away = {row[3] for row in rows if (ranker.info[row[3]]["away"] if ranker else on_topic(row[4], avoid))}
    # A walk's finds have no source: their site stands in. A source the person asked to see less of
    # goes after everything, so the cap never pulls its things up.
    shown = spread([row for row in rows if row[5].source not in hidden and row[3] not in away],
                   lambda row: row[5].source or "site:" + row[4]["site"])
    chosen: set[str] = set()
    if ranker and picks:
        shown, chosen = ranker.picks(shown, model.pick_share(events))
    rows = (shown + [row for row in rows if row[5].source not in hidden and row[3] in away]
            + [row for row in rows if row[5].source in hidden])
    if ranker:
        for rank, row in enumerate(rows):
            ranker.finish(row[4], rank, row[3] in chosen)
            row[4]["reason_term"] = ranker.info[row[3]]["term"]
    return [(row[4], row[5]) for row in rows]


def shown(library: Library, events: list, kept: bool = False, limit: int = LIMIT, before: str = "") -> dict:
    """One page of what the person was shown, newest first: each thing a card, the chat, the first run or the
    app's browser put in front of them, at its first showing, unless they turned it down since; with `kept`,
    the things they liked instead, at their last like. `before` is the `next` of the page above it: the
    milliseconds and id of its last row. Rows are (at, rank, item), rank the row's place in the whole list."""
    limit = max(1, min(LIMIT_MAX, int(limit or LIMIT)))
    cursor = re.fullmatch(r"(\d{1,16})\.([0-9a-f]{16})", before) if before else None
    if before and not cursor:
        raise ValueError("feed_cursor")
    first, liked = {}, {}
    for at, ident, action, *_ in events:
        first.setdefault(ident, at)
        if action == "like":
            liked[ident] = at
    marks = _marks(events)[0]
    states = library.states()
    if kept:
        rows = [(liked.get(ident, seen_at), ident) for ident, (state, seen_at) in states.items() if state == KEPT]
    else:
        rows = [(at, ident) for ident, at in first.items()
                if ident in states and states[ident][0] != DISMISSED and not marks[ident]["skip"]]
    order = sorted(((-int(at * 1000), ident), at, ident) for at, ident in rows)
    start = 0
    if cursor:
        after = (-int(cursor[1]), cursor[2])
        start = next((n for n, row in enumerate(order) if row[0] > after), len(order))
    page = order[start:start + limit]
    return {"rows": [(at, start + n, library.get(ident)) for n, (_, at, ident) in enumerate(page)],
            "next": f"{-page[-1][0][0]}.{page[-1][2]}" if start + len(page) < len(order) else ""}


def first_round(library: Library, events: list, now: float, topics: list[str], chosen: list[str] = ()) -> list[dict]:
    """The first run's sample finds: the ranking's best unseen that are `presentable`, FIRST_PER_SOURCE from
    one site and FIRST_MAX in all at most, those the character has read first, never two in a row from one
    source or on one topic where there is a choice, and text and video in turn where both are left. A site
    counts as one however many of its lists brought things (a video site has a list for each kind of video);
    only when too few sites have something presentable yet does one give more. Each platform the person chose
    (`chosen`) that has one keeps a place for its best before the rest fill."""
    from ..sources import catalog
    carried = {key: source.platform for key, source in catalog.all_sources([]).items()}
    rows, more, per, reserved = [], [], Counter(), {}
    wanted = set(chosen)

    def waiting() -> bool:
        return len(reserved) < FIRST_MAX and not wanted <= reserved.keys()

    for shaped, item in ranked(library, events, now, topics, seed=int(now * 1000)):
        full = len(rows) >= 3 * FIRST_MAX
        if shaped["seen"] or (full and not waiting()):
            break
        platform = carried[item.source] if item.source in carried else platforms.of_url(item.url)
        if not presentable(shaped, bool(platform) and platforms.PLATFORMS[platform].kind == "video"):
            continue
        site = shaped["site"] or item.source
        if platform in wanted and platform not in reserved and waiting() and per[site] < FIRST_PER_SOURCE:
            per[site] += 1
            reserved[platform] = (shaped, item)
        elif full:
            continue
        elif per[site] < FIRST_PER_SOURCE:
            per[site] += 1
            rows.append((shaped, item))
        else:
            more.append((shaped, item))
    rows.sort(key=lambda row: not row[1].judged)
    kept = {item.id for _, item in reserved.values()}
    shown, room = [], FIRST_MAX - len(kept)
    for row in Veins(topics).varied([*reserved.values(), *rows], mix=True):
        if row[1].id in kept or room > 0:
            shown.append(row)
            room -= row[1].id not in kept
    return [shaped for shaped, _ in shown + more[:FIRST_MAX - len(shown)]]


# What the pet's card was handed, by id, so a find it opens in the chat keeps the character's line and slot.
on_card: dict[str, dict] = {}


def remember(runtime: Path, item: Item, action: str, now: float | None = None, *, surface: str = "",
             rank: int | None = None, play_s: float = 0.0, slot: str = "", end: str = "",
             shown_s: float = 0.0, said: dict | None = None, line: str = "") -> bool:
    """Keep one reaction with the model's snapshot of the thing at that moment, where it was shown
    (`surface`: card, list, chat or first), at which `rank` and in which `slot` (model, explore or character,
    as the ranking served it when the page does not say), and what it says of the item's source; one that
    changes nothing is not kept again, and a "play" or "read" (`play_s` its seconds) only when it ran longer
    than any before; an "end" (`end`, `shown_s`) once. `said`: what the person said of it in the chat
    ({"about", "words"}), which the model counts as more than a plain skip. A showing keeps what its reason
    rests on ("why", recommend.facts; `line` the character's sentence as it brought the thing) and also goes to
    the shown table; any reaction but a showing asks the model to refit soon. Whether it was kept."""
    store = db.at(runtime)
    shaped = shape(item, {})
    at = round(life.clock() if now is None else now, 3)
    there = model.served.get(item.id, {})
    rank = there.get("r") if rank is None else rank
    slot = slot or there.get("p", "")
    if action == "seen":
        model.shown(runtime, item, surface, rank, at, model._host(item.url), slot)
    extra = {"f": model.Reader(runtime, now=at).snapshot(item, shaped, at) if shaped else None, "r": rank,
             "s": surface, "p": slot}
    if action in ("play", "read"):
        extra[action + "_s"] = round(play_s, 1)
    if action == "end":
        extra.update(end=end, shown_s=round(shown_s, 1))
    if said:
        extra["said"] = said
    with store.write() as conn:
        mine = _numbered(conn, "WHERE id = ?", (item.id,))
        mark = _marks(mine)[0].get(item.id)
        # An open again counts once it is a coming back (model.BACK_S after the last one); a talk counts once.
        opened = max((e[0] for e in mine if e[2] == "open"), default=None)
        done = {"seen": mark and mark["seen"], "open": opened is not None and at - opened < model.BACK_S,
                "talk": any(e[2] == "talk" for e in mine), "like": mark and mark["like"],
                "unlike": not (mark and mark["like"]), "skip": mark and mark["skip"],
                "hide_source": mark and mark["hide"], "play": play_s <= (mark["play"] if mark else 0),
                "read": play_s <= (mark["play"] if mark else 0), "end": mark and mark["end"]}[action]
        # A find that opened to a wall says nothing more of the person's taste.
        if done or (mark and mark["walled"]):
            return False
        if action == "seen":
            from .. import recommend
            extra["why"] = recommend.facts(item, extra["f"], slot, surface, there.get("t", ""), line,
                                           model.history(events(runtime)))
        _add(conn, [at, item.id, action, shaped["site"] if shaped else item.site, shaped["kind"] if shaped else "text",
                    extra])
        # Time in the app's player or browser, how a card ended and a talk only tell the model; the source
        # learns nothing from them.
        if item.source and action not in ("play", "read", "end", "talk"):
            if action == "hide_source":
                weights.hidden(runtime, item.source)
            # Hiding a source skips the thing too, unless it was skipped already.
            if action != "hide_source" or not (mark and mark["skip"]):
                weights.reacted(runtime, item.source, "skip" if action == "hide_source" else action, mark is None)
    if action != "seen":
        model.fit(runtime)
    return True


def _drop(conn, gone: list) -> None:
    conn.executemany("DELETE FROM feed_events WHERE n = ?", [(e[6],) for e in gone])


def take_back(runtime: Path, item: Item) -> None:
    """Undo a no: the thing's skip, its "less from this source" and the ending the no gave its card go from
    the events, with what they did to its source's count and to the topic's lean, as if the card were
    still out, and no byte of them is left. An ending from before the no (it was opened, or went by itself)
    stays."""
    store = db.at(runtime)
    with store.write() as conn:
        gone = [e for e in _numbered(conn, "WHERE id = ?", (item.id,)) if (
            e[2] in ("skip", "hide_source") or (e[2] == "end" and e[5]["end"] in ("close", "quick", "known")))]
        _drop(conn, gone)
    store.scrubbed()
    nos = [e for e in gone if e[2] != "end"]
    for event in nos:
        said = event[5].get("said") or {}
        if said.get("key"):
            profile.edit(runtime, {"leans": {said["key"]: said["was"]}})
    if nos and item.source:
        def edit(state: dict) -> None:
            # One skip was counted for the thing, whichever of the two said it first (remember).
            row = state[item.source]
            row["points"] = round(row["points"] - weights.POINTS["skip"], 2)
            row["hides"] -= sum(1 for e in nos if e[2] == "hide_source")

        weights.change(runtime, edit)
    model.fit(runtime)


def walled(runtime: Path, item: Item) -> bool:
    """A find opened in the app's browser came to a sign-in or a check: its open, its time there and the card's
    ending by the open go, with the open's points for its source, so it counts as neither interest nor dislike;
    it is not shown again, and its site's finds of its kind wait while the person is signed out there (`ranked`).
    Whether it was new."""
    with db.at(runtime).write() as conn:
        mine = _numbered(conn, "WHERE id = ?", (item.id,))
        mark = _marks(mine)[0].get(item.id)
        if mark is None or mark["walled"]:
            return False
        gone = [e for e in mine if e[2] in ("open", "read") or (e[2] == "end" and e[5].get("end") == "open")]
        _drop(conn, gone)
        _add(conn, [round(life.clock(), 3), item.id, "walled", mark["site"], mark["kind"], {}])
    if item.source and any(e[2] == "open" for e in gone):
        def edit(state: dict) -> None:
            row = state[item.source]
            row["points"] = round(row["points"] - weights.POINTS["open"], 2)

        weights.change(runtime, edit)
    model.fit(runtime)
    return True


def forget_items(runtime: Path, ids: set[str]) -> None:
    """Things taken out of the library (a page deleted from the browser's history): their events and showings go,
    with no byte of them left, and the model is fitted again without them."""
    store = db.at(runtime)
    ids, gone = list(ids), 0
    with store.write() as conn:
        for n in range(0, len(ids), 500):
            part = ids[n:n + 500]
            marks = ",".join("?" * len(part))
            gone += conn.execute(f"DELETE FROM feed_events WHERE id IN ({marks})", part).rowcount
            gone += conn.execute(f"DELETE FROM shown WHERE id IN ({marks})", part).rowcount
    if gone:
        store.scrubbed()
        model.fit(runtime)


def keep_topics(runtime: Path, topics: list[str]) -> None:
    with db.at(runtime).write() as conn:
        conn.execute("DELETE FROM feed_topics")
        conn.executemany("INSERT INTO feed_topics (topic) VALUES (?)", [(topic,) for topic in topics])


def keep_platforms(runtime: Path, keys: list[str]) -> None:
    """The person's chosen platforms (clean_platforms' keys). Reading a signed-in platform's own feed stays the
    switch in Settings > Connections, which asks first."""
    with db.at(runtime).write() as conn:
        conn.execute("DELETE FROM feed_platforms")
        conn.executemany("INSERT INTO feed_platforms (key) VALUES (?)", [(key,) for key in keys])


def forget_said(runtime: Path, match: re.Pattern) -> int:
    """Blank what `match` finds (casefolded) in the person's words about finds and in the snapshots' liked
    and avoided topics, and take the subjects it names out of the snapshots, so what the model learned of
    them goes with the next fit and no byte of the words is left; for a forget (profile.forget). How many
    events changed."""
    store = db.at(runtime)
    changed = []
    named = {key for key, row in subjects.SUBJECTS.items() if any(match.search(n.casefold()) for n in (key, *row[1]))}
    with store.write() as conn:
        for event in _numbered(conn):
            extra = event[5]
            said, snap = extra.get("said"), extra.get("f")
            hit = isinstance(said, dict) and bool(match.search(str(said.get("words") or "").casefold()))
            if hit:
                said["words"] = ""
            for key in ("likes", "avoid"):
                names = snap.get(key) if isinstance(snap, dict) else None
                if names and any(match.search(str(n).casefold()) for n in names):
                    snap[key] = [n for n in names if not match.search(str(n).casefold())]
                    hit = True
            if isinstance(snap, dict) and named & set(snap.get("subj") or ()):
                snap["subj"] = [k for k in snap["subj"] if k not in named]
                hit = True
            if hit:
                changed.append((json.dumps(extra, ensure_ascii=False), event[6]))
        conn.executemany("UPDATE feed_events SET extra = ? WHERE n = ?", changed)
    if changed:
        store.scrubbed()
    return len(changed)
