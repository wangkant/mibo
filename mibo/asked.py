"""The words of a question a step waits on (cardwait.py), as the chat shows it: one or two plain sentences in the
app's own reading of the step (what, where, how much), never the model's text, ending in a question; the step's
facts a fold shows beside them, as data; and for a step asked on a card (cardwait.ALONE) its decisive facts in the
sentence and the two buttons' words, built from the step's facts.

The words come from the gate's own card: the per-language title and lines of commands, files, folders, turning
acting on and settings (shell/words.py, turnon.py, appmap.py), the act of a page (panels/browser.py act_of), the
sentence of a window worked by sight (see/words.py), and the locale's "ask" words for programs and MCP servers.
Kinds whose words exist in Chinese and English alone are asked in Chinese for zh and zh-TW and in English
otherwise, as their cards were."""
from __future__ import annotations

import re

from . import i18n

# What a fold may show beside the question: the step's own facts as the gate read them. The sentence names a few
# of them too (a page's recipient, button and amount, a window's program, a server's tool, a command's folder),
# clipped short and set into the app's own words; everything longer stays here, as data.
DETAIL = ("lines", "review", "skill", "command", "cwd", "diff", "folder", "program", "window", "target", "text",
          "files", "server", "tool", "args", "raw", "env", "url", "host", "site", "to", "button", "amount", "message",
          "picture", "changed", "hard", "destructive")
# An amount a page shows beside a payment, as the question and the pay button may name it: a number with its
# currency symbol or code and nothing else.
_AMOUNT = re.compile(r"(?:[¥$€£₩₽₹]\s?|[A-Z]{3}\s?)?\d[\d.,' ]{0,15}(?:\s?(?:元|円|원|[¥$€£₩₽₹]|[A-Z]{3}))?")
_CLOSE = ("zh", "zh-TW", "ja")
# A command's costly delete by what it takes (shell/panel.py `removes`): its own sentence; else the plain one.
FROM_FILES = {"delete": "binFull", "replace": "replace", None: "delete"}


def _two(lang: str) -> str:
    return "zh" if lang.startswith("zh") else "en"


def _join(lang: str, *parts: str) -> str:
    return ("" if lang in _CLOSE else " ").join(p for p in parts if p)


def _sentence(what: str, lang: str, where: str = "") -> str:
    """`what` asked: in its place when one is named, ending in a question."""
    if where:
        what = i18n.t("ask.in", lang, what=what, where=where)
    what = what.strip()
    if what.endswith(("?", "？")):
        return what
    return _join(lang, what.rstrip("。.") + ("。" if lang in _CLOSE else "."), i18n.t("ask.goOn", lang))


def _said(card: dict, kind: str, lang: str) -> tuple[str, str, dict]:
    """(the language asked in, the sentence, facts the fold shows that the card keeps per language)."""
    if kind in ("command", "folder", "turn_on", "setting"):
        code = lang if lang in card else _two(lang)
        own = card[code]
        where = card["where"][code] if kind == "command" else ""
        return code, _sentence(own["title"], code, where), {"lines": own.get("lines") or [],
                                                             "review": own.get("review") or ""}
    if kind == "desk_action" or kind == "see_action":
        named = i18n.words("ask", lang)["deskKinds"].get(card.get("kind")) or str(card.get("kind") or "")
        return lang, i18n.t("ask.desk", lang, program=card.get("program") or card.get("window") or "",
                            kind=named), {}
    if kind in ("see_key", "see_lease", "see_grant"):
        # The window's sentence, written in the task's language by see/words.py.
        return lang, _sentence(card.get("said") or card["text"], lang), {}
    if kind == "mcp_tool":
        return lang, _sentence(i18n.t("ask.mcpTool", lang, tool=card.get("title") or card["tool"]), lang,
                               card["server"]), {}
    if kind == "mcp_start":
        return lang, _sentence(i18n.t("ask.mcpStart", lang, server=card["server"]), lang), {}
    if kind == "mcp_ask":
        return lang, _sentence(i18n.t("ask.mcpLink", lang, server=card["server"]), lang, card.get("host") or ""), {}
    from .panels.browser import act_of
    code = _two(lang)
    return code, _sentence(act_of(card, code), code, str(card.get("site") or "")), {}


def amount_of(card: dict) -> str:
    """The amount a page shows beside a payment when it reads as one, else ""."""
    amount = " ".join(str(card.get("amount") or "").split())
    return amount if _AMOUNT.fullmatch(amount) else ""


def _act(card: dict, risk: str, lang: str) -> str:
    """The yes button's words for a costly step, named by what it does."""
    if risk == "order" and amount_of(card):
        return i18n.t("ask.acts.orderAmount", lang, amount=amount_of(card))
    if risk == "delete" and card.get("removes") == "replace":
        return i18n.t("ask.acts.replace", lang)
    if risk == "delete" and card.get("count"):
        return i18n.t("ask.acts.deleteCount", lang, count=card["count"])
    return i18n.t(f"ask.acts.{risk}", lang)


def question(card: dict, risk: str, lang: str) -> dict:
    """The question for `card` asked as `risk`, in `lang` (the interface's language): {"text", "kind", "tier",
    "detail"}, and "act" and "decline" for a card."""
    from .cardwait import tier
    kind = str(card.get("type") or "page")
    code, text, own = _said(card, kind, lang)
    # A window's sentence is the question itself; any other text is what the step types or sends.
    shown = {"said", "text"} if kind in ("see_lease", "see_grant") else {"said"}
    detail = {k: card[k] for k in DETAIL if card.get(k) and k not in shown} | {k: v for k, v in own.items() if v}
    asked = {"kind": kind, "tier": tier(risk), "detail": detail}
    if asked["tier"] == "card":
        # The decisive facts in the sentence itself: what it cannot give back, before the question. A command's
        # delete is costly when the Recycle Bin cannot hold it, and its overwrite when no checkpoint keeps the file.
        costly = i18n.t(f"ask.costly.{FROM_FILES.get(card.get('removes')) if risk == 'delete' else risk}", code)
        text = _join(code, costly, text)
        asked.update(act=_act(card, risk, code), decline=i18n.t("ask.decline", code))
    return {"text": text, **asked}
