"""The app's own settings and abilities, as the character knows them, and the deferred tool `settings` by which it
looks one up, opens Settings at it for the person, or changes one they asked to change.

The catalogue follows the Settings pages (static/welcome/setup/*.js): every item a page marks, with switchRow's id or
kit.item, is an Item here under the same page and key, named by the page's own words (its locale key), and
tests/parts/catalogs/test_app_map.py fails when a page gains an item this lacks or this names one no page has.
Settings opened at "setup/<page>/<key>" brings that item into view (setup.js).

Everything runs in the page's process (/api/settings): a value is read, and a change is made, through the same
routes the page itself calls, so there is one way to each setting. A change the character may make goes ahead when
the person asks for it; one that widens its permissions (acting on this computer, reading what is in front, going
out on its own...) first passes crossing.widening, which asks in the chat with the risk "widen" after outside
material, or when the person's own words do not name it. A key or a token is never read: an item says only whether
one is set.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("agent.tools")

NAME = "settings"
TOOL = {"type": "function", "function": {
    "name": NAME,
    "description": (
        "The app's own settings and what it can do, page by page: list them with their values, open Settings at "
        "one for them to see, or change one they asked to change."),
    "parameters": {"type": "object", "properties": {
        "do": {"type": "string", "enum": ["list", "open", "change"]},
        "item": {"type": "string", "description": "page/item as list gives it (device/pet-shown), or a page"},
        "value": {"type": "string", "description": "change: on, off, one of the values list names, or the value"}},
        "required": ["do"]}}}

# The pages of Settings, in the sidebar's order (setup.js ORDER).
PAGES = ("character", "model", "connect", "language", "recs", "walks", "memory", "privacy", "shell", "programs",
         "abilities", "schedule", "device", "about")
# The languages a person may read, as Settings › Language offers them (setup/language.js AUTONYMS).
READABLE = ("zh", "en", "ja", "ko", "ru", "pt", "es", "fr", "de")
COLOUR = re.compile(r"#[0-9a-fA-F]{6}")
# A value the page could not read (a part this computer lacks).
UNREAD = "unknown"


# ------------------------------------------------------------------------------------------------ values

def _switch(text: str) -> bool:
    said = text.strip().lower()
    if said in ("on", "true", "yes", "1"):
        return True
    if said in ("off", "false", "no", "0"):
        return False
    raise ValueError("on or off")


def _one_of(*choices: str) -> Callable[[str], str]:
    def parse(text: str) -> str:
        if text.strip() not in choices:
            raise ValueError(" or ".join(choices))
        return text.strip()
    return parse


def _count(low: int, high: int) -> Callable[[str], int]:
    def parse(text: str) -> int:
        if not text.strip().isdigit() or not low <= int(text) <= high:
            raise ValueError(f"a whole number from {low} to {high}")
        return int(text)
    return parse


def _codes(text: str) -> list[str]:
    codes = [c for c in re.split(r"[\s,，、]+", text.strip()) if c]
    if not codes or any(c not in READABLE for c in codes):
        raise ValueError("language codes from " + ", ".join(READABLE))
    return list(dict.fromkeys(codes))


def _hours(text: str) -> dict | None:
    from .settings import walk_time
    if text.strip().lower() == "off":
        return None
    start, _, end = text.partition("-")
    if not walk_time(start.strip()) or not walk_time(end.strip()):
        raise ValueError("off, or the hours as 22:00-08:00")
    return {"from": walk_time(start.strip()), "to": walk_time(end.strip())}


def _colour(text: str) -> str:
    if not COLOUR.fullmatch(text.strip()):
        raise ValueError("a colour as #rrggbb")
    return text.strip().lower()


def shown(value: Any) -> str:
    """A value as the model reads it."""
    if isinstance(value, bool):
        return "on" if value else "off"
    if value is None:
        return "off"
    if isinstance(value, dict) and "from" in value:
        return f"{value['from']}-{value['to']}"
    if isinstance(value, (list, tuple)):
        return ", ".join(map(str, value)) or "none"
    return str(value)


# ------------------------------------------------------------------------------------------------ the catalogue

class Here:
    """What an item reads its value with: the page's own routes, read once each per call."""

    def __init__(self, get: Callable[[str], Awaitable[dict]], workspace) -> None:
        self._get, self.workspace, self._seen = get, workspace, {}

    async def get(self, route: str) -> dict:
        if route not in self._seen:
            self._seen[route] = await self._get(route)
        return self._seen[route]


