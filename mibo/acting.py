"""How much the character may do by itself when it acts for the person: one mode for pages in the app's browser,
one for other programs' windows and one for commands and files, each chosen by the person in one place (the
pane's chat box, Settings › programs, Settings › files and commands) and read again at every action, so a change
made while a task runs holds from its next step.

    off    it does not act there at all
    read   it looks, reads, scrolls and moves between pages; nothing it does sends, saves or changes anything
           (in a program: it only looks; by command: it only reads files in the granted folders)
    auto   automatic review, the default: code first lets through what plainly only reads or moves about, or can
           be undone inside what the person granted (a page's own reads and telemetry, a tab or filter fetching
           what it shows, a read-only command, a file changed in a granted folder under each turn's checkpoint);
           the reviewer (review.py) then judges what is left of the reviewable kinds, and a card comes only where
           it does not pass or code says always ask

What no mode loosens, decided here in code: paying or buying, deleting, an account's security or access (`HARD`)
ask every time, with no always-allow and no reviewer; a password, payment detail or code is never typed or read
by the character (the gates); sending and posting skip the card only by the person's always-allow for that site or
the reviewer's pass, never on a sensitive site (`sensitive`: banks and payment, health, mail and accounts), where
every kind asks. The reviewer passes nothing while no request of the person's own is under way.

Claude Code's auto mode with its classifier, Claude in Chrome's act-without-asking with its plan, Codex's
approvals reviewer and Qwen Code's approval modes are what this follows.
"""
from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime
from pathlib import Path

AREAS = ("browser", "programs", "commands")
MODES = ("off", "read", "auto")
DEFAULT = "auto"
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
    """What an action of an outside `kind` gets in `mode`: "refuse" (read only), "review" (a kind the reviewer
    may pass, on a site that is not sensitive) or "ask" (a card)."""
    from .review import REVIEWABLE
    if mode in ("off", "read"):
        return "refuse"
    if kind not in HARD and kind in REVIEWABLE[area] and not sensitive(site):
        return "review"
    return "ask"


class Modes:
    """The person's mode per area, in the desktop folder. The off of programs and of commands is their own switch
    (desk.json, shell.json), so the two can never disagree; the level beside it is kept here."""

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

    def _switch(self, area: str):
        """The area's own on/off switch, or None (the browser has none)."""
        if area == "programs":
            from .desk.grants import Grants
            return Grants(self.desktop)
        if area == "commands":
            from .shell.grants import Grants as ShellGrants
            return ShellGrants(self.desktop, self.desktop.parents[1])
        return None

    def mode(self, area: str) -> str:
        switch = self._switch(area)
        if switch is not None and not switch.on():
            return "off"
        kept = self._read().get(area)
        return kept if kept in MODES and not (switch is not None and kept == "off") else DEFAULT

    def all(self) -> dict:
        return {area: self.mode(area) for area in AREAS}

    def set(self, area: str, mode: str) -> dict:
        from .storage import atomic_write_text
        switch = self._switch(area)
        if switch is not None and switch.on() != (mode != "off"):
            switch.set_on(mode != "off")
        with self.lock:
            data = self._read()
            if switch is not None and mode == "off":
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
