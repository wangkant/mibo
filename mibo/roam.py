"""The character's walks: it goes out on its own as a signed-out visitor,
reads pages on any site and brings back what it saw.

The visitor browser (visitor.py) reads a page into a library Item: the facts
the page declares about itself and its readable text (pagefacts.py). A walk
reads a few pages, asks the model once which to keep and why, and keeps those
in the library. Pages are only read; nothing is signed, posted or got around.
"""
from __future__ import annotations

import asyncio
import contextlib
import html
import importlib.util
import json
import logging
import random
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, NamedTuple
from urllib.parse import urlsplit

from . import installed_browser as web
from . import profile, quiet, situation
from .library import Item, Library, item_id
from .llm import purpose
from .pagefacts import (
    PICTURE_FETCH_MAX,
    facts_from,
    host_of,
    host_ok,
    public_address,
    site_name,
    small_picture,
    wall_of,
)
from .panels.feed import load_platforms, site_taste
from .storage import atomic_write_text
from .textproc import (
    _UNTRUSTED_INPUT_RULES,
    _WEB_DESC_CLOSE,
    _WEB_DESC_OPEN,
    SLEEP_HOUR_END,
    SLEEP_HOUR_START,
    _clean_prompt_source,
    _env_tz_offset,
    _fence_user_data,
    salvage_json_object,
    strip_json_fences,
)
from .visitor import IDLE_S, Visitor
from .web import read as reading
from .web import sites
from .web.read import Found

logger = logging.getLogger("mibo.roam")

# What stops a walk; walks switched off in Settings › 外出 are WALKS_OFF.
OUT, ASLEEP, LIMIT, WALKS_OFF, NO_MODEL = "out", "asleep", "limit", "walks_off", "no_model"
# What a host the person favours adds to its place in a walk's order (Settings › 外出), and one of a platform they
# chose (推荐偏好).
FAVOUR = 2.0
CHOSEN = 1.5

# The shortest and the longest the walk loop sleeps between looks.
TICK_S = 30.0
NAP_S = 1800.0
FIRST_WALK_S = 120.0
# Walks a day a lookup may take beyond ROAM_WALKS_A_DAY.
WONDER_EXTRA = 1
KEEP_MAX = 3
PROMPT_EXCERPT = 400
WHY_MAX = 200
TAGS_MAX, TAG_LEN = 5, 30
# What the character's sentence may and may not say; the label under it says what the ranking used.
WHY_RULE = ("The why is one sentence in your own voice about what you yourself see in it. Never say the owner "
             "opened, liked or asked for something like it, and never mention scores or rankings.")
ROW_FORM = ('{"n": <number>, "fits": true or false, "love": <0-3, how much you yourself love it>, '
        '"tags": ["<3-5 short English lowercase tags>"], "why": "<one sentence>"}')

# The web search leg of a walk: its results are read like any other page, each site under its own limit.
WEB = "Web"
WEB_RESULTS = 6
# Pages of one site a walk fails to read before it leaves that site's rows.
UNREAD_MAX = 2
# A thing the character loved this much lends its tags to a walk of its own curiosity.
CURIOUS_LOVE = 2
# The share of walks that follow the tags of what the person opened lately, before their named interests.
THEIRS = 0.25
# General words for a walk with no topic of the owner's; a hot list does the rest.
_GENERAL = {"zh": ("科普", "音乐", "旅行", "美食", "历史", "手工"),
            "en": ("science", "music", "travel", "cooking", "history", "crafts")}


@dataclass
class _Read:
    item: Item
    picture: bytes = b""


@dataclass
class _Plan:
    sources: list = field(default_factory=list)     # (site, host, intent: web, hot or search, words)
    topic: str = ""
    wonder: str = ""                                # the queued words the topic came from
    asked: bool = False                             # the person asked for them, and is told how it went


@dataclass
class _Trip:
    """What one walk did, for the library, the walk record (Settings › 外出) and the report of a lookup."""
    read: list = field(default_factory=list)        # _Read of each page read
    kept: list = field(default_factory=list)        # the ids kept
    places: list = field(default_factory=list)      # the sites whose pages it read
    missed: list = field(default_factory=list)      # (site, why) of each list or page it could not read
    tried: list = field(default_factory=list)       # each list it asked
    skipped: list = field(default_factory=list)     # each page it could not read