def field(route: str, *path: str) -> Callable[[Here], Awaitable[Any]]:
    """The value at `path` in what GET `route` answers."""
    async def read(here: Here) -> Any:
        value: Any = await here.get(route)
        for part in path:
            value = value[part]
        return value
    return read


@dataclass(frozen=True)
class Item:
    page: str
    # The item's mark on its page (switchRow's id, kit.item's key); "" for the page as a whole.
    key: str
    # The locale key of its name on the page.
    label: str
    # What it governs, for the model.
    about: str
    now: Callable[[Here], Awaitable[Any]] | None = None
    # A change: the route the page posts it to, the body for a value (given what GET of that route answers when
    # `merged`, else {}), and how the model's text becomes a value. No parse: only the person changes it there.
    route: str = ""
    body: Callable[[Any, dict], dict] | None = None
    parse: Callable[[str], Any] | None = None
    # Which new values widen the character's permissions; None for an item none does.
    widens: Callable[[Any], bool] | None = None
    # The locale namespace that names its values (setup_shell.modes), for the question.
    values: str = ""
    merged: bool = False

    @property
    def id(self) -> str:
        return f"{self.page}/{self.key}" if self.key else self.page

    @property
    def place(self) -> str:
        """Where Settings opens for it (app.js follow)."""
        return f"setup/{self.id}"

    def widening(self, value: Any) -> bool:
        return self.widens is not None and self.widens(value)


def _turned_on(value: Any) -> bool:
    return value is True


async def _model(here: Here) -> str:
    from . import secretstore
    from .config_env import DEFAULT_LLM_BASE_URL, DEFAULT_LLM_MODEL
    values = await asyncio.to_thread(here.workspace.config)
    host = urlsplit(values.get("LLM_BASE_URL") or DEFAULT_LLM_BASE_URL).hostname or ""
    keyed = await asyncio.to_thread(secretstore.get, here.workspace.home, "LLM_API_KEY")
    return f"{host} · {values.get('LLM_MODEL') or DEFAULT_LLM_MODEL} · {'a key is set' if keyed else 'no key'}"


async def _search(here: Here) -> str:
    api = (await here.get("/api/walks"))["search"]
    return f"{api}, its key set" if api else "the keyless engines, no key"


async def _ui_lang(here: Here) -> str:
    from . import i18n
    return i18n.lang(await asyncio.to_thread(here.workspace.config))


async def _login(here: Here) -> bool:
    return (await here.get("/api/desk/shortcuts"))["login"] == "on"


