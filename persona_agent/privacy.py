"""Whether the character may read what the person's mail and private messages say.

Off by default. Off, a look at mail, Discord or a chat account keeps none of
their words: the messages never enter the library (and so no prompt, memory or
recommendation); only how many came and from whom, which the character says in
a line made here, with no model. On, each one enters the library as its
sender, its subject and a short excerpt with addresses, numbers, codes and
links masked, and reaches the model from there. It can be on only while the
model is reached over https or runs on this computer, and only for the
service it was turned on for: a changed LLM_BASE_URL counts as off.

Kept in `<runtime>/privacy.json`, with the ids of the messages already counted
while off, so each is told once.
"""
from __future__ import annotations

import json
import re
import threading
from dataclasses import replace
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlsplit

from dotenv import dotenv_values

from .library import Item, Library, item_id
from .storage import atomic_write_text

SETTINGS_FILE = "privacy.json"
TITLE_MAX = 120
EXCERPT_MAX = 200
SEEN_MAX = 2000
NAMES_MAX = 3
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")

_lock = threading.Lock()
# Says a line with how many came while off; the page's lifespan gives it (listen).
_tell: Optional[Callable[[str], None]] = None

_LINK = re.compile(r"(https?://)([^/\s?#<>\"'()]+)([^\s<>\"']*)", re.I)
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_CODE = re.compile(r"((?<![A-Za-z])(?:验证码|校验码|动态码|动态密码|确认码|安全码|一次性密码|verification code|security code|"
                   r"one[- ]time (?:code|password|passcode)|otp|passcode|pin|code)\s*(?:is|是|为|:|：)?\s*)"
                   r"(?=[A-Za-z-]*\d)[A-Za-z0-9-]{4,10}(?![A-Za-z0-9])", re.I)
# Six digits or more, a space, dot or dash between them allowed: card, account, ID and phone numbers.
_DIGITS = re.compile(r"\+?\(?(?<!\d)\d(?:[\s().-]{0,2}\d){5,}(?!\d)")
_DATE = re.compile(r"\d{4}[-./]\d{1,2}[-./]\d{1,2}|\d{1,2}[-./]\d{1,2}[-./]\d{4}")


# ----------------------------------------------------------------- the switch --

def path(runtime: Path) -> Path:
    return Path(runtime) / SETTINGS_FILE