# ---------------------------------------------------------------- the walk

class Roam:
    """The walk loop and the reader the rest of the service uses."""

    def __init__(self, agent: Any, *, home: Path, runtime: Path, executable: Path | None = None,
                 clock: Callable[[], float] = time.time, public: Callable[[str], Awaitable[bool]] = public_address,
                 host_check: Callable[[str], bool] = host_ok, hosts: dict | None = None):
        self.agent = agent
        self.settings = agent.settings
        self.library = Library(runtime)
        self.clock = clock
        self.public = public
        self.host_check = host_check
        self.executable = executable
        self.visitor = Visitor(web.visitor_profile(home),executable=executable, host_check=host_check,
                               public=public)
        # The hosts a walk goes to: the seeds' and those learned, or only these cards ({host: {home, hot,
        # search}}, a test's own site).
        for key, entries in (hosts or {}).items():
            sites.plant(runtime, key, entries)
        self.hosts = list(hosts) if hosts else None
        self.state_path = Path(runtime) / "roam.json"
        self.started = clock()
        self.pause = (3.0, 8.0)
        self._wake = asyncio.Event()
        self._walking = False
        self._topics: list[str] = []
        # The words from a chat the walk under way went out for.
        self._wonder = ""
        if self.library.outing().state == "out":
            # A walk the service was stopped in the middle of has ended.
            self.library.returned(0, now=self.started)

    # -- what the life line asks

    def available(self) -> str:
        if importlib.util.find_spec("playwright") is None:
            return web.NO_DRIVER
        if (self.executable or web.find_browser()) is None:
            return web.NO_BROWSER
        if not getattr(self.agent, "enabled", False):
            return NO_MODEL
        return ""

    def _asleep(self, now: float) -> bool:
        return asleep(now, _env_tz_offset())

    def _walks_today(self, now: float) -> int:
        outing = self.library.outing()
        return outing.today if outing.day == time.strftime("%Y-%m-%d", time.localtime(now)) else 0

    def _held(self, now: float, wonder: bool = False) -> str:
        """Why no walk may leave now, "" when one may. A `wonder` walk (words wait) goes in sleep hours too
        and may take WONDER_EXTRA walks beyond the day's."""
        code = self.available()
        if code:
            return code
        if not self.settings.roam_enabled:
            return WALKS_OFF
        if self._walking or self.library.outing().state == "out":
            return OUT
        if not wonder and self._asleep(now):
            return ASLEEP
        if self._walks_today(now) >= self.settings.roam_walks_a_day + (WONDER_EXTRA if wonder else 0):
            return LIMIT
        return ""

    def _wanted(self, now: float) -> bool:
        """Words wait to be looked up (today.wonder) and a walk may leave for them now, the gap aside."""
        from . import today
        return today.waiting(self.library.root.parent) and not self._held(now, wonder=True)

    def request(self) -> str:
        """Words were queued: the loop looks at once, and goes when `_wanted` lets it. Why a walk for them
        cannot leave now, "" when it can (OUT: right after the walk under way)."""
        self._wake.set()
        return self._held(self.clock(), wonder=True)

    def _nap(self, now: float) -> float:
        """Seconds the loop sleeps: until a walk may be due, or the reader's browser
        has been idle long enough to close, at most NAP_S and at least TICK_S.
        Asleep or out of walks for the day, NAP_S: a walk a little late is no matter."""
        times = [NAP_S]
        if self._wanted(now):
            times.append(0.0)
        elif not self._held(now):
            last = self.library.outing().last_end
            times.append(max(self.started + FIRST_WALK_S, last + self.settings.roam_gap_h * 3600,
                             self._not_before(now)) - now)
        if self.visitor.context is not None:
            times.append(self.visitor.used + IDLE_S - self.visitor.clock())
        return max(TICK_S, min(times))

    def _due(self, now: float) -> bool:
        if self._wanted(now):
            return True
        if self._held(now):
            return False
        last = self.library.outing().last_end
        return (now - self.started >= FIRST_WALK_S and now - last >= self.settings.roam_gap_h * 3600
                and now >= self._not_before(now))

    def next_walk(self, now: float) -> float | None:
        """When the next walk of its own may leave, for Settings › 外出; None while one cannot."""
        if self._held(now):
            return None
        last = self.library.outing().last_end
        return max(now, self.started + FIRST_WALK_S, last + self.settings.roam_gap_h * 3600, self._not_before(now))

    def _not_before(self, now: float) -> float:
        """With a set time (ROAM_AT) and no walk yet today, the day's first walk waits for it; else 0."""
        if not self.settings.roam_at or self._walks_today(now):
            return 0.0
        hour, minute = map(int, self.settings.roam_at.split(":"))
        return datetime.fromtimestamp(now).replace(hour=hour, minute=minute, second=0, microsecond=0).timestamp()

    def changed(self) -> None:
        """Settings › 外出 changed `settings`: the loop looks again at once."""
        self._wake.set()

    async def loop(self) -> None:
        code = self.available()
        if code:
            logger.info("roam: walks cannot leave (%s)", code)
            # No browser support or no model: each comes back only with a new install or a settings save,
            # which builds the character again.
            return
        try:
            while True:
                # Asleep, switched off, out of walks for the day or just back, a look at the next wake is
                # enough; words queued and a change in Settings › 外出 wake it at once.
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), self._nap(self.clock()))
                self._wake.clear()
                await self._hush()
                try:
                    await self.tick()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning("roam: a walk failed (%s)", type(exc).__name__)
        finally:
            await self.visitor.stop()

    async def tick(self, now: float | None = None) -> int:
        """One look at the clock: a walk when one is due. Returns what it kept, or -1 when it stayed in."""
        now = self.clock() if now is None else now
        await self.visitor.stop_if_idle()
        if not self._due(now):
            return -1
        return await self.walk(now)

    # -- the day's page counts, per site

    def _counts(self, now: float) -> dict:
        day = time.strftime("%Y-%m-%d", time.localtime(now))
        try:
            saved = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = {}
        if not isinstance(saved, dict) or saved.get("day") != day or not isinstance(saved.get("sites"), dict):
            saved = {"day": day, "sites": {}}
        return saved

    def _may_visit(self, site: str, now: float) -> bool:
        return int(self._counts(now)["sites"].get(site, 0)) < self.settings.roam_site_pages_a_day

    def _count_page(self, site: str, now: float) -> None:
        counts = self._counts(now)
        counts["sites"][site] = int(counts["sites"].get(site, 0)) + 1
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(self.state_path, json.dumps(counts, ensure_ascii=False))
        except OSError:
            pass

    # -- reading one page

    async def _read(self, url: str, *, background: bool = False, cover: str = "",
                    walls: list | None = None) -> _Read | None:
        """`url` read through web/read.py. A walk's read is a `background` visit (the host's card and
        robots.txt are asked first); `cover` is the list row's picture, for a page that declares none.
        The wall a page showed is added to `walls`."""
        url = str(url or "").strip()
        if len(url) > 4096 or urlsplit(url).scheme not in ("http", "https"):
            return None
        if not await self.public(url):
            logger.info("roam: %s is not a public address; not read", host_of(url) or "?")
            return None
        async with self.visitor.tab() as tab:
            page = await reading.read(tab, url, runtime=self.library.root.parent if background else None,
                                      background=background, item=True)
            final = page.url
            if not await self.public(final):
                return None
            facts = facts_from(page.data, final)
            wall = page.wall if page.wall not in ("", "sign_in_overlay", "empty") else wall_of(page.data, final, facts)
            if wall:
                logger.info("roam: %s shows a %s wall to visitors (%s); the page is left", host_of(final), wall,
                            page.evidence or "-")
                if walls is not None:
                    walls.append(wall)
                return None
            picture = await self._picture(tab, facts["picture"] or cover, final)
        if not facts["title"]:
            return None
        item = Item(url=final, site=facts["site"], kind=facts["kind"], title=facts["title"],
                    author=facts["author"], published=facts["published"], length=facts["length"],
                    description=facts["description"], text=facts["text"], embed=facts["embed"])
        item.id = item_id(item.url)
        return _Read(item, picture)

    async def _picture(self, tab: Any, address: str, referer: str) -> bytes:
        if not address or not self.host_check(host_of(address)):
            return b""
        try:
            # Opened in the same tab, so the browser's own network and the guards above apply; a cover
            # whose address expires is saved now.
            answer = await tab.goto(address, referer=referer, timeout_s=10)
            if (not 200 <= answer.status < 300 or not answer.kind.startswith("image/")
                    or answer.length > PICTURE_FETCH_MAX or answer.body is None):
                return b""
            body = await answer.body()
        except Exception:
            return b""
        return small_picture(body) if len(body) <= PICTURE_FETCH_MAX else b""

    # -- where to go

    def _topic(self) -> str:
        """Search words for one of the person's interests (`interests`): a topic they said they like, one
        they ticked on the first run or one of the profile's walk words, never a note and never what they
        said they do not want. The fewer fresh unseen things the library holds on an interest, the likelier
        the walk goes after it, so a starved interest gets fed first."""
        runtime = self.library.root.parent
        named = interests(runtime)
        # Not the last two walks' interests while another is left; a person who named few is still walked for.
        found = [t for t in named if t not in self._topics[-2:]] or named
        if not found:
            return ""
        held = supply(runtime, found, self.clock())
        topic = random.choices(found, [1 / (1 + held[t]) ** 2 for t in found])[0]
        self._topics = [*self._topics, topic][-5:]
        return random.choice(search_words(topic, self._ui_lang()))

    def _curiosity(self, theirs: bool = False) -> str:
        """A couple of tags of something the person opened or liked lately, else (unless `theirs`) of
        something the character itself loved lately, as search words; "" when none."""
        from .library import ENGAGED
        from .panels import feed
        events = feed.events(self.library.root.parent)
        taken = list(dict.fromkeys(e[1] for e in reversed(events) if e[2] in ENGAGED))[:40]
        items = {item.id: item for item in self.library.items() if item.tags}
        loved = [items[i] for i in taken if i in items][:20]
        if not loved and not theirs:
            loved = [item for item in items.values() if item.love >= CURIOUS_LOVE][:20]
        found = [words for words in dict.fromkeys(" ".join(item.tags[:2]) for item in loved)
                 if words not in self._topics]
        if not found:
            return ""
        words = random.choice(found[:10])
        self._topics = [*self._topics, words][-5:]
        return words

    def _plan(self) -> _Plan:
        """Where to go: queued words first (`today.wonder`: the person's lookup or a chat's), then now and then (THEIRS) the tags of
        what the person opened lately, then one of their interests (the most starved likeliest), then the
        character's own curiosity, each searched on the web and with two hosts' own search; with none, one
        or two hosts' hot lists, a host's search for a general word, and the web's."""
        from . import today
        lang = "zh" if str(getattr(self.agent, "agent_lang", "en")) == "zh" else "en"
        runtime = self.library.root.parent
        queued = today.take_wonder(runtime)
        wonder = queued.get("w", "")
        topic = (wonder or (random.random() < THEIRS and self._curiosity(theirs=True)) or self._topic()
                 or self._curiosity())
        searching = self._hosts("search")
        if topic:
            plan = _Plan([(WEB, "", "web", topic)]
                         + [(c["label"], c["key"], "search", topic) for c in searching[:2]], topic, wonder,
                         bool(queued.get("asked")))
        else:
            general = random.choice(_GENERAL[lang])
            hot = self._hosts("hot")[:random.randint(1, 2)]
            plan = _Plan([(c["label"], c["key"], "hot", "") for c in hot]
                         + [(c["label"], c["key"], "search", general) for c in searching
                            if c["key"] not in {h["key"] for h in hot}][:1]
                         + [(WEB, "", "web", general)])
        if wonder:
            # What they brought up is looked up first.
            plan.sources.sort(key=lambda s: s[0] != WEB)
        return plan

    def _hosts(self, intent: str) -> list[dict]:
        """The cards a walk may read `intent` from (web/sites.py), in a language the person reads, best first:
        where the person is, then what they do with each site's finds (the taste model's sampled coefficient,
        or the feed's points while the model is off), the platforms they chose, and a little chance."""
        from . import taste
        runtime = self.library.root.parent
        chosen = set(load_platforms(runtime))
        langs = situation.readable(runtime) | situation.expand({self._ui_lang()})
        found = [dict(c, label=c["name"] or site_name(c["home"]))
                 for c in sites.walk_hosts(runtime, intent, keys=self.hosts) if not c["lang"] or c["lang"] in langs]
        if taste.enabled(runtime):
            sampler = taste.Sampler(taste.load(runtime), taste.Priors(runtime), random.getrandbits(32))
            learned = {c["label"]: sampler.theta("origin:site:" + c["label"]) for c in found}
        else:
            learned = site_taste(runtime)
        found.sort(key=lambda c: -(situation.walk_prior(runtime, c["label"], c["region"])
                                   + learned.get(c["label"], 0.0) + FAVOUR * c["favour"]
                                   + CHOSEN * (c["key"] in chosen) + random.random()))
        return found

    def _ui_lang(self) -> str:
        return str(getattr(self.agent, "chat_lang", "") or getattr(self.agent, "agent_lang", "") or "en")

    async def _search(self, words: str) -> list[Found]:
        """The web search's results for `words` as pages to read; the visitor's guards apply as each is read."""
        found = []
        avoided = {key for key, how in sites.steered(self.library.root.parent).items() if how == "avoid"}
        for row in await self.agent._search_rows(words, max_results=WEB_RESULTS):
            url = row["url"]
            # A site's front page is a place to go, not a thing to read, and a broad word finds mostly those;
            # a site the person keeps walks off is left.
            if (urlsplit(url).scheme in ("http", "https") and row["title"] and urlsplit(url).path.strip("/")
                    and sites.key_of(url) not in avoided):
                found.append(Found(url, row["title"], site_name(url)))
        return found

    async def _list(self, key: str, intent: str, words: str) -> tuple[list[Found], str]:
        """A host's hot list or its search for `words` (web/sites.py), or the web search's ("web"), and the
        wall the list showed ("" for none)."""
        if intent == "web":
            return await self._search(words), ""
        runtime = self.library.root.parent
        async with self.visitor.tab() as tab:
            page = await sites.list_of(runtime, tab, sites.card(runtime, key)["home"], intent, words)
        # Chromium's own connection errors say the site cannot be reached from here.
        if page.wall == "error" and situation.navigation_failed(Exception(page.evidence)):
            situation.record(runtime, key, False)
            return [], "error"
        situation.record(runtime, key, True)
        situation.record_wall(runtime, key, page.wall in ("verification", "sign_in"))
        if page.wall not in ("", "sign_in_overlay"):
            logger.info("roam: the %s list of %s gave nothing (%s: %s)", intent, key, page.wall,
                        page.evidence or "-")
            return [], page.wall
        shape = sites.card(runtime, key)["shape"]
        return reading.found_rows(page, site_name,
                                  shape_ok=(lambda url: sites.matches(url, shape)) if shape else None), ""

    # -- the walk itself

    async def walk(self, now: float | None = None) -> int:
        """Go out, read a few pages, keep what is worth keeping. Returns how many were kept."""
        now = self.clock() if now is None else now
        self._walking = True
        outing = uuid.uuid4().hex[:12]
        plan = self._plan()
        self._wonder = plan.wonder
        trip = _Trip()
        # A web search is no place; the pages it leads to say where it is.
        self.library.left(plan.sources[0][0] if plan.sources and plan.sources[0][0] != WEB else "", now=now)
        try:
            lists = await self._ask_lists(plan, now, trip)
            await self._read_pages(lists, now, trip)
            await self._keep(trip, outing, plan.wonder, now)
            logger.info("roam: back from a walk, read %d pages, kept %d", len(trip.read), len(trip.kept))
        finally:
            self._walking = False
            self._back(trip, outing, plan, now)
        return len(trip.kept)

    async def _ask_lists(self, plan: _Plan, now: float, trip: _Trip) -> list[list[Found]]:
        """What each of the plan's lists found; a topic no list found anything for gets a host's hot list."""
        lists: list[list[Found]] = []
        for site, key, intent, words in plan.sources:
            if not self._may_visit(site, now):
                continue
            found, wall = await self._list(key, intent, words)
            self._count_page(site, now)
            if found and site != WEB:
                # Only a site that let it in counts as one it has been to.
                self.library.at(site)
            if not found:
                trip.missed.append((site, wall or "none"))
            trip.tried.append({"site": site, "intent": intent, "found": len(found),
                               "why": "" if found else wall or "none"})
            lists.append(found)
            await self._rest()
        hot = self._hosts("hot")[:1] if plan.topic and not any(lists) else []
        for card in hot:
            if self._may_visit(card["label"], now):
                found, wall = await self._list(card["key"], "hot", "")
                trip.tried.append({"site": card["label"], "intent": "hot", "found": len(found),
                                   "why": "" if found else wall or "none"})
                lists.append(found)
                self._count_page(card["label"], now)
        return lists

    async def _read_pages(self, lists: list[list[Found]], now: float, trip: _Trip) -> None:
        """A few of the lists' pages, one from each list in turn, into `trip.read`."""
        wanted = random.randint(3, max(3, self.settings.roam_pages))
        # A site whose pages it could not read twice in this walk is left for the rest of it.
        unread: dict[str, int] = {}
        for found in _interleave(lists):
            if len(trip.read) >= wanted:
                break
            if (self.library.seen(found.url) or unread.get(found.site, 0) >= UNREAD_MAX
                    or not self._may_visit(found.site, now)):
                continue
            self.library.at(found.site)
            self._count_page(found.site, now)
            walls: list[str] = []
            page = await self._read(found.url, background=True, cover=found.picture, walls=walls)
            if page is None:
                unread[found.site] = unread.get(found.site, 0) + 1
                why = walls[0] if walls else "unread"
                trip.missed.append((found.site, why))
                trip.skipped.append({"site": found.site, "title": found.title, "url": found.url, "why": why})
            elif all(r.item.id != page.item.id for r in trip.read):
                # Two rows can lead to one page (a redirect, a canonical address): it is kept once.
                trip.read.append(page)
                if found.site not in trip.places:
                    trip.places.append(found.site)
            await self._rest()

    async def _keep(self, trip: _Trip, outing: str, wonder: str, now: float) -> None:
        """The pages the model chose, with its judgement, into the library."""
        for choice in await self._choose(trip.read):
            chosen = trip.read[choice.index]
            chosen.item.outing, chosen.item.why, chosen.item.fits = outing, choice.why, choice.fits
            chosen.item.love, chosen.item.tags, chosen.item.judged = choice.love, list(choice.tags), choice.love >= 0
            chosen.item.seen_at = int(now)
            # Every list of a walk is for its one topic, so all it kept was looked for with those words.
            chosen.item.wonder = wonder
            if chosen.picture:
                chosen.item.picture = self.library.save_picture(chosen.item.id, chosen.picture)
            self.library.add(chosen.item)
            trip.kept.append(chosen.item.id)

    def _back(self, trip: _Trip, outing: str, plan: _Plan, now: float) -> None:
        """The walk over, kept or failed: the library, the walk record and a lookup's report are told."""
        runtime = self.library.root.parent
        self.library.returned(len(trip.kept), trip.places, now=self.clock())
        from .panels import walks as walk_log
        walk_log.record(runtime, {
            "id": outing, "at": int(now), "end": int(self.clock()), "topic": plan.topic, "asked": plan.asked,
            "lists": trip.tried, "skipped": trip.skipped,
            "read": [{"site": r.item.site, "title": r.item.title, "url": r.item.url, "kept": r.item.id in trip.kept}
                     for r in trip.read]})
        if plan.wonder:
            from . import today
            today.wondered(runtime, plan.wonder, trip.kept, self.clock(), asked=plan.asked,
                           read=len(trip.read), missed=trip.missed)

    async def _rest(self) -> None:
        await asyncio.sleep(random.uniform(*self.pause))
        await self._hush()

    async def _hush(self) -> None:
        """While quiet nothing walks: the browser closes, and opens again after."""
        if quiet.active():
            await self.visitor.stop()
            await quiet.wait()

    async def _choose(self, read: list[_Read]) -> list[Choice]:
        """Which pages to keep, and for each why, whether it fits the owner, how much the character
        loves it and its tags, asked of the model once."""
        if not read:
            return []
        try:
            system, user = self._prompt(read)
            with purpose("roam"):
                answer = await self.agent._call_llm(system, [{"role": "user", "content": user}], self.agent.model,
                                                    max_tokens=900, disable_thinking=True,
                                                    temperature=0.4, json_object=True)
            chosen = parse_choice(answer, len(read), KEEP_MAX)
        except Exception as exc:
            logger.warning("roam: the model did not choose (%s)", type(exc).__name__)
            chosen = None
        # No usable row (cheap models answer an empty list now and then): the walk still brings the first
        # pages home, which came from the walk's first list; the ranking sorts them out.
        if not chosen:
            return [Choice(n, "", n == 0) for n in range(min(KEEP_MAX, len(read)))]
        return chosen

    def _prompt(self, read: list[_Read]) -> tuple[str, str]:
        from .langs import NAMES
        lang = str(getattr(self.agent, "chat_lang", "") or getattr(self.agent, "agent_lang", "en"))
        name = str(getattr(self.agent, "persona_name", "") or "")
        persona = str(getattr(self.agent, "persona", "") or "")[:1500]
        system = (
            f"You are {name or 'the character described below'}.\n{persona}\n\n"
            "You have just been out on the web as a visitor and read the pages listed below. Choose the 1 to "
            f"{KEEP_MAX} most worth keeping, even when little is known about your owner yet. For each, write one "
            f"sentence in {NAMES.get(lang, lang)}, in your own voice, on why you stopped there, say whether it "
            "fits your owner, judged by what you know about them, how much you yourself love it (0-3), and 3-5 "
            "tags. " + WHY_RULE + " Answer with JSON only: " '{"items": [' + ROW_FORM + ']}.\n\n'
            + manner(self.library.root.parent) + _UNTRUSTED_INPUT_RULES)
        wonder = self._wonder
        user = (knowing(self.library.root.parent, self.clock())
                + ("\n\nYou went out to look this up because your owner brought it up in a chat: "
                   + _fence_user_data(wonder) if wonder else "")
                + "\n\nThe pages:\n" + page_rows([page.item for page in read], PROMPT_EXCERPT))
        return system, user