ITEMS = (
    Item("character", "characters", "setup.names.character",
         "Which character it is: its name, picture and persona; choosing another changes the whole character",
         field("/api/state", "name")),
    Item("character", "accent", "setup_character.accent", "Mibo's main colour, a cool hue as #rrggbb",
         field("/api/look/colors", "accent"), "/api/look/colors", lambda v, now: {**now, "accent": v}, _colour,
         merged=True),
    Item("character", "shell", "setup_character.shell", "Mibo's shell colour, a pale cool hue as #rrggbb",
         field("/api/look/colors", "shell"), "/api/look/colors", lambda v, now: {**now, "shell": v}, _colour,
         merged=True),
    Item("model", "service", "setup.names.model",
         "The model service, the model and its key; every reply, page text, window picture and file text it reads "
         "goes there. Only they choose it", _model),
    Item("model", "more", "setup_model.more", "A backup model, the model for short calls, time limits"),
    Item("connect", "sites", "setup.names.connect",
         "Sites they signed in to in the app's own browser, which you read and act on with their sign-in; they "
         "sign in themselves"),
    Item("language", "display", "setup_language.display", "The language of the app's screens",
         _ui_lang, "/api/look/ui", lambda v, now: {"lang": v}, _one_of("zh", "zh-TW", "en", "ja", "ko", "es", "fr",
                                                                     "de", "pt-BR", "ru")),
    Item("language", "readable", "setup_language.canRead", "The languages they read; finds come in these",
         field("/api/situation", "factors", "readable", "value"), "/api/situation",
         lambda v, now: {"name": "readable", "value": v}, _codes),
    Item("recs", "pace", "setup_recs.paceName", "How often finds are brought: less, normal or more",
         field("/api/profile/taste", "pace"), "/api/profile/taste", lambda v, now: {"pace": v},
         _one_of("less", "normal", "more")),
    Item("recs", "recs-quiet", "setup_recs.quietName", "Quiet hours with no finds brought, as 22:00-08:00, or off",
         field("/api/profile/taste", "quiet_hours"), "/api/profile/taste", lambda v, now: {"quiet_hours": v}, _hours),
    Item("recs", "taste", "setup_recs.tasteTitle", "Their topics and what their reactions taught, each with a lean"),
    Item("walks", "walks-on", "setup_walks.onName", "Going out on its own to public sites, as a visitor",
         field("/api/walks", "on"), "/api/walks", lambda v, now: {"on": v}, _switch, _turned_on),
    Item("walks", "walks-count", "setup_walks.walksName", "Walks a day, 0 to 6",
         field("/api/walks", "walks"), "/api/walks", lambda v, now: {"walks": v}, _count(0, 6)),
    Item("walks", "search-key", "setup_walks.searchTitle",
         "The web search service and its key, which they bring themselves", _search),
    Item("walks", "sites", "setup_walks.moreTitle", "Sites walks keep off or favour"),
    Item("walks", "record", "setup_walks.recordTitle", "What each walk read and skipped"),
    Item("memory", "memory-on", "setup_memory.onTitle", "Memory of them used and kept",
         field("/api/person", "settings", "on"), "/api/person/settings", lambda v, now: {"on": v}, _switch,
         _turned_on),
    Item("memory", "memory-health", "setup_memory.healthTitle", "Health details kept in memory",
         field("/api/person", "settings", "health"), "/api/person/settings", lambda v, now: {"health": v}, _switch,
         _turned_on),
    Item("memory", "items", "setup.names.memory", "Each thing kept about them, to rewrite or forget"),
    Item("memory", "transfer", "setup_memory.moreTitle", "Memory exported, or another assistant's list imported"),
    Item("memory", "all", "setup_memory.allTitle", "Forgetting everything; only they do it"),
    Item("privacy", "remarks", "setup_privacy.remarksTitle",
         "Reading the program and window title in front, for a line now and then",
         field("/api/remarks/settings", "on"), "/api/remarks/settings", lambda v, now: {"on": v}, _switch,
         _turned_on),
    Item("privacy", "quiet", "setup_privacy.quietTitle", "Hiding the pet and holding back in full screen and games",
         field("/api/quiet/settings", "on"), "/api/quiet/settings", lambda v, now: {"on": v}, _switch),
    Item("privacy", "browsing", "setup_privacy.browsingTitle",
         "Using what they read in the app's browser (its history and pages)",
         field("/api/browser", "shared"), "/api/browser", lambda v, now: {"shared": v}, _switch, _turned_on),
    Item("privacy", "history", "setup_privacy.historyTitle", "The app browser's history, searched or cleared"),
    Item("privacy", "permits", "setup_privacy.permitsFold", "Camera, microphone, location and other site permissions"),
    Item("privacy", "sites", "setup_privacy.sitesFold", "Per site: kinds of act allowed without asking, the feed read"),
    Item("shell", "shell-on", "setup_shell.onTitle", "Doing things on this computer by command and file tools",
         field("/api/shell", "on"), "/api/shell", lambda v, now: {"on": v}, _switch, _turned_on),
    Item("shell", "shell-mode", "setup_shell.modeName", "read (read only) or auto (automatic review)",
         field("/api/shell", "mode"), "/api/shell", lambda v, now: {"mode": v}, _one_of("read", "auto"),
         lambda v: v == "auto", "setup_shell.modes"),
    Item("shell", "folders", "setup_shell.foldersTitle", "The folders it may use; granted when it asks in the chat"),
    Item("shell", "rules", "setup_shell.rulesTitle", "Programs always allowed in a folder, each taken back there"),
    Item("shell", "record", "setup_shell.logFold", "Every command run, with its result"),
    Item("programs", "programs-on", "setup.names.programs", "Operating other programs' windows on this computer",
         field("/api/programs", "on"), "/api/programs", lambda v, now: {"on": v}, _switch, _turned_on),
    Item("programs", "programs-mode", "setup_programs.modeName", "read (read only) or auto (automatic review)",
         field("/api/programs", "mode"), "/api/programs", lambda v, now: {"mode": v}, _one_of("read", "auto"),
         lambda v: v == "auto", "setup_programs.modes"),
    Item("programs", "programs-pictures", "setup_programs.pictures",
         "Pictures of a window only a picture can work, sent to the model service with no question",
         field("/api/programs", "pictures", "on"), "/api/programs", lambda v, now: {"pictures": v}, _switch,
         _turned_on),
    Item("programs", "grants", "setup_programs.grantsTitle", "Programs allowed always, each with what it may do there"),
    Item("programs", "never", "setup_programs.neverFold", "Programs never operated, and words that block one"),
    Item("programs", "record", "setup_programs.logFold", "What was done in which program"),
    Item("abilities", "skills", "setup.names.skills", "Skills: guidance for kinds of task, installed or switched"),
    Item("abilities", "tools", "setup.names.tools",
         "Connectors (MCP servers): their programs and services, added, signed in, switched"),
    Item("schedule", "", "setup.names.schedule",
         "Scheduled tasks: reminders and tasks run at set times, made in the chat or there"),
    Item("schedule", "schedule-acts", "setup_schedule.acts", "Whether a scheduled task may work in the app's browser"),
    Item("device", "start", "setup_device.startTitle", "Starting at sign-in to this computer",
         _login, "/api/desk/shortcut", lambda v, now: {"which": "login", "on": v}, _switch),
    Item("device", "links", "setup_device.linksTitle", "Links open in the app's browser (app) or the system's (system)",
         field("/api/browser", "links"), "/api/browser", lambda v, now: {"links": v}, _one_of("app", "system")),
    Item("device", "side-fold", "setup_device.sideFoldTitle", "The sidebar folds while a page is open; kept per window"),
    Item("device", "background", "setup_device.bgTitle", "Running on after the window closes",
         field("/api/runtime", "background"), "/api/runtime/background", lambda v, now: {"on": v}, _switch),
    Item("device", "pet-shown", "setup_device.petTitle", "The desktop pet shown",
         field("/api/pet", "shown"), "/api/pet", lambda v, now: {"shown": v}, _switch),
    Item("device", "updates", "setup_device.updateTitle", "The version, and whether a newer one is out",
         field("/api/runtime", "version")),
    Item("device", "data", "setup_device.dataTitle", "Backing up, restoring and resetting everything; only they do it"),
    Item("about", "version", "setup_about.version", "The app's version", field("/api/state", "version")),
    Item("about", "licences", "setup_about.licences", "The licences"),
)
BY_ID = {item.id: item for item in ITEMS}


