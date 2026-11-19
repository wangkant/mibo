"""The sources panel: the rounds that read public places for the person, and
the feeds they added themselves.

Nobody picks public sources; each round draws them by what was learned (see
`sources.weights`). `GET /api/sources` shows each one's weight, for looking
into that, not for a page to list. The rounds run in the page server (see
`sources.catalog.Rounds`), so the library fills with no model and no
character service. The lifespan starts `app.state.sources.loop()` and
cancels it with its other tasks.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path

from fastapi import Request

from .. import langs
from ..library import item_id
from ..roam import public_address, site_name
from ..sources import base, catalog

logger = logging.getLogger("agent.sources")

ADDRESS_MAX = 2048
TITLE_MAX = 200
# An OPML file is larger than the page's usual request.
OPML_MAX = 2_000_000

ERRORS: frozenset[str] = frozenset({"source_unknown", "source_invalid", "source_not_found",
                                    "source_unavailable", "opml_invalid"})


def _when(at) -> str:
    return datetime.fromtimestamp(at).astimezone().isoformat(timespec="seconds") if isinstance(at, int) and at else ""


def _text(value, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


class Sources:
    def __init__(self, workspace):
        self.ws = workspace
        # The language the page last named, for a home whose character has none set.
        self.page_lang = ""
        self.rounds = catalog.Rounds(self.runtime, self.lang, home=lambda: self.ws.home)

    def runtime(self) -> Path:
        return self.ws._runtime()

    def lang(self) -> str:
        return langs.normalize(self.ws.config().get("AGENT_LANG")) or self.page_lang or "en"

    def heard(self, lang) -> None:
        self.page_lang = langs.normalize(lang) or self.page_lang

    # -- what the rounds weigh

    def view(self) -> dict:
        lang = self.lang()
        zh = 1 if lang in ("zh", "zh-TW") else 0
        runtime = self.runtime()
        choice = catalog.load_choice(runtime)
        sources = catalog.all_sources(choice["own"])

        def last(key: str) -> dict:
            was = choice["last"].get(key, {})
            return {"at": _when(was.get("at")), "count": int(was.get("count") or 0), "error": str(was.get("error") or "")}

        public = [{"key": row["source"].key, "name": row["source"].name[zh], "group": row["source"].group,
                   "lang": row["source"].lang, "default": row["source"].default,
                   **{f: row[f] for f in ("weight", "prior", "learned", "reads", "items", "points", "hides", "fails")},
                   **last(row["source"].key)}
                  for row in catalog.weighed(runtime, lang, sources)]
        own = [{"key": e["key"], "title": str(e.get("title") or ""), "site": str(e.get("site") or ""),
                "url": e["url"], **(last(e["key"]) if e["key"] in sources
                                    else {"at": "", "count": 0, "error": "source_unavailable"})}
               for e in choice["own"]]
        return {"running": self.rounds.busy, "reader": catalog.reader(lang), "last_round": self.rounds.last_picked,
                "sources": public, "own": own}

    # -- feeds of the person's own

    def remove(self, payload: dict) -> dict:
        key = payload.get("key")
        runtime = self.runtime()
        if key not in {e["key"] for e in catalog.load_choice(runtime)["own"]}:
            raise ValueError("source_unknown")

        def drop(choice: dict) -> None:
            choice["own"] = [e for e in choice["own"] if e["key"] != key]
            choice["last"].pop(key, None)

        catalog.change_choice(runtime, drop)
        return self.view()

    @staticmethod
    def _entry(raw) -> dict | None:
        """A feed as it is saved, or None when its address is not one to read."""
        if not isinstance(raw, dict):
            return None
        url = str(raw.get("url") or "").strip()
        if len(url) > ADDRESS_MAX or not url.startswith(("https://", "http://")):
            return None
        site = _text(raw.get("site"), TITLE_MAX) or site_name(url)
        # The feed's name is what the page and the source show; the site stands in for a missing one.
        return {"key": "own-" + item_id(url)[:12], "url": url,
                "title": _text(raw.get("title"), TITLE_MAX) or site, "site": site}

    async def _public(self, entries: list[dict]) -> list[dict]:
        # A feed is read by this computer every round: only one on the public web.
        checks = await asyncio.gather(*(public_address(e["url"]) for e in entries))
        return [e for e, ok in zip(entries, checks) if ok]

    def _add(self, entries: list[dict]) -> int:
        added = 0

        def put(choice: dict) -> None:
            nonlocal added
            saved = {e["key"] for e in choice["own"]}
            for entry in entries:
                if entry["key"] not in saved:
                    choice["own"].append(entry)
                    saved.add(entry["key"])
                    added += 1

        catalog.change_choice(self.runtime(), put)
        return added

    async def find(self, payload: dict) -> dict:
        address = str(payload.get("address") or "").strip()
        if not address or len(address) > ADDRESS_MAX:
            raise ValueError("source_invalid")
        own = catalog.custom()
        if own is None:
            raise ValueError("source_unavailable")
        try:
            async with base.client() as http:
                feeds = await asyncio.wait_for(own.discover(http, address), base.TIMEOUT_S * 2)
        except Exception as exc:
            # A site that will not answer, or answers with no feed, is nothing found.
            logger.info("sources: nothing found at the address given (%s)", catalog.short(exc))
            feeds = []
        feeds = [{"url": f["url"], "title": str(f.get("title") or ""), "site": str(f.get("site") or "")}
                 for f in feeds or [] if isinstance(f, dict) and f.get("url")]
        if not feeds:
            raise ValueError("source_not_found")
        return {"feeds": feeds}

    async def add(self, payload: dict) -> dict:
        entry = self._entry(payload)
        if entry is None or not await self._public([entry]):
            raise ValueError("source_invalid")
        if await asyncio.to_thread(self._add, [entry]):
            # A feed just added is read now, not half an hour from now.
            self.rounds.ask(even_if_running=True)
        return await asyncio.to_thread(self.view)

    async def opml(self, payload: dict) -> dict:
        own = catalog.custom()
        if own is None:
            raise ValueError("source_unavailable")
        try:
            found = own.parse_opml(str(payload.get("text") or ""))
        except Exception:
            raise ValueError("opml_invalid") from None
        entries = {e["key"]: e for e in map(self._entry, found) if e is not None}
        added = await asyncio.to_thread(self._add, await self._public(list(entries.values())))
        if added:
            self.rounds.ask(even_if_running=True)
        return {"added": added, **await asyncio.to_thread(self.view)}


def mount(app, workspace, body) -> None:
    panel = Sources(workspace)
    app.state.sources = panel.rounds
    panel.rounds.found = lambda: workspace.found()

    async def read(request: Request, limit: int | None = None) -> dict:
        payload = await (body(request, limit) if limit else body(request))
        panel.heard(payload.get("lang"))
        return payload

    @app.get("/api/sources")
    async def sources_view(lang: str = ""):
        panel.heard(lang)
        return await asyncio.to_thread(panel.view)

    @app.post("/api/sources/find")
    async def sources_find(request: Request):
        return await panel.find(await read(request))

    @app.post("/api/sources/add")
    async def sources_add(request: Request):
        return await panel.add(await read(request))

    @app.post("/api/sources/remove")
    async def sources_remove(request: Request):
        return await asyncio.to_thread(panel.remove, await read(request))

    @app.post("/api/sources/opml")
    async def sources_opml(request: Request):
        return await panel.opml(await read(request, OPML_MAX))

    @app.post("/api/sources/refresh")
    async def sources_refresh(request: Request):
        await read(request)
        panel.rounds.ask()
        return {"ok": True}