class Choice(NamedTuple):
    """The character's judgement of one page: `love` is -1 when it did not say."""
    index: int
    why: str
    fits: bool
    love: int = -1
    tags: tuple = ()


def asleep(now: float, offset_hours: float) -> bool:
    hour = datetime.fromtimestamp(now, timezone(timedelta(hours=offset_hours))).hour
    if SLEEP_HOUR_START <= SLEEP_HOUR_END:
        return SLEEP_HOUR_START <= hour < SLEEP_HOUR_END
    return hour >= SLEEP_HOUR_START or hour < SLEEP_HOUR_END


def knowing(runtime: Path, now: float) -> str:
    """The profile's text about the owner, what they told the character in the chat about their tastes (at
    once, before any rewrite), what it came to like from them, and their situation today."""
    known = profile.load(runtime)

    def block(title: str, text: str) -> str:
        return f"{title}:\n" + (_fence_user_data(text) if text.strip() else "(nothing yet)")

    return "\n\n".join([block("Your notes about your owner", known["owner"]),
                        block("What they told you in the chat about their tastes (this comes first)",
                              "\n".join(f"- {line}" for line in profile.told(runtime))),
                        block("Things your owner showed you that you came to like", known["character_learned"]),
                        "Their situation:\n" + (situation.notes(runtime, now) or "(unknown)")])


