"""Every source, and the rounds that read them into the library.

The catalogue is the area modules' `SOURCES` and one source per feed the
person added themselves (kept in `<runtime>/sources.json` with how each
source's last read went). Nobody chooses public sources: each round reads
every own feed and `weights.ROUND` public sources drawn by what was learned
(see `weights`), keeps what the library has not seen, each thing marked
with the source that brought it, and the feed ranks it by the person's taste.

Each round first infers the person's situation again (`situation.infer`) and
reads through a transport that records which hosts answer, so a source that
cannot be reached from where the person is stops taking a place in the round.
"""
from __future__ import annotations

import asyncio
import contextlib
import importlib
import json
import logging
import random
import threading
import time
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urljoin

import httpx

from .. import langs, quiet, roam, situation
from ..library import Library, item_id
from ..panels import feed as feed_panel
from ..roam import public_address, small_picture
from ..storage import atomic_write_text
from . import base, weights
from .base import Find, Source

logger = logging.getLogger("agent.sources")

# The modules that list sources.
AREAS = ("tech", "china", "world", "culture", "regional")
CHOICE_FILE = "sources.json"
# Sources fetched at the same time in one round.
AT_ONCE = 6
# A round soon after the app starts, then this often.
FIRST_ROUND_S = 20
ROUND_EVERY_S = 30 * 60
# Covers are read only this far; a larger one is left out rather than half read.
COVER_READ_MAX = 500_000
COVER_HOPS = 4
ERROR_MAX = 160

# sources.json is written from the page's worker threads and from the rounds.
_lock = threading.Lock()
_broken: set[str] = set()


# ----------------------------------------------------------------- the catalogue --

def _module(name: str):
    """One sibling module, or None: one that is missing or broken never takes the others down."""
    try:
        return importlib.import_module(f"{__package__}.{name}")
    except Exception as exc:
        # The catalogue is read on every view: one line per module, not per view.
        if name not in _broken:
            _broken.add(name)
            logger.warning("sources: %s could not be loaded (%s: %s); the others go on",
                           name, type(exc).__name__, exc)
        return None


def custom():
    return _module("custom")


def all_sources(own_entries: list[dict]) -> dict[str, Source]:
    """Every source by key: the area modules' first, then one per saved own entry."""
    found: dict[str, Source] = {}
    for name in AREAS:
        module = _module(name)
        for source in getattr(module, "SOURCES", ()):
            found.setdefault(source.key, source)
    own = custom() if own_entries else None
    if own is not None:
        try:
            for entry in own_entries:
                source = own.source_for(entry)
                found[source.key] = source
        except Exception as exc:
            logger.warning("sources: the person's own feeds could not be listed (%s: %s)", type(exc).__name__, exc)
    return found


def reader(lang: str) -> str:
    """Which defaults a reader of `lang` gets: "zh" for Chinese, else "en"."""
    return "zh" if langs.content(langs.normalize(lang) or "en") == "zh" else "en"


# ----------------------------------------------------------- what is kept on disk --

def choice_path(runtime: Path) -> Path:
    return Path(runtime) / CHOICE_FILE


