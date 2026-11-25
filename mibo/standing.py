"""The person's standing rules: sentences they typed in the chat for steps that need not ask them from then on
("以后在 D:\\work 里运行脚本不用问我"), each kept as they typed it with the time and the chat it came from. (A
scheduled task's standing request is another thing: its scope is crossing.within's.)

A rule is the person's own words and nothing else. It is added only through the settings tool (appmap.py, the item
privacy/standing), only when its text is a span of the person's own message of the turn under way as they typed it
(crossing.own_words), and after the turn read outside material only on their yes in the chat (crossing.widening):
text from a page, a file, a tool's result or the character's own words never becomes one. Removing one only narrows
what passes, so it needs no question, from Settings › Privacy or from the chat.

Its one effect is on the reviewer (review.py): the rules are given to it beside the person's messages, dated and
marked as standing words, and it may pass a step one covers. Nothing else reads them: costly acts, sensitive sites,
secrets, the refusals and the questions code keeps are decided before any reviewer, as they were. Claude Code's auto
mode, whose classifier reads the person's prose allow rules beside the transcript, is what this follows.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path

from fastapi import Request
from fastapi.responses import JSONResponse

FILE = "standing-rules.json"
# Rules kept at most, and the longest one, in characters.
MOST = 30
LONGEST = 300
_LOCK = threading.Lock()


def _path(workspace) -> Path:
    return Path(workspace.home) / "runtime" / "desktop" / FILE


def rules(workspace) -> list[dict]:
    """The rules kept, oldest first: [{"id", "text", "at", "conversation"}]."""
    try:
        return json.loads(_path(workspace).read_text(encoding="utf-8"))["rules"]
    except OSError:
        return []


def _keep(workspace, kept: list[dict]) -> list[dict]:
    from .storage import atomic_write_text
    atomic_write_text(_path(workspace), json.dumps({"rules": kept}, ensure_ascii=False))
    return kept


def add(workspace, text: str, conversation: str) -> list[dict] | None:
    """`text` kept as a rule from `conversation`; None when MOST are kept already."""
    with _LOCK:
        kept = rules(workspace)
        if len(kept) >= MOST:
            return None
        ident = max((rule["id"] for rule in kept), default=0) + 1
        return _keep(workspace, [*kept, {"id": ident, "text": text, "at": time.time(), "conversation": conversation}])


def remove(workspace, ident: int) -> list[dict] | None:
    """The rules left with rule `ident` removed; None when there is none by that number."""
    with _LOCK:
        kept = rules(workspace)
        left = [rule for rule in kept if rule["id"] != ident]
        return _keep(workspace, left) if len(left) < len(kept) else None


def mount(app, workspace, body) -> None:
    from .cardwait import doing

    @app.get("/api/standing")
    async def standing_list():
        """Settings › Privacy's list, and the settings tool's reading of it."""
        return {"rules": await asyncio.to_thread(rules, workspace)}

    @app.post("/api/standing")
    async def standing_change(request: Request):
        """{"remove": id} from Settings or the settings tool; {"add": text} from the settings tool alone, past its
        gate (appmap.py), kept with the chat of the turn under way. -> {"rules"}."""
        payload = await body(request)
        if isinstance(payload.get("remove"), int):
            left = await asyncio.to_thread(remove, workspace, payload["remove"])
            if left is None:
                return JSONResponse({"error": "no rule by that number"}, status_code=404)
            return {"rules": left}
        text = payload.get("add")
        if not isinstance(text, str) or not 0 < len(text) <= LONGEST:
            return JSONResponse({"error": "generic"}, status_code=400)
        kept = await asyncio.to_thread(add, workspace, text, str(doing(workspace).get("conversation") or ""))
        if kept is None:
            return JSONResponse({"error": f"full: {MOST} rules are kept; one must be removed first"}, status_code=409)
        return {"rules": kept}