# ---------------------------------------------------------------- the person's interests and their supply

#: What counts as the library's supply of an interest: unseen things on it that came in this lately.
SUPPLY_DAYS = 2


def interests(runtime: Path) -> list[str]:
    """What the person is interested in, as they put it: the topics they ticked or typed on the first run,
    then those they said they like in the chat and the profile's walk words; none they said they do not want."""
    from .panels import feed
    ticked = feed.load_topics(runtime)
    return [t for t in dict.fromkeys(ticked + profile.walk_topics(runtime)) if not profile.unwanted(runtime, t)]


def supply(runtime: Path, topics: list[str], now: float, unread: frozenset = frozenset()) -> dict[str, int]:
    """For each topic, how many things on it came into the library in the last SUPPLY_DAYS and were not shown
    yet: what the ranking can still bring of it. Things from the sources in `unread` (in a language the
    person does not read) do not count."""
    from .panels import feed
    shown = feed._marks(feed.events(runtime))[0]
    matchers = {t: feed.topic_matcher([t]) for t in topics}
    held = dict.fromkeys(topics, 0)
    for item in Library(runtime).items():
        if item.seen_at < now - SUPPLY_DAYS * 86400:
            break
        if item.id in shown or item.source in unread:
            continue
        text = " ".join((item.title, item.description[:300], item.site)).casefold()
        for topic, matcher in matchers.items():
            if matcher and matcher.search(text):
                held[topic] += 1
    return held


