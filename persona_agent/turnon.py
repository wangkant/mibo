"""A switched-off ability offered in the chat: one entry tool in place of its tools, and the card that turns it on.

While commands and files (shell/) or other programs (desk/) are off, the reply model gets one tool, turn_on, that
names them; its many tools are not sent. When their message asks for one, the model calls it and the chat shows the
card: what the ability does and what always waits for a press, with 开启 / 暂不开启. A press on 开启 is the same as
the switch in Settings; the turn then goes on with that ability's tools. Only a press on the app's own page answers
it, never words typed in the chat, and the card waits only while the person's own turn is under way (cardwait.py).
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

from fastapi import Request
from fastapi.responses import JSONResponse

from .cardwait import WAIT_S, Card

NAME = "turn_on"
# The abilities that have a switch, and what the model and the card call each.
FEATURES = {
    "computer": {"model": "commands and files on this computer (use_computer and the file tools)",
                 "zh": "文件与命令", "en": "Files and commands"},
    "programs": {"model": "operating other programs' windows on this computer (use_program)",
                 "zh": "电脑上的程序", "en": "Other programs"},
}


def _who() -> str:
    return os.getenv("PERSONA_NAME", "").strip() or "Mibo"


def off(home: Path) -> list[str]:
    """The abilities switched off in this home, as FEATURES keys."""
    from .shell.grants import Grants as ShellGrants
    desktop = Path(home) / "runtime" / "desktop"
    shut = [] if ShellGrants(desktop, Path(home)).on() else ["computer"]
    if sys.platform == "win32":
        from .desk.grants import Grants as DeskGrants
        shut += [] if DeskGrants(desktop).on() else ["programs"]
    return shut


def tool(shut: list[str]) -> dict:
    """The entry tool for the abilities in `shut`."""
    return {"type": "function", "function": {
        "name": NAME,
        "description": (
            "These abilities of yours are switched off: " + "; ".join(FEATURES[k]["model"] for k in shut) + ". When "
            "their message asks for something only one of them can do (a file, a folder, a command, a program's "
            "window), call this: they get a card to switch it on, and once they do, its tools come in this same "
            "turn and you carry on. Never say it is done, or that you cannot, without calling this first."),
        "parameters": {"type": "object", "properties": {
            "feature": {"type": "string", "enum": list(shut)},
            "why": {"type": "string", "description": "what they asked that needs it, in a few words"},
            **({"folder": {"type": "string", "description": "for computer: the folder their message names "
                                                            "(downloads, documents, desktop, or a full path); the "
                                                            "same card grants it"}} if "computer" in shut else {})},
            "required": ["feature"]}}}


def card_of(feature: str) -> dict:
    who = _who()
    from .desk.grants import SWITCH
    lines = {lang: SWITCH[lang]["sentence"].format(who=who) for lang in ("zh", "en")}
    return {"type": "turn_on", "feature": feature,
            "zh": {"title": f"开启「{FEATURES[feature]['zh']}」？", "lines": [lines["zh"]],
                   "yes": "开启", "no": "暂不开启", "on": "已开启", "off": "未开启"},
            "en": {"title": f"Turn on {FEATURES[feature]['en']}?", "lines": [lines["en"]],
                   "yes": "Turn on", "no": "Not now", "on": "Turned on", "off": "Left off"}}


def switch(home: Path, feature: str) -> None:
    """The same as the switch in Settings."""
    from .desk.grants import Grants as DeskGrants
    DeskGrants(Path(home) / "runtime" / "desktop").set_on(True)


# ------------------------------------------------------------ the page's side

def mount(app, workspace, body) -> None:
    from .panels.runtime import WINDOW_HEADER
    cards = Card(workspace, lambda: getattr(app.state, "window", None))
    home = Path(workspace.home)

    @app.post("/api/turnon/ask")
    async def turnon_ask(request: Request):
        """From the character's turn: the card for one ability, and the press. Waits for it."""
        payload = await body(request)
        feature, conversation = payload.get("feature"), payload.get("conversation")
        if feature not in FEATURES or not isinstance(conversation, str):
            return JSONResponse({"error": "generic"}, status_code=400)
        if feature not in await asyncio.to_thread(off, home):
            return {"status": "on"}
        card = card_of(feature)
        yes = await cards.ask(card, conversation, {lang: card[lang]["title"] for lang in ("zh", "en")})
        if yes:
            await asyncio.to_thread(switch, home, feature)
        return {"status": "on" if yes else "declined" if yes is False else "unanswered"}

    @app.get("/api/turnon/card")
    async def turnon_card():
        return {"card": cards.card}

    @app.post("/api/turnon/card")
    async def turnon_press(request: Request):
        """The person's press: from the app's own page on this computer alone."""
        window = getattr(app.state, "window", None)
        if window is not None and not window.is_own_page(request.headers.get(WINDOW_HEADER, "")):
            return JSONResponse({"error": "local_only"}, status_code=403)
        payload = await body(request)
        ident, yes = payload.get("id"), payload.get("yes")
        if not isinstance(ident, str) or not isinstance(yes, bool):
            return JSONResponse({"error": "generic"}, status_code=400)
        return {"ok": cards.press(ident, yes)}


# ----------------------------------------------------------- the agent's side

_SAID = {
    "on": "On now: its tools are offered from your next call. Carry on with what they asked.",
    "declined": "They chose not to turn it on. Nothing was done; tell them it stays off, in a sentence.",
    "unanswered": "The card waited with no answer. Nothing was done; say it needs their press to switch it on.",
}
_WAITING = {"zh": "等待你确认是否开启", "en": "Asking whether to turn it on"}


async def use(agent, args: dict, lookups) -> str:
    from . import today
    from .browsed import _ask
    feature = args.get("feature")
    if feature not in FEATURES:
        return f"(feature is one of: {', '.join(FEATURES)})"
    home = today.runtime_of(agent).parent
    lang = "zh" if str(getattr(agent, "chat_lang", "") or "zh").startswith("zh") else "en"
    # Commands and files turn on with the folder named, on the shell's own card (shell/panel.py enable).
    computer = feature == "computer"
    lookups.doing("shell" if computer else NAME, _WAITING[lang])
    # Waiting on their press is not the turn's model time.
    lookups.away_since = time.monotonic()
    try:
        outcome = await asyncio.to_thread(_ask, home, "POST", "/api/shell/enable" if computer else "/api/turnon/ask",
                                          WAIT_S + 30, json={"feature": feature, "folder": str(args.get("folder") or ""),
                                                             "conversation": lookups.conversation})
    finally:
        lookups.away_s, lookups.away_since = lookups.away(), None
    status = outcome.get("status") or "unanswered"
    named = FEATURES[feature][lang]
    lookups.trace.append({"tool": NAME, "status": status, "what": (
        (f"已开启「{named}」" if status == "on" else f"未开启「{named}」") if lang == "zh"
        else (f"Turned on {named}" if status == "on" else f"{named} left off"))})
    return _SAID[status]
