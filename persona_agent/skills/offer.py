"""A skill from the market offered in the chat, before the reply, when the person's message plainly fits one they do
not have (market.offer_for decides in code, with a high bar).

The offer is the chat's asking card: the skill's name, what it does in one line, 安装 / 不安装. The reply runs in
the agent's process and the card in the page's, as with commands: `offer` asks the page (/api/skills/offer/ask),
which shows the card, waits for a press on the app's own page, and on 安装 installs the skill (market.install, every
check of the market included). The turn then goes on with it in the prompt; no press, a refusal or a failed install
go on without it. A conversation gets one offer at most, unless the person asks for a skill.
"""
from __future__ import annotations

import asyncio
import logging
import secrets
import time
from pathlib import Path

from . import market

logger = logging.getLogger("personagent.skills")

# How long the card waits for a press; how soon the page must have looked at it; how long an install may take.
CARD_S = 150.0
WATCHED_S = 10.0
INSTALL_S = 180.0
_WAITING = {"zh": "确认是否安装技能", "en": "Asking whether to install a skill"}


# ------------------------------------------------------------ the page's side

class _Card:
    def __init__(self, card: dict) -> None:
        loop = asyncio.get_running_loop()
        self.card = {**card, "id": secrets.token_urlsafe(10)}
        self.answer, self.outcome = loop.create_future(), loop.create_future()
        self.looked = loop.time()


_shown: dict[str, _Card] = {}


def card_of(one: dict) -> dict:
    return {"type": "skill_offer", "entry": one["id"], "name": one["name"], "title": one["title"],
            "about": one["about"], "publisher": one["publisher"], "scripts": one["needs"]["scripts"],
            "risk": one["scan"]["risk"]}


def card(home: Path) -> dict | None:
    """The card waiting in this home, as the page asks for it; asking is how the app knows the page watches."""
    shown = _shown.get(str(home))
    if shown is None:
        return None
    shown.looked = asyncio.get_running_loop().time()
    return shown.card


async def press(home: Path, ident: str, yes: bool) -> dict:
    """The person's press; with yes, waits for the install and says how it went."""
    shown = _shown.get(str(home))
    if shown is None or shown.card["id"] != ident or shown.answer.done():
        return {"ok": False}
    shown.answer.set_result(yes)
    if not yes:
        return {"ok": True}
    try:
        return {"ok": True, **await asyncio.wait_for(asyncio.shield(shown.outcome), INSTALL_S)}
    except asyncio.TimeoutError:
        return {"ok": True, "installed": False, "error": "market_fetch_failed"}


async def ask(home: Path, ident: str) -> dict:
    """Shows the card for the entry and waits: {"installed": True, "name"} after a press on 安装 and an install,
    else {"installed": False} with the error when the install failed."""
    one = await asyncio.to_thread(market.by_id, home, ident)
    if one is None or market.can_install(one, False) or one["fit"] != "ready":
        return {"installed": False, "error": "market_not_installable"}
    shown = _Card(card_of(one))
    _shown[str(home)] = shown
    loop = asyncio.get_running_loop()
    try:
        began = loop.time()
        while loop.time() - began < CARD_S and loop.time() - shown.looked <= WATCHED_S:
            done, _ = await asyncio.wait({shown.answer}, timeout=0.5)
            if done:
                break
        if not shown.answer.done() or not shown.answer.result():
            logger.info("[Skills] %s offered, not installed", ident)
            return {"installed": False}
        try:
            name = await market.install(home, ident)
        except ValueError as e:
            shown.outcome.set_result({"installed": False, "error": str(e)})
            return {"installed": False, "error": str(e)}
        shown.outcome.set_result({"installed": True})
        return {"installed": True, "name": name}
    finally:
        if not shown.outcome.done():
            shown.outcome.set_result({"installed": False, "error": "skill_gone"})
        if _shown.get(str(home)) is shown:
            del _shown[str(home)]


# ----------------------------------------------------------- the agent's side

async def offer(agent, said: str, lookups) -> None:
    """Before the reply in the person's own chat in the app: offers the market skill the message plainly fits and,
    when they press 安装 and it installs, names it for this turn (lookups.skills_offered)."""
    from ..browsed import _ask
    from ..textproc import _WEB_DESC_SPAN
    from ..turns import turn_choices
    from .tool import _home
    lookups.skills_offered = ""
    # Only the person's own words: not a quoted reply or a shared page's description inside the message.
    said = _WEB_DESC_SPAN.sub("\n", said or "")
    conversation = lookups.conversation
    if lookups.path is None or not conversation or not said.strip():
        return
    if turn_choices() & {"page", "page_on"}:
        # Typed beside the page in the app's browser: it is done in that page, and the chat is not in view.
        return
    offered = vars(agent).setdefault("_skills_offered", set())
    if conversation in offered and not market.asked_for(said):
        return
    home = _home(agent)
    one = await asyncio.to_thread(market.offer_for, home, said)
    if one is None:
        return
    offered.add(conversation)
    lang = "zh" if str(getattr(agent, "agent_lang", "") or "").startswith("zh") else "en"
    lookups.doing("skill_offer", _WAITING[lang])
    lookups.away_since = time.monotonic()
    try:
        outcome = await asyncio.to_thread(_ask, home, "POST", "/api/skills/offer/ask", CARD_S + INSTALL_S + 30,
                                          json={"id": one["id"]})
    finally:
        lookups.away_s, lookups.away_since = lookups.away(), None
    if outcome.get("installed"):
        lookups.skills_offered = str(outcome.get("name") or "")