def where(item: Item, lang: str) -> str:
    """The item as the person finds it: 设置 › 本机 › 显示桌宠."""
    from . import i18n
    parts = [i18n.t("setup.title", lang), i18n.t(f"setup.names.{item.page}", lang)]
    name = i18n.t(item.label, lang, count=0)
    return " › ".join(parts + ([name] if name != parts[-1] else []))


def value_words(item: Item, value: Any, lang: str) -> str:
    """A new value as the question in the chat names it."""
    from . import i18n
    if isinstance(value, bool):
        return i18n.t("appmap.on" if value else "appmap.off", lang)
    return i18n.t(f"{item.values}.{value}", lang) if item.values else shown(value)


def selected(name: str) -> list[Item]:
    """The items `name` picks: one by its id, a page's, or all of them."""
    if name in BY_ID:
        return [BY_ID[name]]
    return [item for item in ITEMS if not name or item.page == name]


# ------------------------------------------------------------------------------------------------ the page's side

def mount(app, workspace, body, token: str) -> None:
    import httpx

    from . import crossing, i18n
    from .cardwait import Card
    from .chatlangs import CODES
    from .panels.runtime import WINDOW_HEADER
    from .welcome import TOKEN_HEADER

    cards = Card(workspace, lambda: getattr(app.state, "window", None))

    def client(own: bool) -> httpx.AsyncClient:
        """The page's own routes, called in this process. `own`: a change past the gate below, made as a press on
        the app's own page makes it."""
        window = getattr(app.state, "window", None)
        headers = {TOKEN_HEADER: token, **({WINDOW_HEADER: window.frame_key} if own and window is not None else {})}
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                                 base_url="http://127.0.0.1", headers=headers, timeout=60)

    async def get(route: str) -> dict:
        async with client(False) as page:
            answer = await page.get(route)
            answer.raise_for_status()
            return answer.json()

    async def now(item: Item, here: Here) -> Any:
        """The item's value now; UNREAD when the page could not read it (a part this computer lacks)."""
        try:
            return await item.now(here)
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            return UNREAD

    async def listing(name: str, lang: str) -> dict:
        here = Here(get, workspace)
        rows = []
        for item in selected(name):
            rows.append({"id": item.id, "where": where(item, lang), "about": item.about,
                         "now": shown(await now(item, here)) if item.now is not None else "",
                         "change": "no" if item.parse is None else "asks" if item.widens is not None else "yes"})
        return {"status": "ok", "items": rows}

    async def change(item: Item, text: str, conversation: str) -> dict:
        try:
            value = item.parse(text)
        except ValueError as problem:
            return {"status": "invalid", "takes": str(problem)}
        here = Here(get, workspace)
        was = await now(item, here)
        if value == was:
            return {"status": "same", "now": shown(value)}
        names = [i18n.t(item.label, code, count=0) for code in CODES]
        if item.widening(value) and crossing.widening_in(workspace, {"names": names}):
            card = {"type": "setting", **{code: {
                "title": i18n.t("appmap.ask", code, name=i18n.t(item.label, code, count=0),
                                value=value_words(item, value, code)),
                "lines": [i18n.t("appmap.widens", code)]} for code in CODES}}
            yes = await cards.ask(card, conversation, {code: card[code]["title"] for code in ("zh", "en")},
                                  risk="widen")
            if not yes:
                return {"status": "declined" if yes is False else "unanswered", "now": shown(was)}
        whole = await here.get(item.route) if item.merged else {}
        async with client(True) as page:
            answer = await page.post(item.route, json=item.body(value, whole))
        if answer.status_code != 200:
            # The page's own code for it (an error route's {"error"}), else the status.
            error = str((answer.json() if "json" in answer.headers.get("content-type", "") else {}).get("error")
                        or answer.status_code)
            logger.info("[Agent] settings %s -> %s", item.id, error)
            return {"status": "failed", "error": error, "now": shown(was)}
        logger.info("[Agent] settings %s changed", item.id)
        return {"status": "changed", "was": shown(was), "now": shown(value)}

    @app.post("/api/settings")
    async def settings_do(request: Request):
        """From the character's turn (appmap.use): {"do": list | open | change, "item", "value", "conversation"}."""
        payload = await body(request)
        do, name = payload.get("do"), str(payload.get("item") or "").strip().strip("/")
        lang = i18n.lang(await asyncio.to_thread(workspace.config))
        if do == "list":
            return await listing(name, lang) if selected(name) else {"status": "unknown"}
        # An item by its id, else a page by its name.
        item = BY_ID.get(name) or next((one for one in ITEMS if one.page == name), None)
        if do not in ("open", "change") or item is None:
            return {"status": "unknown"}
        if do == "open":
            window = getattr(app.state, "window", None)
            place, shown_as = (item.place, where(item, lang)) if name in BY_ID else (
                f"setup/{item.page}", i18n.t(f"setup.names.{item.page}", lang))
            if window is None:
                return {"status": "no_window", "where": shown_as}
            await asyncio.to_thread(window.open_at, place)
            return {"status": "opened", "where": shown_as}
        if name not in BY_ID or item.parse is None:
            return {"status": "theirs", "where": where(item, lang)}
        conversation = payload.get("conversation")
        if not isinstance(conversation, str):
            return JSONResponse({"error": "generic"}, status_code=400)
        return {**await change(item, str(payload.get("value") or ""), conversation), "where": where(item, lang)}

    @app.get("/api/settings/card")
    async def settings_card():
        """The question waiting in the chat, if any (chat.js draws it; /api/confirm answers it)."""
        return {"card": cards.card}