def search_words(topic: str, lang: str) -> list[str]:
    """Words to search for a topic: an offered topic's own name and its words in the reader's script (so
    "科学" also goes out as 天文 or 航天, and each walk on it looks somewhere else); a typed one as itself."""
    from .panels import feed
    zh = str(lang).startswith("zh")
    for key, (names, words) in feed.SUGGESTED.items():
        if topic.casefold() in (key, *(n.casefold() for n in names)):
            # Latin words of three letters or less (ai, ui, nba) find too much elsewhere.
            return [names[zh]] + [w for w in words if (not w.isascii()) == zh and (zh or len(w) > 3)]
    return [topic]


def manner(runtime: Path) -> str:
    """How the person asked to be treated, as a paragraph of a system prompt; "" when they said nothing."""
    rule = profile.manner_rule(runtime)
    return rule + "\n\n" if rule else ""


def page_rows(items: list[Item], excerpt: int) -> str:
    """Things as a prompt's numbered list, each with `excerpt` characters of its words, fenced (`fence_pages`)."""
    rows = []
    for number, item in enumerate(items, 1):
        words = " ".join((item.description or item.text).split())[:excerpt]
        rows.append(f"{number}. [{item.kind}] {item.title}\nsite: {item.site}\nauthor: {item.author or '-'}\n{words}")
    return fence_pages("\n\n".join(rows))