def _load(runtime: Path) -> dict:
    try:
        saved = json.loads(path(runtime).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    saved = saved if isinstance(saved, dict) else {}
    return {"on": saved.get("on") is True, "service": str(saved.get("service") or ""),
            "seen": [s for s in saved.get("seen") or [] if isinstance(s, str)]}


def _change(runtime: Path, change: Callable[[dict], None]) -> dict:
    with _lock:
        state = _load(runtime)
        change(state)
        state["seen"] = state["seen"][-SEEN_MAX:]
        Path(runtime).mkdir(parents=True, exist_ok=True)
        atomic_write_text(path(runtime), json.dumps(state))
        return state


def values_of(home: Path) -> dict:
    return {k: str(v or "") for k, v in dotenv_values(Path(home) / ".env").items()}


def service(values: dict) -> dict:
    """Where the text would go: the model service's host and model, and whether it may go there."""
    base = values.get("LLM_BASE_URL", "").strip()
    parts = urlsplit(base)
    host = parts.hostname or ""
    local = host in LOCAL_HOSTS or host.endswith(".localhost")
    return {"base": base, "host": parts.netloc.rpartition("@")[2], "model": values.get("LLM_MODEL", "").strip(),
            "local": local, "safe": bool(host) and (parts.scheme == "https" or (parts.scheme == "http" and local))}


def allowed(runtime: Path, values: dict) -> bool:
    """On, for the service the model is reached at now, and that service is safe to send to."""
    state, there = _load(runtime), service(values)
    return state["on"] and there["safe"] and state["service"] == there["base"]


def settings(runtime: Path, values: dict) -> dict:
    there = service(values)
    return {"on": allowed(runtime, values), "host": there["host"], "model": there["model"],
            "local": there["local"], "safe": there["safe"], "configured": bool(there["base"] and there["model"])}


def save(runtime: Path, values: dict, on: bool) -> dict:
    """Turn it on for the service configured now, or off; off takes the messages already kept out of the library."""
    there = service(values)
    if on and not (there["base"] and there["model"]):
        raise ValueError("privacy_no_model")
    if on and not there["safe"]:
        raise ValueError("privacy_unsafe")
    if not on:
        gone = forget(runtime)
        _change(runtime, lambda s: s.update(on=False, service="", seen=s["seen"] + gone))
    else:
        _change(runtime, lambda s: s.update(on=True, service=there["base"]))
    return settings(runtime, values)


def forget(runtime: Path) -> list[str]:
    """Every private message out of the library; their ids."""
    library = Library(runtime)
    return library.drop(lambda item: item.private)


# ------------------------------------------------------------------- masking --

def _link(match: re.Match) -> str:
    return match.group(1) + match.group(2) + ("/…" if match.group(3) else "")


def _digits(match: re.Match) -> str:
    text = match.group(0)
    return text if _DATE.fullmatch(text.strip("()+ ")) else "[number]"


def mask(text: str) -> str:
    """The text with e-mail addresses, codes, long numbers and the rest of each link after its host masked."""
    text = _LINK.sub(_link, str(text or ""))
    text = _EMAIL.sub("[email]", text)
    text = _CODE.sub(lambda m: m.group(1) + "[code]", text)
    return _DIGITS.sub(_digits, text)


def clip(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def sender(item: Item, what: str) -> str:
    """Who it is from: a mail's sender name, else the domain of the address; a talk's speakers."""
    if what == "message":
        return item.author
    name = item.site
    return name.rpartition("@")[2] if "@" in name else name


def masked(item: Item, what: str) -> Item:
    """What enters the library while on: sender, subject, a short masked excerpt; nothing whole."""
    return replace(item, site=clip(mask(item.site if what == "message" else sender(item, what)), 80),
                   title=clip(mask(item.title), TITLE_MAX), author="" if what == "mail" else clip(mask(item.author), 120),
                   description=clip(mask(item.description), EXCERPT_MAX), text="", private=True)


# ------------------------------------------------------------------- keeping --

def seen(runtime: Path) -> set[str]:
    """Ids of the messages counted while off."""
    return set(_load(runtime)["seen"])


def keep(runtime: Path, values: dict, items: list[Item], what: str) -> int:
    """Mail ("mail") or private messages ("message") a look found, new ones only. On: masked into the
    library. Off: their ids noted and a line with how many and from whom said; nothing else kept."""
    if not items:
        return 0
    if allowed(runtime, values):
        library = Library(runtime)
        for item in items:
            library.add(masked(item, what))
        return len(items)
    ids = [item_id(item.url) for item in items]
    before = seen(runtime)
    fresh = [item for item, ident in zip(items, ids) if ident not in before]
    _change(runtime, lambda s: s.update(seen=s["seen"] + [i for i in ids if i not in before]))
    if fresh and _tell is not None:
        _tell(line(fresh, what, values.get("AGENT_LANG", "")))
    return len(items)


def line(items: list[Item], what: str, lang: str) -> str:
    """"有 3 封新邮件，来自 A、B。": made here, from the count and the names only."""
    names: list[str] = []
    for item in items:
        for name in sender(item, what).split(", "):
            name = clip(mask(name), 40)
            if name and name not in names:
                names.append(name)
    zh = str(lang or "").lower().startswith("zh")
    n, shown, more = len(items), names[:NAMES_MAX], len(names) > NAMES_MAX
    if zh:
        head = f"有 {n} 封新邮件" if what == "mail" else f"有 {n} 条新消息"
        return head + (f"，来自 {'、'.join(shown)}{' 等' if more else ''}。" if shown else "。")
    head = f"{n} new email{'s' if n != 1 else ''}" if what == "mail" else f"{n} new message{'s' if n != 1 else ''}"
    return head + (f", from {', '.join(shown)}{' and others' if more else ''}." if shown else ".")


def listen(tell: Optional[Callable[[str], None]]) -> None:
    """Who says the lines; called from the looks' worker threads."""
    global _tell
    _tell = tell