# ------------------------------------------------------------------------------------------------ the agent's side

_SAID = {
    "unknown": "Error: there is no such item; do list gives them.",
    "no_window": "Error: the app window is not open, so nothing was opened. Tell them it is in {where}.",
    "opened": "Opened {where} for them.",
    "theirs": "Error: only they change this, in {where}; open it for them with do open.",
    "invalid": "Error: not changed: it takes {takes}.",
    "same": "It is already {now}; nothing changed.",
    "changed": "Changed {where}: {was} -> {now}. Tell them in a sentence.",
    "declined": "Error: they did not say yes in the chat, so {where} stays {now}.",
    "unanswered": "Error: the question about {where} got no answer, so it stays {now}. Tell them it needs their yes.",
    "failed": "Error: the app did not take it ({error}), so {where} stays {now}. Tell them.",
    "no_app": "Error: not done: the app's page is not there.",
}


async def use(agent, args: dict, lookups) -> str:
    """One call of `settings`: the list, Settings opened at an item, or a change, as the page answers it."""
    from . import today
    from .browsed import _ask
    from .cardwait import WAIT_S
    home = today.runtime_of(agent).parent
    do, item = args.get("do"), " ".join(str(args.get("item") or "").split())[:80]
    lookups.doing(NAME, item)
    # A widening change waits on the person's answer, which is not the turn's model time.
    lookups.away_since = time.monotonic()
    try:
        outcome = await asyncio.to_thread(_ask, home, "POST", "/api/settings", WAIT_S + 60, json={
            "do": do, "item": item, "value": str(args.get("value") or ""), "conversation": lookups.conversation})
    finally:
        lookups.away_s, lookups.away_since = lookups.away(), None
    status = outcome.get("status") or "no_app"
    if status == "ok":
        return ("Settings by page; id | where they find it | now | change (yes: you change it when they ask; asks: "
                "a change that widens what you may do is asked in the chat; no: only they change it there). A key "
                "or a token is never shown.\n" + "\n".join(
                    " | ".join(v for v in (row["id"], row["where"], row["now"] and f"now {row['now']}",
                                           f"change {row['change']}", row["about"]) if v)
                    for row in outcome["items"]))
    values = {"where": "", "now": "", "was": "", "takes": "", "error": "", **outcome}
    return _SAID.get(status, _SAID["no_app"]).format(**values)