def fence_pages(text: str) -> str:
    """Pages' words as external material their content cannot close."""
    cleaned = html.escape(_clean_prompt_source(text), quote=False)
    return f"{_WEB_DESC_OPEN}[external_web_pages]\n{cleaned}\n[/external_web_pages]{_WEB_DESC_CLOSE}"


def _whole(value: Any) -> int | None:
    """A whole number as models write one: 2, 2.0 or "2"; None for anything else (a bool included)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and re.fullmatch(r"\s*-?\d+\s*", value):
        return int(value)
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value if isinstance(value, int) else None


def parse_choice(answer: Any, count: int, limit: int = KEEP_MAX) -> list[Choice] | None:
    """The valid rows of the model's answer, at most `limit`, each page once; a row that is not
    in the asked form is left out. None when the answer is not the asked JSON at all."""
    value = salvage_json_object(strip_json_fences(str(answer or "")))
    rows = (value.get("items", value.get("keep")) if isinstance(value, dict) else None)
    if not isinstance(rows, list):
        return None
    chosen, seen = [], set()
    for row in rows:
        if not isinstance(row, dict) or len(chosen) >= limit:
            continue
        number, why, fits, love = _whole(row.get("n")), row.get("why"), row.get("fits"), _whole(row.get("love", -1))
        if (number is None or not 1 <= number <= count or number in seen or not isinstance(why, str)
                or not isinstance(fits, bool) or love not in (-1, 0, 1, 2, 3)):
            continue
        why = " ".join(why.split())
        if not why:
            continue
        # A long sentence is cut, not thrown away with the page.
        why = why[:WHY_MAX]
        tags = row.get("tags") if isinstance(row.get("tags"), list) else []
        tags = list(dict.fromkeys(t for t in (" ".join(str(x).split()).lower()[:TAG_LEN] for x in tags
                                               if isinstance(x, str)) if t))[:TAGS_MAX]
        seen.add(number)
        chosen.append(Choice(number - 1, why, fits, int(love), tuple(tags)))
    return chosen



def _interleave(lists: list[list[Found]]) -> list[Found]:
    """One from each list in turn, each address once."""
    out, seen = [], set()
    for row in range(max((len(x) for x in lists), default=0)):
        for found in lists:
            if row < len(found) and found[row].url not in seen:
                seen.add(found[row].url)
                out.append(found[row])
    return out
