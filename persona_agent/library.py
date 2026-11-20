"""What the character has seen on its walks, kept on this computer.

One line per thing in `<runtime>/library/items.jsonl`, its cover (made small)
in `pictures/`, and `outing.json` saying whether it is out now. The walk
writes here; the home page and the days read from here.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from .storage import append_jsonl, atomic_write_text

KINDS = ("video", "article", "post", "page")
# The walks and the sources add from their own threads; a compact
# between another's read and its append would lose that append.
_write = threading.Lock()
# What became of an item: the owner's doing, never the character's.
NEW, KEPT, DISMISSED = "", "kept", "dismissed"
CHAT = "chat"
# Read by the person themselves in the app's own browser (browsed.py), not by the character.
BROWSED = "browsed"
TEXT_MAX = 20_000
EXCERPT_MAX = 400
PICTURE_MAX_BYTES = 200_000
ITEMS_MAX = 2000
# A thing the person opened, liked, played or read this recently is kept past the limit while older ones can go.
REACTED_DAYS = 45
# A walk's or a source's find nobody kept or opened retires this long after it came: the feed would not bring it now.
STALE_DAYS = 30
# What the feed counts as the person taking a thing up; a showing or a skip is not.
ENGAGED = ("open", "like", "play", "read")


@dataclass
class Item:
    """One thing read or watched. `embed` is the site's own player address,
    set only when the page offered one and its host is allowed; `why` is the
    character's sentence; `fits` says it kept this for its owner."""
    url: str
    site: str = ""
    kind: str = "page"
    title: str = ""
    author: str = ""
    published: str = ""
    length: Optional[int] = None        # seconds, for a video
    description: str = ""
    text: str = ""
    embed: str = ""
    picture: str = ""                   # file name under pictures/, or ""
    seen_at: int = 0
    outing: str = ""
    why: str = ""
    fits: bool = False
    told: bool = False
    state: str = NEW
    id: str = ""
    source: str = ""                    # the public source that brought it, "" for a walk's find
    # The character's own judgement: love 0-3 (-1 before it was asked), a few short English tags,
    # and whether it was asked at all, so "not asked" and "asked, said no" differ.
    love: int = -1
    tags: list = field(default_factory=list)
    judged: bool = False
    # CHAT when the character read it during a chat, BROWSED when the person read it in the app's browser;
    # "" for a walk's find or a source's.
    via: str = ""
    # The words from a chat that sent a walk looking for it, "" when it went on its own.
    wonder: str = ""

    def card(self) -> dict:
        """What the page draws: public facts, no file paths."""
        excerpt = " ".join((self.description or self.text).split())[:EXCERPT_MAX]
        return {"kind": self.kind, "title": self.title, "site": self.site, "author": self.author,
                "length": self.length, "picture": f"/api/library/picture/{self.id}" if self.picture else "",
                "embed": self.embed, "url": self.url, "excerpt": excerpt, "readable": bool(self.text.strip())}


