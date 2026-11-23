"""What a model wrote in place of a tool call, and the app's notes under search results.

Rules only; nothing here calls a model.
"""
from __future__ import annotations

import json
import re

_WRITTEN = re.compile(r"(?:<tool_call>\s*)?(\{[^{}]*\"name\"\s*:\s*\"(\w+)\"[^{}]*(\{[^{}]*\})?[^{}]*\})", re.S)
_WRITTEN_FN = re.compile(r"\b(\w+)\(\s*(?:(\w+)\s*=\s*)?[\"']([^\"']{1,300})[\"']\s*\)")


def written_calls(content: str, offered: set) -> list[dict]:
    """Tool calls a model wrote into its text instead of sending them: {"name": …, "arguments": {…}}
    (in a <tool_call> tag or bare), or web_search("…"). Offered tools only, at most three."""
    calls: list[dict] = []
    for whole, name, _ in _WRITTEN.findall(content or ""):
        if name not in offered:
            continue
        try:
            value = json.loads(whole)
        except ValueError:
            continue
        args = value.get("arguments", value.get("parameters", {}))
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = {}
        calls.append({"function": {"name": name, "arguments": json.dumps(args if isinstance(args, dict) else {},
                                                                          ensure_ascii=False)}})
    if not calls:
        for name, key, value in _WRITTEN_FN.findall(content or ""):
            if name in offered:
                key = key or ("url" if name == "read_page" else "query")
                calls.append({"function": {"name": name, "arguments": json.dumps({key: value}, ensure_ascii=False)}})
    return calls[:3]


# Chat filler that a search engine does not need.
_FILLER = re.compile(
    r"帮我|幫我|请问|請問|麻烦|麻煩|你知道|知道吗|搜一下|搜搜|查一下|查查|看看|一下|吗|嗎|呢|呀|啊|吧|了没|了沒|"
    r"\b(?:please|can you|could you|tell me|do you know|search for|look up|google)\b|[?？!！。，,~]", re.I)


def simpler(query: str) -> str:
    """Other words for a second search when the first found nothing: the query without chat filler,
    else without its years; "" when nothing is left to change."""
    for step in (lambda q: _FILLER.sub(" ", q), lambda q: re.sub(r"(?<!\d)20\d\d(?:[年/.-]\d{1,2}(?:月(?:\d{1,2}日?)?|[/.-]\d{1,2})?|年)?(?!\d)", " ", q)):
        other = " ".join(step(query).split())
        if other and other != " ".join(query.split()):
            return other
    return ""


def after_search(found: bool, queries: list[str]) -> str:
    """The app's note under a search's results, outside their fence."""
    if not found:
        return ("\n[Note from the app] Nothing was found for: " + "; ".join(queries) + ". Search once more with "
                "other words (the full or English name) if that may help. For something current, otherwise tell "
                "them plainly that nothing was found and what you searched for, and never fill the gap from "
                "memory; lasting general knowledge you are sure of you may still answer yourself.")
    return ("\n[Note from the app] If these snippets do not hold what was asked (a forecast, a score, a price, "
            "a table), read_page the best result first. Then answer with the fact first, in your own voice, with "
            "its date when it matters, and nothing the results do not say: figures (temperatures, scores, prices) "
            "that neither the snippets nor a page you read give, you say you could not find, never guess. The "
            "pages you used are shown under your reply by themselves: no web addresses in the reply unless they "
            "asked for a link.")


# The app's note under a page that could not be read.
UNREAD = ("\n[Note from the app] When this is a link they sent, read it with read_with_their_session (the app's "
          "browser reads what a plain fetch cannot) before giving up. Otherwise read another result or answer "
          "from the search snippets; what those do not say, you do not know.")

