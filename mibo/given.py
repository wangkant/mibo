"""The web addresses given to the character in a conversation, and the ones it composed (crossing.py).

A model that read outside material can be told by it to carry the person's private words out inside an address it
writes: in its path or query, or in a host name. So, as Anthropic's web fetch tool opens only addresses that came up
in the conversation and OpenAI's url_safe check does, an address the model wrote is opened by itself only when it was
given, compared in its normal form (`form`: scheme and "www." dropped, host lower-cased, fragment and a trailing slash
dropped, percent-encoding written one way; path and query otherwise exact):
- it stands in the person's own typed messages of the conversation (the chat record, never the model's history), or
  in the stored request of the scheduled task being run;
- it stands in material the app itself handed the model there (`SOURCES`: search results, a page read with its
  links and its address after redirects, a list read with their session, a site's finds, the finds brought, the
  pages they read in the app's browser; the finds the chat shows; the address a page in the app's browser is at), and
  no call of the model's this turn holds it: a page or a server that repeats what the model wrote is an echo;
- its host is one the app knows for a site (`hosts`: platforms.py, web/signin_sites.json's pages, web/places.json's,
  web/seeds.json's; and a known site's own other hosts, `_OWN`: its mobile pages, Wikipedia's languages)
  or one the person typed; unless it carries another address that is not given, as a redirect or a proxy does
  (`carried`). Another sub-domain of such a site is given only as an exact given address: a user's own host on a
  platform, or a sub-domain that carries data in its name, is not the site.
A host that only appeared in material gives nothing beyond its exact addresses: that is the attacker's own host. Files,
command output, MCP servers' answers and the report of messages read are no source: the model can write them, or a
model wrote them.

Where the rule holds: a conversation that read no outside material, this turn or earlier, and took in nothing the
person did not type (crossing.steered, `Given.steered`) opens every address, as nothing could have steered the model.
After that, a composed address is not opened, in the person's turn as in a scheduled run, and nobody is asked: the
model is told to find the page with a search, and to hand an address it is sure of to the person in its reply, where
the page shows it whole before opening it (linkcard.js). A search query is no address: it goes to the search engine.
The chat's link cards fetch a preview or an icon only for a given address, or one of a conversation that read nothing
(`shown`).

Kept per conversation in runtime/desktop/given.json (MOST_CHATS conversations, MOST hashes each, the newest kept): a
truncated SHA-256 of each given address's normal form and of its host (`digest`), never the address, so a chat's words
forgotten leave none of their bytes there; and whether it read outside material. A 无痕对话's are kept in this process
only.
"""
from __future__ import annotations

import asyncio
import contextlib
import functools
import hashlib
import json
import re
import threading
import time
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from fastapi import Request
from fastapi.responses import JSONResponse

FILE = "given.json"
MOST, MOST_CHATS = 2000, 32
# The tools whose results hand the model addresses it may open.
SOURCES = frozenset({"web_search", "read_page", "read_with_their_session", "find_on_site", "bring_find",
                     "pages_they_read"})
# The tools that open the address the model gives as `url`.
READS = frozenset({"read_page", "read_with_their_session"})
# An address as the chat page finds one in a message (linkcard.js URL_RE), its closing marks trimmed.
SCHEMED = re.compile(r"https?://[^\s<>\"'，。！？；）】」　]+", re.I)
_CLOSING = ".,;:!?)]"
# A host with no scheme before it: dotted names ending in a public suffix, a port and a path after it.
BARE = re.compile(r"(?<![A-Za-z0-9_@./:%-])((?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63})(?::\d{1,5})?"
                  r"(?:[/?][^\s<>\"'，。！？；）】」　]*)?", re.I)
