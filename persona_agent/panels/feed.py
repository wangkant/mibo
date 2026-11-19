"""The feed: what the character found on its walks, ranked for its person by
what they do with it.

Every reaction from the Feed page or the pet's card is kept as an event in
`<runtime>/feed.json`. Taste is read back from those events: the sites and
kinds of the things the person opened and liked count for a thing, the ones
they skipped count against it. The topics the person named on the first run
are kept in the same file and count before there is any behaviour to go on.
A thing a public source brought also counts what was learned of that source
(`sources.weights`, fed from `remember`), and no source fills more than
SOURCE_CAP of any PAGE_WINDOW things in a row.

The ranking itself is the person's model in `taste` (a Bayesian logistic
regression with Thompson draws, and the character's pick slot); `score` is the
old point sum, kept for the FEED_MODEL switch and for the replay to compare
against. Each event is [at, id, action, site, kind, extra], extra holding the
model's snapshot of the thing at that moment (older events have five).
Things whose host cannot be reached now (`situation.gate`) are never shown.
"""
from __future__ import annotations

import asyncio
import json
import re
import threading
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import Request

from .. import langs, life, situation
from .. import taste as model
from ..library import DISMISSED, KEPT, Item, Library
from ..sources import weights
from ..storage import atomic_write_text

TASTE_FILE = "feed.json"
# "hide_source" is "less like this source": the thing is skipped and its source read and ranked far less.
# "play" carries the seconds the app's own player ran, sent when it stops or the card closes.
ACTIONS = ("seen", "open", "like", "unlike", "skip", "hide_source", "play")
PLAY_MAX_S = 24 * 3600
# One event per item and action at most, so this holds a few thousand things.
EVENTS_MAX = 8000
LIMIT = 20
LIMIT_MAX = 100
# The desktop is shown nothing new sooner than this after the last thing it showed.
QUIET_S = 300
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
# an excerpt or a site's name. A topic the person typed is found as itself.
SUGGESTED = {
    "tech": (("Tech", "科技"), ("tech", "technology", "gadget", "smartphone", "iphone", "android", "chip",
                               "semiconductor", "hardware", "the verge", "科技", "数码", "手机", "芯片", "硬件",
                               "华为", "小米")),
    "ai": (("AI", "AI"), ("ai", "llm", "llms", "gpt", "chatgpt", "openai", "anthropic", "claude", "gemini",
                          "deepseek", "machine learning", "deep learning", "neural", "人工智能", "大模型",
                          "机器学习", "深度学习", "神经网络", "智能体")),
    "games": (("Games", "游戏"), ("game", "games", "gaming", "gamer", "steam", "nintendo", "playstation", "xbox",
                                 "esports", "游戏", "电竞", "手游", "主机", "任天堂", "原神")),
    "anime": (("Anime", "动画"), ("anime", "manga", "bangumi", "动画", "动漫", "番剧", "新番", "漫画", "二次元")),
    "music": (("Music", "音乐"), ("music", "song", "songs", "album", "concert", "band", "spotify", "musician",
                                 "音乐", "歌曲", "老歌", "新歌", "专辑", "演唱会", "乐队", "说唱", "翻唱")),
    "film": (("Film", "电影"), ("film", "films", "movie", "movies", "cinema", "trailer", "box office", "netflix",
                               "director", "电影", "影视", "剧集", "票房", "导演", "预告", "纪录片")),
    "science": (("Science", "科学"), ("science", "scientists", "physics", "chemistry", "biology", "astronomy",
                                     "space", "nasa", "arxiv", "nature", "quantum", "科学", "物理", "化学", "生物",
                                     "天文", "航天", "论文", "宇宙")),
    "finance": (("Finance", "财经"), ("finance", "financial", "market", "markets", "stock", "stocks", "economy",
                                     "economic", "inflation", "bank", "bitcoin", "investor", "财经", "金融", "经济",
                                     "股市", "美股", "a股", "基金", "通胀", "央行")),
    "design": (("Design", "设计"), ("design", "designer", "ui", "ux", "typography", "font", "fonts", "figma",
                                    "architecture", "设计", "字体", "排版", "建筑")),
    "food": (("Food", "美食"), ("food", "recipe", "recipes", "cooking", "baking", "bread", "chef",
                               "restaurant", "kitchen", "美食", "菜谱", "做饭", "烹饪", "烘焙", "面包", "餐厅", "下厨")),
    "sports": (("Sports", "运动"), ("sport", "sports", "football", "soccer", "nba", "basketball", "tennis",
                                    "olympic", "olympics", "f1", "marathon", "fitness", "运动", "体育", "足球",
                                    "篮球", "网球", "奥运", "健身", "跑步")),
    "history": (("History", "历史"), ("history", "historical", "historian", "ancient", "archaeology", "empire",
                                     "medieval", "历史", "古代", "考古", "王朝", "文物")),
    "programming": (("Programming", "编程"), ("programming", "programmer", "code", "coding", "developer",
                                             "developers", "python", "javascript", "typescript", "rust", "golang",
                                             "github", "open source", "compiler", "software", "hacker news",
                                             "stack overflow", "编程", "代码", "程序员", "开发者", "开源", "前端",
                                             "后端")),
    "travel": (("Travel", "旅行"), ("travel", "trip", "tourism", "tourist", "flight", "flights", "hotel",
                                    "旅行", "旅游", "攻略", "景点", "出行", "自驾")),
    "books": (("Books", "读书"), ("book", "books", "novel", "novels", "reading", "author", "literature",
                                 "读书", "书单", "小说", "作家", "阅读", "文学")),
}