def load_choice(runtime: Path) -> dict:
    """The person's own feeds, and how each source's last read went."""
    try:
        saved = json.loads(choice_path(runtime).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    saved = saved if isinstance(saved, dict) else {}
    own = saved.get("own") if isinstance(saved.get("own"), list) else []
    last = saved.get("last") if isinstance(saved.get("last"), dict) else {}
    return {"own": [e for e in own if isinstance(e, dict) and e.get("key") and e.get("url")],
            "last": {k: v for k, v in last.items() if isinstance(v, dict)}}


def save_choice(runtime: Path, choice: dict) -> None:
    atomic_write_text(choice_path(runtime), json.dumps(choice, ensure_ascii=False, indent=1))


def change_choice(runtime: Path, change: Callable[[dict], None]) -> dict:
    """Read, change and write the file as one step; what was written."""
    with _lock:
        choice = load_choice(runtime)
        change(choice)
        save_choice(runtime, choice)
        return choice


def weighed(runtime: Path, lang: str, sources: dict[str, Source], rng: Optional[random.Random] = None) -> list[dict]:
    """Every public source with its weight for this person, highest first (see `weights.weigh`):
    the languages they read (the character's always among them), the situation's supply term, and the
    taste model's sampled coefficient for each source while the model is on."""
    from .. import taste
    runtime = Path(runtime)
    matcher = feed_panel.topic_matcher(feed_panel.load_topics(runtime / feed_panel.TASTE_FILE))
    public = [s for s in sources.values() if s.group != "own"]
    origin = None
    if taste.enabled(runtime):
        sampler = taste.Sampler(taste.load(runtime), taste.Priors(runtime), (rng or random.Random()).getrandbits(32))
        origin = lambda key: sampler.theta("origin:src:" + key)  # noqa: E731
    return weights.weigh(public, weights.load(runtime), situation.readable(runtime) | situation.expand({lang}), matcher,
                         unreadable=situation.unreadable(runtime), defaults=situation.default_langs(runtime, lang),
                         supply=situation.supplier(runtime), origin=origin,
                         retry_s=situation.retry_s(runtime), retry_at=situation.retry_at(runtime))


# --------------------------------------------------------------------- one round --

def short(exc: BaseException) -> str:
    if isinstance(exc, asyncio.TimeoutError | httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.HTTPStatusError):
        return f"http {exc.response.status_code}"
    words = " ".join(str(exc).split())
    return f"{type(exc).__name__}: {words}"[:ERROR_MAX] if words else type(exc).__name__


async def _fetch(http: httpx.AsyncClient, source: Source, gate: asyncio.Semaphore) -> tuple[list[Find], str, str]:
    """What a source brought, its error, and how the read went for `weights.read`: blocked when the
    transport could not reach it (its error, or every request it made failed so), else failed or ok."""
    async with gate:
        counts = situation.tally()
        try:
            finds = await asyncio.wait_for(source.fetch(http), base.TIMEOUT_S)
        except Exception as exc:
            logger.info("sources: %s did not answer (%s)", source.key, short(exc))
            blocked = isinstance(exc, situation.COUNTED) or (counts["fail"] and not counts["ok"])
            return [], short(exc), weights.BLOCKED if blocked else weights.FAILED_READ
    finds = list(finds)[:base.PER_SOURCE]
    # A source that reads several feeds and keeps what answered says nothing when none did.
    return finds, "", weights.BLOCKED if not finds and counts["fail"] and not counts["ok"] else weights.OK


async def _cover(http: httpx.AsyncClient, address: str, referer: str) -> bytes:
    """The cover made small, or b"": only https to public addresses, every redirect checked again."""
    for _ in range(COVER_HOPS):
        if not address.startswith("https://") or not await public_address(address):
            return b""
        async with http.stream("GET", address, headers={"Referer": referer}, follow_redirects=False) as answer:
            if answer.is_redirect:
                address = urljoin(address, answer.headers.get("location", ""))
                continue
            if answer.status_code != 200 or int(answer.headers.get("content-length") or 0) > COVER_READ_MAX:
                return b""
            data = bytearray()
            async for chunk in answer.aiter_bytes():
                data.extend(chunk)
                if len(data) > COVER_READ_MAX:
                    return b""
        return await asyncio.to_thread(small_picture, bytes(data))
    return b""


async def _covered(http: httpx.AsyncClient, found: Find, gate: asyncio.Semaphore) -> bytes:
    if not found.picture:
        return b""
    async with gate:
        try:
            return await asyncio.wait_for(_cover(http, found.picture, found.item.url), base.TIMEOUT_S)
        except Exception:
            # A cover is a nicety: whatever the network did, the find is kept without one.
            return b""


def _keep(library: Library, new: list[tuple[Find, bytes]]) -> None:
    for found, cover in new:
        item = found.item
        item.id = item_id(item.url)
        # What a source brings was not chosen by the character: the feed ranks it by taste.
        item.fits, item.why = False, ""
        if cover:
            item.picture = library.save_picture(item.id, cover)
        library.add(item)
    library.compact()


def plan(runtime: Path, lang: str, rng: random.Random) -> list[Source]:
    """This round's sources: every own feed, and the public ones `weights.pick` draws."""
    sources = all_sources(load_choice(runtime)["own"])
    own = [s for s in sources.values() if s.group == "own"]
    return own + [row["source"] for row in weights.pick(weighed(runtime, lang, sources, rng), rng)]


async def run_round(runtime: Path, lang: str) -> tuple[int, list[str]]:
    """Read this round's sources and keep what is new; how many new things were kept, and which sources were read."""
    runtime = Path(runtime)
    await situation.retry_down(runtime)
    await asyncio.to_thread(situation.infer, runtime, lang)
    before = await asyncio.to_thread(load_choice, runtime)
    picked = await asyncio.to_thread(plan, runtime, lang, random.Random())
    library = Library(runtime)
    known = {item.id for item in await asyncio.to_thread(library.items)}
    gate = asyncio.Semaphore(AT_ONCE)
    async with base.client(**situation.client_options(runtime)) as http:
        answers = await asyncio.gather(*(_fetch(http, s, gate) for s in picked))
        new: list[Find] = []
        for source, (finds, _, _) in zip(picked, answers):
            for found in finds:
                ident = item_id(found.item.url)
                if ident not in known:
                    known.add(ident)
                    found.item.source = source.key
                    new.append(found)
        covers = await asyncio.gather(*(_covered(http, f, gate) for f in new))
    if new:
        await asyncio.to_thread(_keep, library, list(zip(new, covers)))
    now = int(time.time())

    def record(saved: dict) -> None:
        # A feed of their own the person removed while the round ran leaves no trace.
        removed = {e["key"] for e in before["own"]} - {e["key"] for e in saved["own"]}
        for source, (finds, error, _) in zip(picked, answers):
            if source.key not in removed:
                saved["last"][source.key] = {"at": now, "count": len(finds), "error": error}

    await asyncio.to_thread(change_choice, runtime, record)
    await asyncio.to_thread(weights.read, runtime, {s.key: outcome for s, (_, _, outcome) in zip(picked, answers)
                                                    if s.group != "own"}, now)
    logger.info("sources: a round of %d sources kept %d new things", len(picked), len(new))
    return len(new), [s.key for s in picked]


# ---------------------------------------------------------------------- the loop --

class Rounds:
    """A round soon after start, then every ROUND_EVERY_S, and at once when asked.
    `runtime` and `lang` are read again for each round, so a changed setting counts. `home` is the folder
    whose .env names the character's model, the runtime's parent unless given."""

    def __init__(self, runtime: Callable[[], Path], lang: Callable[[], str],
                 home: Optional[Callable[[], Path]] = None):
        self.runtime, self.lang = runtime, lang
        self.home = home or (lambda: self.runtime().parent)
        self.running = False
        self._wake = asyncio.Event()
        self.last_count: Optional[int] = None
        self.last_picked: list[str] = []
        # Called after a round that kept something new (the page shares it and tells the pet).
        self.found: Callable[[], None] = lambda: None

    def ask(self, *, even_if_running: bool = False) -> None:
        """A round now; while one runs, another right after it only when `even_if_running`."""
        if even_if_running or not self.running:
            self._wake.set()

    @property
    def busy(self) -> bool:
        """A round is running or about to: what the page shows as reading."""
        return self.running or self._wake.is_set()

    async def _wait(self, seconds: float) -> None:
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._wake.wait(), seconds)
        self._wake.clear()

    async def check_again(self) -> dict:
        """The person's "check again now": the down hosts tried at once, then a round that retries
        every blocked source. What the situation then is (`situation.view`)."""
        shown = await situation.check_again(self.runtime(), self.lang())
        self.ask(even_if_running=True)
        return shown

    async def _judge(self) -> None:
        try:
            await roam.judge(self.runtime(), self.home())
        except Exception:
            # The person's model may be down or slow; what was kept waits for the next round's judgement.
            logger.exception("sources: the character's judgement failed")

    async def loop(self) -> None:
        # The first start checks a few hosts, so the gate and the region exist before the first round.
        first = asyncio.create_task(situation.probe(self.runtime(), self.lang()))
        try:
            await self._wait(FIRST_ROUND_S)
            while True:
                await quiet.wait()
                self.running = True
                try:
                    self.last_count, self.last_picked = await run_round(self.runtime(), self.lang())
                except Exception:
                    logger.exception("sources: a round failed")
                finally:
                    self.running = False
                # What the round kept is judged by the character after it, when enough waits.
                await self._judge()
                if self.last_count:
                    self.found()
                await self._wait(ROUND_EVERY_S)
        finally:
            first.cancel()