def item_id(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


@dataclass
class Outing:
    """Whether the character is out, and how its last walk ended."""
    state: str = "home"                 # home | out
    site: str = ""
    since: int = 0
    last_end: int = 0
    last_count: int = 0
    day: str = ""
    today: int = 0                      # walks started today
    sites: list = field(default_factory=list)   # every site ever visited, by name


class Library:
    def __init__(self, runtime: Path):
        self.root = Path(runtime) / "library"
        self.items_path = self.root / "items.jsonl"
        self.pictures = self.root / "pictures"
        self.outing_path = self.root / "outing.json"

    # -- items

    def _rows(self) -> dict[str, Item]:
        """Every item by id; a later line for the same id replaces the earlier one."""
        found: dict[str, Item] = {}
        try:
            lines = self.items_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return found
        known = set(Item.__dataclass_fields__)
        for line in lines:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get("id") and row.get("url"):
                found[str(row["id"])] = Item(**{k: v for k, v in row.items() if k in known})
        return found

    def add(self, item: Item) -> Item:
        """Keep `item`; one already there for the same address is replaced, with the owner's choice kept."""
        item.id = item.id or item_id(item.url)
        item.kind = item.kind if item.kind in KINDS else "page"
        item.text = item.text[:TEXT_MAX]
        item.seen_at = item.seen_at or int(time.time())
        with _write:
            before = self._rows().get(item.id)
            if before is not None:
                item.state, item.told = before.state, before.told or item.told
                if not item.judged:
                    item.judged, item.love, item.tags = before.judged, before.love, before.tags
            self.root.mkdir(parents=True, exist_ok=True)
            append_jsonl(self.items_path, asdict(item))
        return item

    def get(self, ident: str) -> Optional[Item]:
        return self._rows().get(str(ident))

    def items(self, *, newest_first: bool = True) -> list[Item]:
        rows = sorted(self._rows().values(), key=lambda item: (item.seen_at, item.id), reverse=newest_first)
        return rows

    def change(self, ident: str, **values) -> Optional[Item]:
        # Read and written as one step, so two changes to one thing at once both stay.
        with _write:
            item = self.get(ident)
            if item is None:
                return None
            for name, value in values.items():
                if name in ("state", "told", "why", "fits", "love", "tags", "judged", "picture"):
                    setattr(item, name, value)
            append_jsonl(self.items_path, asdict(item))
        return item

    def seen(self, url: str) -> bool:
        return item_id(url) in self._rows()

    def compact(self) -> None:
        """One line per item again, without the stale (a walk's or a source's find older than STALE_DAYS that
        nobody kept or took up). Past the limit the dismissed go first, then the oldest shown and never taken
        up, then the oldest not taken up in REACTED_DAYS, then the oldest of the rest; a kept one never goes."""
        with _write:
            self._compact()

    def drop(self, gone) -> list[str]:
        """Every item `gone(item)` is true of out of the file at once; their ids."""
        with _write:
            rows = self.items(newest_first=False)
            dropped = [r.id for r in rows if gone(r)]
            if dropped:
                atomic_write_text(self.items_path, "".join(json.dumps(asdict(r), ensure_ascii=False) + "\n"
                                                           for r in rows if r.id not in dropped))
            return dropped

    def _reacted(self) -> tuple[set[str], set[str]]:
        """The ids the person took up (ENGAGED) in REACTED_DAYS, and every id shown to them."""
        # The feed's events (see panels.feed), read here so the feed's model can still rebuild them.
        try:
            events = json.loads((self.root.parent / "feed.json").read_text(encoding="utf-8")).get("events")
        except (OSError, ValueError, AttributeError):
            return set(), set()
        if not isinstance(events, list):
            return set(), set()
        since = time.time() - REACTED_DAYS * 86400
        rows = [e for e in events if isinstance(e, list) and len(e) >= 5]
        return {e[1] for e in rows if e[0] >= since and e[2] in ENGAGED}, {e[1] for e in rows}

    def _compact(self) -> None:
        rows = self.items(newest_first=False)
        taken, shown = self._reacted()
        old = time.time() - STALE_DAYS * 86400
        # The person's own reading has its own keeping (browsed.py).
        stale = {r.id for r in rows if r.seen_at < old and r.state != KEPT and r.id not in taken
                 and not r.via}
        gone = [r for r in rows if r.id in stale]
        rows = [r for r in rows if r.id not in stale]
        while len(rows) > ITEMS_MAX:
            drop = (next((r for r in rows if r.state == DISMISSED), None)
                    or next((r for r in rows if r.state != KEPT and r.id in shown and r.id not in taken), None)
                    or next((r for r in rows if r.state != KEPT and r.id not in taken), None)
                    or next((r for r in rows if r.state != KEPT), None))
            if drop is None:
                break
            rows.remove(drop)
            gone.append(drop)
        for drop in gone:
            if drop.picture:
                (self.pictures / drop.picture).unlink(missing_ok=True)
        if rows or gone:
            self.root.mkdir(parents=True, exist_ok=True)
            atomic_write_text(self.items_path, "".join(json.dumps(asdict(r), ensure_ascii=False) + "\n" for r in rows))

    # -- pictures

    def save_picture(self, ident: str, data: bytes, suffix: str = ".jpg") -> str:
        """Keep a cover that is already small; "" when it is too large or empty."""
        if not data or len(data) > PICTURE_MAX_BYTES or suffix not in (".jpg", ".png", ".webp"):
            return ""
        self.pictures.mkdir(parents=True, exist_ok=True)
        name = f"{ident}{suffix}"
        (self.pictures / name).write_bytes(data)
        return name

    def picture_path(self, ident: str) -> Optional[Path]:
        item = self.get(ident)
        if item is None or not item.picture:
            return None
        path = (self.pictures / item.picture).resolve()
        return path if path.is_file() and path.parent == self.pictures.resolve() else None

    # -- the walk

    def outing(self) -> Outing:
        try:
            saved = json.loads(self.outing_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return Outing()
        known = set(Outing.__dataclass_fields__)
        return Outing(**{k: v for k, v in saved.items() if k in known}) if isinstance(saved, dict) else Outing()

    def _save_outing(self, outing: Outing) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self.outing_path, json.dumps(asdict(outing), ensure_ascii=False))

    def left(self, site: str = "", now: Optional[float] = None) -> Outing:
        now = int(time.time() if now is None else now)
        outing = self.outing()
        day = time.strftime("%Y-%m-%d", time.localtime(now))
        if outing.day != day:
            outing.day, outing.today = day, 0
        outing.state, outing.site, outing.since, outing.today = "out", site, now, outing.today + 1
        self._save_outing(outing)
        return outing

    def at(self, site: str) -> None:
        outing = self.outing()
        if outing.state == "out":
            outing.site = site
            if site and site not in outing.sites:
                outing.sites.append(site)
            self._save_outing(outing)

    def returned(self, count: int, sites: Iterable[str] = (), now: Optional[float] = None) -> Outing:
        outing = self.outing()
        outing.state, outing.site = "home", ""
        outing.last_end, outing.last_count = int(time.time() if now is None else now), int(count)
        for site in sites:
            if site and site not in outing.sites:
                outing.sites.append(site)
        self._save_outing(outing)
        return outing