ERRORS: frozenset[str] = frozenset({"feed_action", "feed_cursor", "feed_topics", "feed_no_source",
                                    "situation_invalid"})

# The page answers reactions on worker threads; one writer at a time.
_lock = threading.Lock()


# ------------------------------------------------------------------ events --

def _read(path: Path) -> dict:
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return saved if isinstance(saved, dict) else {}


def _load(path: Path) -> list:
    events = _read(path).get("events")
    return [e for e in events if isinstance(e, list) and (len(e) == 5 or len(e) == 6 and isinstance(e[5], dict))]\
        if isinstance(events, list) else []


def load_topics(path: Path) -> list[str]:
    topics = _read(path).get("topics")
    return [t for t in topics if isinstance(t, str)] if isinstance(topics, list) else []


def _save(path: Path, events: list, topics: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps({"events": events[-EVENTS_MAX:], "topics": topics}, ensure_ascii=False))


def _marks(events: list, until: Optional[float] = None) -> tuple[dict, float]:
    """What the person had done with each thing by `until`, and when the
    desktop last showed something."""
    marks: dict[str, dict] = {}
    shown = 0.0
    for at, ident, action, site, kind, *extra in events:
        if until is not None and at > until:
            continue
        mark = marks.setdefault(ident, {"seen": False, "open": False, "like": False, "skip": False,
                                        "hide": False, "play": 0.0, "site": site, "kind": kind})
        mark["seen"] = True
        if action == "seen":
            shown = max(shown, at)
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
        elif action == "play":
            mark["play"] = max(mark["play"], float(extra[0].get("play_s") or 0))
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
    taste = _taste(_marks(_load(Path(runtime) / TASTE_FILE))[0])
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


def source_points(row: Optional[dict]) -> float:
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


def _word(word: str) -> str:
    # A Latin word is found whole, so "ai" is not found in "said"; Chinese has no spaces to look for.
    if word.isascii():
        return r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])"
    return re.escape(word)


def topic_matcher(topics: list[str]) -> Optional[re.Pattern]:
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
    return re.compile("|".join(_word(w.casefold()) for w in sorted(words, key=len, reverse=True)))


