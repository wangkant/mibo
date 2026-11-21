"""A switched-off ability, turned on from inside the call that needs it.

While commands and files (shell/) or other programs (desk/) are off, their tools are still offered (search.py). When
the reply model calls one, the call first shows the card: what the ability does and what always waits for a press,
with 开启 / 暂不开启. A press on 开启 is the same as the switch in Settings, and the call then runs and answers as it
would have; on 暂不开启 it answers with an Error line. Only a press on the app's own page answers it, never words
typed in the chat, and the card waits only while the person's own turn is under way (cardwait.py).
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

# What the waiting row and the step under the reply call the card (chat.js shows it on this name).
NAME = "turn_on"
# The abilities that have a switch, and what the model and the card call each.
FEATURES = {
    "computer": {"model": "Commands and files on this computer", "zh": "文件与命令", "en": "Files and commands"},
    "programs": {"model": "Operating other programs", "zh": "电脑上的程序", "en": "Other programs"},
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
    "declined": "Error: {area} is off; they chose to leave it off. Tell them in a sentence.",
    "unanswered": "Error: {area} is off; the card to turn it on got no answer. Tell them it needs their press.",
}
_WAITING = {"zh": "等待你确认是否开启", "en": "Asking whether to turn it on"}


async def use(agent, feature: str, folder: str, lookups) -> str:
    """The card for `feature` inside the call that needs it: "" once it is on, so the call goes on; else the
    Error line the call answers with. Commands and files turn on with the folder the call names, on the shell's
    own card (shell/panel.py enable)."""
    from . import today
    from .browsed import _ask
    home = today.runtime_of(agent).parent
    lang = "zh" if str(getattr(agent, "chat_lang", "") or "zh").startswith("zh") else "en"
    computer = feature == "computer"
    lookups.doing("shell" if computer else NAME, _WAITING[lang])
    # Waiting on their press is not the turn's model time.
    lookups.away_since = time.monotonic()
    try:
        outcome = await asyncio.to_thread(_ask, home, "POST", "/api/shell/enable" if computer else "/api/turnon/ask",
                                          WAIT_S + 30, json={"feature": feature, "folder": folder,
                                                             "conversation": lookups.conversation})
    finally:
        lookups.away_s, lookups.away_since = lookups.away(), None
    status = outcome.get("status") or "unanswered"
    named = FEATURES[feature][lang]
    lookups.trace.append({"tool": NAME, "status": status, "what": (
        (f"已开启「{named}」" if status == "on" else f"未开启「{named}」") if lang == "zh"
        else (f"Turned on {named}" if status == "on" else f"{named} left off"))})
    return "" if status == "on" else _SAID.get(status, _SAID["unanswered"]).format(area=FEATURES[feature]["model"])