_PATH_SAFE = "/:@!$&'()*+,;=~"
_QUERY_SAFE = _PATH_SAFE + "?"
# What the model is told when an address it composed is not opened: in the person's turn, and in a scheduled run.
NOT_OPENED = {
    "turn": ("Error: not opened: {url} is an address you wrote yourself, not one from their messages, a search result "
             "or a page you read, and this conversation has read outside material. Find the page with web_search and "
             "read a result. If you are sure of an address the search does not find, give it to them in your reply "
             "for them to open."),
    "run": ("Error: not opened: in a scheduled run nobody is watching, an address you wrote yourself, not taken "
            "from their request, a search result or a page you read, is not opened. Search for the page with "
            "web_search and read a result, or put it into propose_action for them to open."),
}


def found(text: str) -> list[str]:
    """The web addresses in `text`, with their scheme or without one, as written."""
    text = str(text or "")
    out = [match.group(0).rstrip(_CLOSING) for match in SCHEMED.finditer(text)]
    rest = SCHEMED.sub(" ", text)
    from .situation import _suffixes
    rules = _suffixes()[0]
    out += [match.group(0).rstrip(_CLOSING) for match in BARE.finditer(rest)
            if match.group(1).rsplit(".", 1)[-1].lower() in rules]
    return [address for address in out if address]


def form(address: str) -> str:
    """An address's normal form: no scheme, no "www.", the host lower-cased, no fragment and no trailing slash, its
    percent-encoding written one way, its user, path and query otherwise as they are; "" for what is no web
    address."""
    text = str(address or "").strip()
    if not re.match(r"[a-z][a-z0-9+.-]*://", text, re.I):
        text = "//" + text
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError:
        return ""
    host = (parts.hostname or "").rstrip(".").removeprefix("www.")
    if (parts.scheme and parts.scheme.lower() not in ("http", "https")) or not host:
        return ""
    with contextlib.suppress(UnicodeError):
        host = host.encode("idna").decode("ascii")
    user = parts.netloc.rpartition("@")[0]
    path = quote(unquote(parts.path), safe=_PATH_SAFE)
    query = quote(unquote(parts.query), safe=_QUERY_SAFE)
    return (f"{quote(unquote(user), safe=':') + '@' if user else ''}{host}"
            f"{f':{port}' if port and port not in (80, 443) else ''}{path.removesuffix('/')}"
            f"{'?' + query if query else ''}")


def host_of(address: str) -> str:
    """The host of an address or of a normal form, as `form` writes it."""
    shaped = form(address)
    return urlsplit("//" + shaped).hostname or "" if shaped else ""


def digest(shaped: str) -> str:
    """What is kept of a normal form or a host: the first 16 hex digits of its SHA-256."""
    return hashlib.sha256(shaped.encode("utf-8")).hexdigest()[:16]


def digests(addresses) -> list[str]:
    """The hashes `Given` keeps for `addresses`: of each one's normal form and of its host ("host " before it)."""
    out = []
    for address in addresses:
        shaped = form(address)
        if shaped:
            out += [digest(shaped), digest("host " + host_of(shaped))]
    return out


def carried(address: str) -> list[str]:
    """The addresses an address carries in its path or query, as a redirect or a proxy takes one: written with a
    scheme anywhere, or as a query's value, percent-encoded or not."""
    try:
        parts = urlsplit(str(address or "").strip())
    except ValueError:
        return []
    inside = unquote(unquote(f"{parts.path}?{parts.query}"))
    return found(re.sub(r"[=&]", " ", inside))


@functools.lru_cache(maxsize=1)
def hosts() -> frozenset[str]:
    """The hosts the app knows for its sites, as `form` writes them: each platform's registrable host, and the hosts
    of the pages the sign-in hints and the places opened by name name."""
    from .platforms import PLATFORMS
    from .resolve import PLACES
    from .web import signin
    pages = [row.get(key) for row in signin.hints() for key in ("home", "signin")]
    pages += [m["url"] for row in signin.hints() for m in row.get("messages") or []]
    pages += [row.get(key) for row in json.loads(PLACES.read_text(encoding="utf-8")) for key in ("home", "signin")]
    seeds = json.loads(PLACES.with_name("seeds.json").read_text(encoding="utf-8"))["hosts"]
    pages += [p for row in seeds.values() for p in (row.get("home"), row.get("search"), *(row.get("hot") or []))]
    return frozenset([*PLATFORMS, *seeds, *(row["site"] for row in signin.hints()),
                      *(host_of(p) for p in pages if p)])