def on_topic(shaped: dict, matcher: Optional[re.Pattern]) -> bool:
    return bool(matcher and matcher.search(" ".join((shaped["title"], shaped["text"], shaped["site"])).casefold()))


# ------------------------------------------------------------------- items --

def shape(item: Item, marks: dict) -> Optional[dict]:
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
            # Set by `ranked`: the line under the character's sentence, and whether this is its own pick.
            "reason": "", "reason_key": "", "is_pick": False, "pick": "", "slot": ""}


def ranked(library: Library, events: list, at: float, topics: list[str] = (), *, seed: Optional[int] = None,
           lang: str = "", picks: bool = True) -> list[tuple[dict, Item]]:
    """Everything not dismissed, not skipped, found by `at` and reachable now, unseen first, then by score:
    the model's draw seeded by `seed` (the cursor's ms unless given), with the character's picks placed
    when `picks`, or the old point sum when the FEED_MODEL switch is off. Reactions after `at` do not move
    anything, so a cursor's pages hold still."""
    runtime = library.root.parent
    then, _ = _marks(events, at)
    now, _ = _marks(events)
    items = library.items()
    learned = _by_source(then, {item.id: item.source for item in items})
    # A source the person asked to see less of: as it stood at `at`, like every other mark.
    hidden = {key for key, row in learned.items() if row["hides"]}
    ranker = None
    if model.enabled(runtime):
        ranker = model.Ranker(runtime, list(topics), at, int(at * 1000) if seed is None else seed, lang, hidden)
        if model.due(runtime, events, life.clock()):
            model.fit(runtime)
    else:
        taste = _taste(then)
        matcher = topic_matcher(list(topics))
        acted = sum(1 for mark in then.values() if mark["open"] or mark["like"] or mark["skip"])
        topical = TOPIC * 0.5 ** (acted / TOPIC_HALF)
    reachable: dict[str, bool] = {}

    def up(host: str) -> bool:
        if host not in reachable:
            reachable[host] = situation.gate(runtime, host=host)
        return reachable[host]

    rows = []
    for item in items:
        if item.state == DISMISSED or item.seen_at > at or then.get(item.id, {}).get("skip"):
            continue
        shaped = shape(item, now)
        # A thing whose page or player cannot be reached is held back, not shown and not counted against.
        if shaped is not None and all(up(host) for host in model.hosts(item, shaped)):
            seen = bool(then.get(item.id, {}).get("seen"))
            if ranker:
                points = ranker.score(item, shaped)
            else:
                points = score(shaped, item.seen_at, item.fits, taste, at,
                               topical if on_topic(shaped, matcher) else 0, source_points(learned.get(item.source)))
            rows.append((seen, -points, -item.seen_at, item.id, shaped, item))
    rows.sort(key=lambda row: row[:4])
    # A walk's finds have no source: their site stands in. A source the person asked to see less of
    # goes after everything, so the cap never pulls its things up.
    shown = spread([row for row in rows if row[5].source not in hidden],
                   lambda row: row[5].source or "site:" + row[4]["site"])
    chosen: set[str] = set()
    if ranker and picks:
        shown, chosen = ranker.picks(shown, model.pick_share(events))
    rows = shown + [row for row in rows if row[5].source in hidden]
    if ranker:
        for rank, row in enumerate(rows):
            ranker.finish(row[4], rank, row[3] in chosen)
    return [(row[4], row[5]) for row in rows]


def _cursor(before: str) -> tuple[int, int]:
    ms, _, start = before.partition(".")
    if not (ms.isdigit() and start.isdigit()) or len(before) > 40:
        raise ValueError("feed_cursor")
    return int(ms), int(start)


