"""Acting switched off, turned on from inside the call that needs it.

While the one acting mode (acting.py) is off, the tools of commands and files (shell/) and of other programs (desk/)
are still offered (search.py). When the reply model calls one, the call first asks in the chat, in the app's own
words, whether to turn the ability on and what still waits for the person's yes. Their typed yes sets the mode to
automatic review, and the call then runs and answers as it would have; any other message leaves it off and the call
answers with an Error line. Only the person's own message typed in the app's chat box answers it (cardwait.py), and
the question waits only while their own turn is under way.
"""
from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

from fastapi import Request
from fastapi.responses import JSONResponse

from .cardwait import WAIT_S, Card

# What the waiting row and the step under the reply call the question (chat.js shows it on this name).
NAME = "turn_on"
# The abilities whose tools turn acting on, and what the model and the question call each.
FEATURES = {
    "computer": {"model": "Commands and files on this computer", "zh": "文件与命令", "en": "Files and commands"},
    "programs": {"model": "Operating other programs", "zh": "电脑上的程序", "en": "Other programs"},
}


# The switch in Settings (the one acting mode) and the sentence under it.
SWITCH = {
    "zh": {"label": "允许{who}操作电脑上的其他程序",
           "sentence": "开启后，仅当你在对话中提出要求时，{who}才会查看或操作电脑上的程序。发送、发布等操作由自动审查核对"
                       "你的原话后执行；删除、付款和更改账号每次都需要你确认，可随时按 Esc 停止。始终不操作密码管理器、终端、"
                       "系统设置和付款程序。"},
    "en": {"label": "Let {who} operate other programs on this computer",
           "sentence": "When on, {who} looks at or operates programs on this computer only while you ask in chat. "
                       "Sending and posting go ahead once the automatic review finds them in your own words; deleting, "
                       "paying and account changes ask you every time, and Esc stops it. Password managers, terminals, "
                       "system settings and payment programs are never touched."},
}


def _who() -> str:
    return os.getenv("PERSONA_NAME", "").strip() or "Mibo"


def off(home: Path) -> list[str]:
    """The abilities switched off in this home, as FEATURES keys: all of them while the one mode is off."""
    from .acting import Modes
    return list(FEATURES) if Modes(Path(home) / "runtime" / "desktop").mode() == "off" else []


def card_of(feature: str) -> dict:
    who = _who()
    lines = {lang: SWITCH[lang]["sentence"].format(who=who) for lang in ("zh", "en")}
    return {"type": "turn_on", "feature": feature,
            "zh": {"title": f"开启「{FEATURES[feature]['zh']}」？", "lines": [lines["zh"]]},
            "en": {"title": f"Turn on {FEATURES[feature]['en']}?", "lines": [lines["en"]]}}


def switch(home: Path) -> None:
    """The same as the switch in Settings: the one mode set to automatic review."""
    from .acting import Modes
    Modes(Path(home) / "runtime" / "desktop").set("auto")


# ------------------------------------------------------------ the page's side

def mount(app, workspace, body) -> None:
    cards = Card(workspace, lambda: getattr(app.state, "window", None))
    home = Path(workspace.home)

    @app.post("/api/turnon/ask")
    async def turnon_ask(request: Request):
        """From the character's turn: the question for one ability, and the person's answer. Waits for it."""
        payload = await body(request)
        feature, conversation = payload.get("feature"), payload.get("conversation")
        if feature not in FEATURES or not isinstance(conversation, str):
            return JSONResponse({"error": "generic"}, status_code=400)
        if feature not in await asyncio.to_thread(off, home):
            return {"status": "on"}
        card = card_of(feature)
        yes = await cards.ask(card, conversation, {lang: card[lang]["title"] for lang in ("zh", "en")})
        if yes:
            await asyncio.to_thread(switch, home)
        return {"status": "on" if yes else "declined" if yes is False else "unanswered"}

    @app.get("/api/turnon/card")
    async def turnon_card():
        """The gate's reading of the question waiting, if any (said in the chat as the character's message (cardwait.py); /api/confirm answers it)."""
        return {"card": cards.card}


# ----------------------------------------------------------- the agent's side

_SAID = {
    "declined": "Error: {area} is off; they chose to leave it off. Tell them in a sentence.",
    "unanswered": "Error: {area} is off; the question to turn it on got no answer. Tell them it needs their yes.",
}
_WAITING = {"zh": "等待你确认是否开启", "en": "Asking whether to turn it on"}


async def use(agent, feature: str, folder: str, lookups) -> str:
    """The question for `feature` inside the call that needs it: "" once it is on, so the call goes on; else the
    Error line the call answers with. Commands and files turn on with the folder the call names, on the shell's
    own question (shell/panel.py enable)."""
    from . import today
    from .browsed import _ask
    home = today.runtime_of(agent).parent
    lang = "zh" if str(getattr(agent, "chat_lang", "") or "zh").startswith("zh") else "en"
    computer = feature == "computer"
    lookups.doing("shell" if computer else NAME, _WAITING[lang])
    # Waiting on their answer is not the turn's model time.
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