# The other hosts a known site runs itself: its mobile pages, Wikipedia's languages, Hacker News. Any other
# sub-domain may be a user's own page there.
_OWN = re.compile(r"(?:m|mobile)\.(.+)|[a-z]{2,3}(?:-[a-z]+)?(?:\.m)?\.(wikipedia\.org)|news\.(ycombinator\.com)")


def site_host(host: str) -> str:
    """`host`, or the known host it is such a host of."""
    match = _OWN.fullmatch(host)
    site = next(filter(None, match.groups()), "") if match else ""
    return site if site in hosts() else host


def given(address: str, kept: set[str], words: list[str]) -> bool:
    """Whether `address` is given: its normal form's hash is among `kept` (what material handed the model) or it
    stands in the person's own `words`, or its host is one the app knows or they typed and it carries no address that
    is not given."""
    own = form(address)
    if not own:
        return False
    said = {form(a) for w in words for a in found(w)}
    if digest(own) in kept or own in said:
        return True
    near = hosts() | {host_of(a) for a in said}
    return site_host(host_of(own)) in near and all(
        digest(form(a)) in kept or form(a) in said or site_host(host_of(a)) in near for a in carried(address))


def host_given(host: str, kept: set[str], words: list[str]) -> bool:
    """Whether `host` is the host of a given address, one the app knows, or one they typed."""
    host = host.lower().removeprefix("www.")
    return (digest("host " + host) in kept or host in hosts()
            or any(host_of(a) == host for w in words for a in found(w)))


class Given:
    """The hashes of each conversation's given addresses and whether it read outside material, in
    runtime/desktop/given.json: {conversation: {"at", "outside", "given": [hashes, the newest last]}}; a 无痕对话's in
    `private`."""

    def __init__(self, desktop: Path) -> None:
        self.path = Path(desktop) / FILE
        self.lock = threading.Lock()
        try:
            self.chats: dict = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.chats = {}
        self.private: dict = {}

    def _row(self, conversation: str) -> dict:
        from .channels import private_chat
        rows = self.private if private_chat(conversation) else self.chats
        return rows.setdefault(conversation, {"at": time.time(), "outside": False, "given": []})

    def _save(self) -> None:
        from .storage import atomic_write_text
        for gone in sorted(self.chats, key=lambda c: self.chats[c]["at"])[:max(0, len(self.chats) - MOST_CHATS)]:
            del self.chats[gone]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self.path, json.dumps(self.chats))

    def took(self, conversation: str, addresses: list[str]) -> None:
        """`addresses` handed the model in `conversation`, kept as given."""
        new = list(dict.fromkeys(digests(addresses)))
        with self.lock:
            row = self._row(conversation)
            kept = [a for a in row["given"] if a not in new]
            if kept + new == row["given"]:
                return
            row.update(at=time.time(), given=(kept + new)[-MOST:])
            self._save()

    def mark(self, conversation: str) -> None:
        """`conversation` read outside material, or took in what the person did not type."""
        with self.lock:
            row = self._row(conversation)
            if not row["outside"]:
                row.update(at=time.time(), outside=True)
                self._save()

    def steered(self, conversation: str) -> bool:
        with self.lock:
            return bool((self.private.get(conversation) or self.chats.get(conversation) or {}).get("outside"))

    def hashes(self, conversation: str) -> set[str]:
        with self.lock:
            return set((self.private.get(conversation) or self.chats.get(conversation) or {}).get("given") or ())

    def has(self, conversation: str, address: str) -> bool:
        return digest(form(address)) in self.hashes(conversation)

    def forget(self, conversation: str) -> None:
        """A chat deleted or started anew: what it was given goes with it."""
        with self.lock:
            self.private.pop(conversation, None)
            if self.chats.pop(conversation, None) is not None:
                self._save()