def feed(library: Library, events: list, limit: int = LIMIT, before: str = "",
         now: Optional[float] = None, topics: list[str] = (), *, lang: str = "") -> dict:
    """One page; `next` carries the moment of the first page, in milliseconds
    since a page marks what it shows at once, and where the next one starts.
    The same milliseconds seed the model's draw, so a cursor's pages hold still."""
    limit = max(1, min(LIMIT_MAX, int(limit or LIMIT)))
    ms, start = _cursor(before) if before else (int((life.clock() if now is None else now) * 1000), 0)
    rows = ranked(library, events, ms / 1000, topics, seed=ms, lang=lang)
    end = start + limit
    # Skipped since the first page: left out here without moving where the next page starts.
    skipped = {ident for ident, mark in _marks(events)[0].items() if mark["skip"]}
    return {"items": [shaped for shaped, _ in rows[start:end] if shaped["id"] not in skipped],
            "next": f"{ms}.{end}" if end < len(rows) else ""}


# What the pet's card was handed, by id, so a find it opens in the chat keeps the character's line and slot.
on_card: dict[str, dict] = {}


def remember(runtime: Path, item: Item, action: str, now: Optional[float] = None, *, surface: str = "",
             rank: Optional[int] = None, play_s: float = 0.0, slot: str = "") -> None:
    """Keep one reaction with the model's snapshot of the thing at that moment, where it was shown
    (`surface`: card, list or chat), at which `rank` and in which `slot` (model, explore or character,
    as the ranking served it when the page does not say), and what it says of the item's source; one that
    changes nothing is not kept again, and a "play" only when it ran longer than any before. Every
    showing also goes to shown.jsonl, and any reaction but a showing asks the model to refit soon."""
    path = Path(runtime) / TASTE_FILE
    shaped = shape(item, {})
    at = round(life.clock() if now is None else now, 3)
    there = model.served.get(item.id, {})
    rank = there.get("r") if rank is None else rank
    slot = slot or there.get("p", "")
    if action == "seen":
        model.shown(runtime, item, surface, rank, at, model._host(item.url), slot)
    extra = {"f": model.Reader(runtime).snapshot(item, shaped, at) if shaped else None, "r": rank, "s": surface,
             "p": slot}
    if action == "play":
        extra["play_s"] = round(play_s, 1)
    with _lock:
        events = _load(path)
        mark = _marks(events)[0].get(item.id)
        done = {"seen": mark and mark["seen"], "open": mark and mark["open"], "like": mark and mark["like"],
                "unlike": not (mark and mark["like"]), "skip": mark and mark["skip"],
                "hide_source": mark and mark["hide"], "play": play_s <= (mark["play"] if mark else 0)}[action]
        if done:
            return
        events.append([at, item.id, action, shaped["site"] if shaped else item.site,
                       shaped["kind"] if shaped else "text", extra])
        _save(path, events, load_topics(path))
        # The app's own play time only raises the model's confidence; the source learns nothing from it.
        if item.source and action != "play":
            if action == "hide_source":
                weights.hidden(runtime, item.source)
            # Hiding a source skips the thing too, unless it was skipped already.
            if action != "hide_source" or not (mark and mark["skip"]):
                weights.reacted(runtime, item.source, "skip" if action == "hide_source" else action, mark is None)
    if action != "seen":
        model.fit(runtime)


def keep_topics(runtime: Path, topics: list[str]) -> None:
    path = Path(runtime) / TASTE_FILE
    with _lock:
        _save(path, _load(path), topics)


# ------------------------------------------------------------------ routes --

