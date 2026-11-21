"""How much the character may do by itself when it acts for the person: one mode for pages in the app's browser
and one for other programs' windows, each chosen by the person in one place (the pane's chat box, Settings ›
programs) and read again at every action, so a change made while a task runs holds from its next step.

    off    it does not act there at all
    read   it looks, reads, scrolls and moves between pages; nothing it does sends, saves or changes anything
           (in a program: it only looks)
    ask    each action with an effect outside waits for the person's press on a card (the default)
    auto   the reviewer (review.py) looks first at sends, comments, likes, posts, submissions and presses that code
           could not sort; only those it finds plainly asked for go ahead without a card, the rest still ask

What no mode loosens, decided here in code: paying or buying, deleting, an account's security or access (`HARD`)
ask every time, with no always-allow and no reviewer; a password, payment detail or code is never typed or read
by the character (the gates); sending and posting skip the card only by the person's always-allow for that site
(ask) or the reviewer's pass (auto), never on a sensitive site (`sensitive`: banks and payment, health, mail and
accounts), where every kind asks. The reviewer passes nothing while no request of the person's own is under way.

Claude in Chrome's ask-before-acting / act-without-asking with its plan, Claude Code's permission modes with
its classifier, Codex's approvals reviewer and Qwen Code's approval modes are what this follows.
"""
from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime
from pathlib import Path

AREAS = ("browser", "programs")
MODES = ("off", "read", "ask", "auto")
DEFAULT = "ask"
FILE = "acting.json"
# The kinds that ask in every mode, each time.
HARD = frozenset({"order", "delete", "account", "grant"})
# Sites where every kind asks and nothing is let through: banks, payment, brokers, health, mail and accounts.
SENSITIVE = re.compile(
    r"(?:^|\.)(?:bank|banking|pay|wallet|alipay|paypal|stripe|venmo|broker|securities|stock|fund|insurance|health|"
    r"hospital|clinic|medical|pharmacy|mail|webmail|outlook|icloud|account|accounts|login|signin|passport|id|gov|tax|"
    r"icbc|ccb|abchina|boc|bankcomm|cmbchina|psbc|spdb|cib|citicbank|cebbank|cmbc|pingan|webank|mybank|95516|"
    r"unionpay|chase|wellsfargo|citi|hsbc|barclays|schwab|fidelity|vanguard|robinhood|coinbase|binance|okx|gmail|"
    r"proton)\.", re.I)


def sensitive(site: str) -> bool:
    """A bank's, a payment service's, a broker's, a health service's or a mail service's site."""
    host = str(site or "").split(":")[0].lower()
    return bool(host) and bool(SENSITIVE.search(host))


def decide(mode: str, kind: str, site: str = "", area: str = "browser") -> str:
    """What an action of an outside `kind` gets in `mode`: "refuse" (read only), "review" (auto, a kind the
    reviewer may pass, on a site that is not sensitive) or "ask" (a card)."""
    from .review import REVIEWABLE
    if mode in ("off", "read"):
        return "refuse"
    if mode == "auto" and kind not in HARD and kind in REVIEWABLE[area] and not sensitive(site):
        return "review"
    return "ask"


class Modes:
    """The person's mode per area, in the desktop folder. Programs' off is the switch in desk.json (desk/grants.py),
    so the two can never disagree; the level beside it is kept here."""

    def __init__(self, desktop: Path):
        self.desktop = Path(desktop)
        self.path = self.desktop / FILE
        self.lock = threading.Lock()

    def _read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def mode(self, area: str) -> str:
        if area == "programs":
            from .desk.grants import Grants
            if not Grants(self.desktop).on():
                return "off"
        kept = self._read().get(area)
        return kept if kept in MODES and not (area == "programs" and kept == "off") else DEFAULT

    def all(self) -> dict:
        return {area: self.mode(area) for area in AREAS}

    def set(self, area: str, mode: str) -> dict:
        from .storage import atomic_write_text
        if area == "programs":
            from .desk.grants import Grants
            grants = Grants(self.desktop)
            if grants.on() != (mode != "off"):
                grants.set_on(mode != "off")
        with self.lock:
            data = self._read()
            if area == "programs" and mode == "off":
                data.pop(area, None)
            else:
                data[area] = mode
            self.desktop.mkdir(parents=True, exist_ok=True)
            atomic_write_text(self.path, json.dumps(data, ensure_ascii=False))
        return self.all()


def asked(workspace) -> list[dict]:
    """The person's own messages in the conversation whose turn is under way, from the app's chat record, never
    from the model: [{"text", "at"}], the latest last; none while no turn of theirs is under way."""
    if not workspace._chat_lock.locked():
        return []
    try:
        doing = json.loads((Path(workspace.home) / "runtime" / "desktop" / "chat-doing.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    room = next((chat for chat in [workspace._main, *workspace._chats.values()]
                 if chat.conversation == doing.get("conversation")), None)
    out = []
    for message in room.history if room is not None else []:
        if message.get("role") != "user" or not str(message.get("text") or "").strip():
            continue
        try:
            at = datetime.fromisoformat(str(message.get("at"))).timestamp()
        except ValueError:
            at = time.time()
        out.append({"text": str(message["text"]), "at": at})
    return out[-8:]


def reviewer(workspace):
    """The reviewer's one model call, on the person's own model service as the app's settings name it."""
    from .review import endpoint
    values = workspace.config()
    return endpoint(values.get("LLM_BASE_URL", ""), values.get("LLM_API_KEY", ""), values.get("LLM_MODEL", ""))
