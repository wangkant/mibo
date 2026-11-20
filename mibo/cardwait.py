"""A card that waits for its person: the one loop behind the cards of commands (shell/panel.py), other programs
(desk/panel.py) and MCP servers (mcp_hub.py).

Presence is the app running with the person's own chat turn under way for that conversation, not the page in
view. As in Claude Code, Codex and OpenCode, a card stays until it is pressed or the turn is stopped, so one raised
while the window is minimised, or while the person is in another program, is still there when they come back. When
the app window is not in front the system notification says so once (window.notify, the path scheduled tasks use),
and the pet's line shows 需要你确认 (petline.js). A card left WAIT_S ends its step unanswered, and the reply offers
继续 (activity.js), which asks again.
"""
from __future__ import annotations

import asyncio
import json
import secrets
from pathlib import Path

# How long a card waits before its step ends unanswered; inside the reply's own limit (welcome.REPLY_WITHIN_S).
WAIT_S = 600.0
TICK_S = 0.5

NOTICE = {"zh": "需要你确认：{what}", "en": "Needs your confirmation: {what}"}


class Card:
    """The one card a place shows at a time: the page reads `card`, a press on the app's own page answers it."""

    def __init__(self, workspace, window=lambda: None) -> None:
        # `window`: the app window when there is one (app.state.window), for the notification.
        self.workspace, self.window = workspace, window
        self.doing = Path(workspace.home) / "runtime" / "desktop" / "chat-doing.json"
        self.card: dict | None = None
        self.answer: asyncio.Future | None = None

    def turn_on(self, conversation: str) -> bool:
        """The person's own chat turn in the app is under way, for this conversation."""
        if not conversation or not self.workspace._chat_lock.locked():
            return False
        try:
            doing = json.loads(self.doing.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        return doing.get("conversation") == conversation

    async def ask(self, card: dict, conversation: str, what: dict, ended=None):
        """Shows `card` and waits: what was pressed, or None when the turn ended, `ended()` says the task did, or
        WAIT_S passed. `what` names it for the notification, {"zh", "en"}."""
        loop = asyncio.get_running_loop()
        self.card, self.answer = {**card, "id": secrets.token_urlsafe(10)}, loop.create_future()
        self._tell(loop, what)
        try:
            began = loop.time()
            while loop.time() - began < WAIT_S and self.turn_on(conversation) and not (ended and ended()):
                done, _ = await asyncio.wait({self.answer}, timeout=TICK_S)
                if done:
                    return self.answer.result()
            return None
        finally:
            self.card = self.answer = None

    def up(self, ident: str) -> bool:
        """The card `ident` is up and not yet answered."""
        return self.card is not None and self.card["id"] == ident and not self.answer.done()

    def press(self, ident: str, answer) -> bool:
        if not self.up(ident):
            return False
        self.answer.set_result(answer)
        return True

    def drop(self) -> None:
        """The task ended: a card still waiting goes unanswered."""
        if self.answer is not None and not self.answer.done():
            self.answer.set_result(None)

    def _tell(self, loop, what: dict) -> None:
        """The system notification, when the app window is not in front (window.notify decides), off the loop."""
        window = self.window()
        if window is None:
            return
        lang = "zh" if str(self.workspace.config().get("AGENT_LANG") or "zh").lower().startswith("zh") else "en"
        loop.run_in_executor(None, window.notify, NOTICE[lang].format(what=what[lang]))