class Feed:
    def __init__(self, workspace):
        self.ws = workspace

    def _path(self) -> Path:
        return self.ws._runtime() / TASTE_FILE

    def _events(self) -> list:
        return _load(self._path())

    def _lang(self, lang: str) -> str:
        return langs.normalize(lang) or langs.normalize(self.ws.config().get("AGENT_LANG")) or "en"

    def page(self, limit: int, before: str, lang: str = "") -> dict:
        return feed(self.ws._library(), self._events(), limit, before, topics=load_topics(self._path()),
                    lang=self._lang(lang))

    async def next(self) -> dict:
        """The character's choice for the card (`recommend`), unless the desktop showed something a moment
        ago; nothing while it is being chosen, and the pet is told to look again once it is (news)."""
        events = await asyncio.to_thread(self._events)
        if life.clock() - _marks(events)[1] < QUIET_S:
            return {"item": None}
        chosen = await self.ws.chooser.take("card")
        if chosen is None:
            return {"item": None}
        on_card[chosen[0]["id"]] = chosen[0]
        return {"item": chosen[0]}

    def numbers(self) -> dict:
        from .. import profile
        runtime = self.ws._runtime()
        return {**model.numbers(runtime), "calls": profile.calls(runtime)}

    def situation(self) -> dict:
        return situation.view(self.ws._runtime())

    def set_situation(self, payload: dict) -> dict:
        name = payload.get("name")
        if not isinstance(name, str):
            raise ValueError("situation_invalid")
        situation.set_value(self.ws._runtime(), name, payload.get("value"))
        return self.situation()

    def interests(self, lang: str) -> dict:
        lang = langs.normalize(lang) or langs.normalize(self.ws.config().get("AGENT_LANG")) or "en"
        return {"topics": load_topics(self._path()), "suggested": suggested(lang)}

    def choose(self, payload: dict) -> dict:
        keep_topics(self.ws._runtime(), clean_topics(payload.get("topics")))
        return self.interests(payload.get("lang") or "")

    async def react(self, payload: dict) -> dict:
        action = payload.get("action")
        if action not in ACTIONS:
            raise ValueError("feed_action")
        item = self.ws._item(payload)
        if action == "hide_source" and not item.source:
            raise ValueError("feed_no_source")
        surface, rank, play_s = payload.get("surface") or "", payload.get("rank"), payload.get("play_s") or 0
        slot = payload.get("slot") or ""
        if (surface not in model.SURFACES and surface != "" or slot not in ("", "model", "explore", "character")
                or rank is not None and (not isinstance(rank, int) or isinstance(rank, bool) or rank < 0)
                or not isinstance(play_s, (int, float)) or isinstance(play_s, bool)
                or not 0 <= play_s <= PLAY_MAX_S or action == "play" and not play_s):
            raise ValueError("feed_action")
        await asyncio.to_thread(remember, self.ws._runtime(), item, action, surface=surface, rank=rank,
                                play_s=float(play_s), slot=slot)
        if action in ("like", "unlike"):
            # A liked thing is a kept one: the days and the chat see the same choice.
            await self.ws.mark_item(item.id, "keep", action == "like")
        elif action in ("skip", "hide_source"):
            self.ws.fold_card(item.id, action)
        return {"ok": True}


def mount(app, workspace, body) -> None:
    panel = Feed(workspace)

    @app.get("/api/feed")
    async def feed_page(limit: int = LIMIT, before: str = "", lang: str = ""):
        return await asyncio.to_thread(panel.page, limit, before, lang)

    @app.get("/api/feed/next")
    async def feed_next():
        return await panel.next()

    @app.get("/api/feed/numbers")
    async def feed_numbers():
        return await asyncio.to_thread(panel.numbers)

    # The situation table's view and the person's corrections (see `situation`).
    @app.get("/api/situation")
    async def situation_view():
        return await asyncio.to_thread(panel.situation)

    @app.post("/api/situation")
    async def situation_set(request: Request):
        return await asyncio.to_thread(panel.set_situation, await body(request))

    # The person's "check again now": the down hosts tried at once, then a round that retries the blocked
    # sources (the sources panel mounts the rounds as app.state.sources before any request comes).
    @app.post("/api/situation/check")
    async def situation_check():
        return await app.state.sources.check_again()

    @app.post("/api/feed/react")
    async def feed_react(request: Request):
        return await panel.react(await body(request))

    @app.get("/api/feed/interests")
    async def feed_interests(lang: str = ""):
        return await asyncio.to_thread(panel.interests, lang)

    @app.post("/api/feed/interests")
    async def feed_interests_choose(request: Request):
        return await asyncio.to_thread(panel.choose, await body(request))