_KEPT: dict[str, Given] = {}


def kept(desktop: Path) -> Given:
    """The one Given of the app whose desktop folder is `desktop`."""
    return _KEPT.setdefault(str(Path(desktop).resolve()), Given(desktop))


# ------------------------------------------------------------ the page's side

def _record(workspace, conversation: str) -> tuple[set[str], list[str]]:
    """What the chat `conversation` itself holds: the hashes of the finds it shows, and the person's own messages as
    they typed them."""
    room = next((chat for chat in workspace._all_chats() if chat.conversation == conversation), None)
    history = room.history if room is not None else []
    return (set(digests(m["card"]["url"] for m in history if (m.get("card") or {}).get("url"))),
            [str(m.get("text") or "") for m in history if m.get("role") == "user"])


def shown(workspace, chat: str, address: str = "", host: str = "") -> bool:
    """Whether the app may fetch a link card's preview of `address`, or the icon of `host`, for the chat `chat`, and
    whether the page opens `address` with no confirmation: it stands in that chat's own record (a message, a reply's
    sources, a find's card), and the chat read no outside material and took in nothing the person did not type, or
    the address, or an address on the host, is given there. The record and the given addresses are the app's own, so
    a caller naming a chat reaches only what that chat holds."""
    from .cardwait import doing
    from .crossing import steered, turn_read
    room = workspace._chat(chat)
    texts = [str(text or "") for m in room.history
             for text in (m.get("text"), (m.get("card") or {}).get("url"), *(s.get("url") for s in m.get("sources") or []))]
    if not (form(address) in {form(a) for text in texts for a in found(text)} if address
            else any(host in text for text in texts)):
        return False
    store = kept(workspace._desktop)
    read = turn_read(workspace) if doing(workspace).get("conversation") == room.conversation else {}
    if not (store.steered(room.conversation) or steered(read)):
        return True
    cards, words = _record(workspace, room.conversation)
    known = store.hashes(room.conversation) | cards
    return given(address, known, words) if address else host_given(host, known, words)


def mount(app, workspace, body) -> None:
    @app.post("/api/address/given")
    async def address_given(request: Request):
        """From the character's turn, for an address it wrote after the conversation read outside material:
        {"given": true} when it is given by the chat's record, what the conversation was handed, or the stored request
        of the scheduled task being run (`run`)."""
        payload = await body(request)
        url, conversation, run = payload.get("url"), payload.get("conversation"), payload.get("run")
        if not (isinstance(url, str) and form(url) and isinstance(conversation, str)
                and (run is None or isinstance(run, str))):
            return JSONResponse({"error": "generic"}, status_code=400)
        cards, words = _record(workspace, conversation)
        return {"given": given(url, kept(workspace._desktop).hashes(conversation) | cards,
                               words + ([run] if run else []))}


# ----------------------------------------------------------- the agent's side

async def opens(agent, url: str, lookups) -> str:
    """Whether the model's address `url` is opened: "" to go on, else the Error line the call answers with. Opened
    while the conversation is not steered (and kept as given then), or when the address is given; never asked."""
    from . import today
    from .browsed import _ask
    from .crossing import steered
    from .schedule_tool import run_of
    store = lookups.given
    if store is None or urlsplit(url).scheme not in ("http", "https") or not form(url):
        return ""
    if not (steered(lookups.crossing.summary()) or store.steered(lookups.conversation)):
        store.took(lookups.conversation, [url])
        return ""
    if store.has(lookups.conversation, url):
        return ""
    run = run_of()
    answer = await asyncio.to_thread(_ask, today.runtime_of(agent).parent, "POST", "/api/address/given", 30,
                                     json={"url": url, "conversation": lookups.conversation,
                                           "run": run["words"] if run else None})
    return "" if answer.get("given") else NOT_OPENED["run" if run else "turn"].format(url=url[:300])
