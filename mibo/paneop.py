"""The character operating the page in the pane (web/operate.py drives it, through browser.Pane): DevTools calls and
events of the page, the column beside the page that lists the run's steps (browse.js), and the watch on the
person's own input in the pane, which pauses the run (Esc stops it). The run's own clicks go through DevTools, not
Windows, so they never count as the person's."""
from __future__ import annotations

import contextlib
import ctypes
import json
import re
import time
from collections.abc import Callable
from urllib.parse import urlsplit

from . import browsed
from .panereading import last_input_tick
from .webview2 import CDP_S, call_devtools

# While the character operates, how often the person's own input in the pane is looked for, and how long a page may
# take to come up for it.
WATCH_MS = 250
OPEN_WITHIN_S = 20.0
VK_ESCAPE = 0x1B
# The pointer's buttons (left, right, middle, the two side buttons) among the virtual keys.
POINTER_BUTTONS = {0x01, 0x02, 0x04, 0x05, 0x06}
# Shift, Ctrl, Alt (either side), the Windows keys, Caps Lock and Num Lock: they type nothing alone.
QUIET_KEYS = {0x10, 0x11, 0x12, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0x5B, 0x5C, 0x14, 0x90}
# The steps of a run the column beside the page lists (browse.js), the ends after which the page is the person's
# until they say to go on, and for how long a run going on from one of those keeps its steps.
STEPS_KEPT = 40
THEIRS = ("handover", "asked", "paused", "cap", "waiting")
GO_ON_S = 30 * 60.0
# What the column is told of a run.
SHOWN = ("task", "step", "note", "held", "end", "why", "steps", "card", "wait")


def _keys_down() -> set[int]:
    """The virtual keys and pointer buttons down now or pressed since the last read (GetAsyncKeyState, which clears
    "pressed since" as it is read), less the keys that type nothing alone."""
    keys = ctypes.windll.user32.GetAsyncKeyState
    return {k for k in range(0x01, 0xFF) if keys(k) & 0x8001} - QUIET_KEYS


def handed(status: str, note: str) -> str:
    """Why a run handed the page to the person, for the column to say what they should do: "secret:<field>",
    a wall's kind (verification, sign_in, ...), "drawn" or "stuck"; "" for any other end."""
    if status != "handover":
        return ""
    secret = re.search(r"needs their own (.+?) first", note)
    if secret:
        return f"secret:{secret.group(1)[:40]}"
    wall = re.search(r"shows a (\w+) wall", note)
    if wall:
        return wall.group(1)
    return "drawn" if "almost nothing to work with" in note or "drawn" in note else "stuck"


def on_page(x: float, y: float, wide: float, high: float, cuts: list, scale: float) -> bool:
    """Whether a point in the pane's own px (from its top left) is on the page: inside the pane and not under a
    part of the app page laid over it (`cuts`, CSS px: the chat beside the page with its cards, the bar's
    suggestions), which is cut out of the pane and pressed there, not on the page."""
    if not (0 <= x < wide and 0 <= y < high):
        return False
    return not any(cx * scale <= x < (cx + cw) * scale and cy * scale <= y < (cy + ch) * scale
                   for cx, cy, cw, ch in cuts)


def cuts_at(tick: int, before: list, now: list) -> list:
    """The cuts that stood at input tick `tick` (GetTickCount's, which wraps): the first of `before` (each the
    cuts with the tick they ended at) that ended after it, else the ones standing `now`."""
    return next((was for ended, was in before if ended != tick and (ended - tick) & 0xFFFFFFFF < 0x80000000), now)


def went_to_page(pressed: bool, at_page: bool, typed: bool, focus_in_page: bool) -> bool:
    """Whether the person's input went to the page in the pane: a pointer press goes where the pointer is (a press
    on the chat, a card or the bar laid over the page is on the app's own page, whatever holds the focus), keys go
    where the keyboard focus is."""
    if pressed:
        return at_page
    return typed and focus_in_page


class OperatedPane:
    """The part of browser.Pane the character operates through: its public calls come from a thread other than the
    form's, the input watch runs on the form's. The run under way is `op`: the task, the step it is on, why it must
    stop ("stopped", "paused" when the person moved in the pane), and the column's steps; `_op_last` is the run that
    ended last."""

    def cdp(self, method: str, params: dict | None = None, timeout: float = CDP_S, session: str = "",
            tab: int = 0) -> dict:
        """One DevTools protocol call in the page open now (with `tab`, in that tab's), or with `session` in one of
        its frames; a page at rest wakes for it (browser.Pane.in_use)."""
        return call_devtools(self.ui, lambda: self.in_use(tab), method, params or {}, timeout, session)

    def listen(self, name: str, handler: Callable[..., None], session: bool = False, tab: int = 0) -> None:
        """`handler(params)` on each DevTools event `name` of the page open now (with `tab`, of that tab's); with
        `session`, `handler(params, session)`, the session it came from ("" for the page, else a frame's)."""
        def on(sender, args) -> None:
            with contextlib.suppress(ValueError):
                params = json.loads(str(args.ParameterObjectAsJson))
                if session:
                    handler(params, str(args.SessionId or ""))
                else:
                    handler(params)

        def add() -> None:
            core = self.core_of(tab)
            if core is not None:
                core.GetDevToolsProtocolEventReceiver(name).DevToolsProtocolEventReceived += on
                self._listeners.append(on)
        self.ui(add)

    def address(self, tab: int = 0) -> str:
        found: list = []

        def read() -> None:
            shown = next((t for t in self._tabs if t.id == tab), None) if tab else self._tab
            core = shown.core if shown is not None else None
            found.append(str(core.Source) if core is not None else shown.pending if shown is not None else "")
        self.ui(read)
        return found[0] if found else ""

    def bar_address(self) -> str:
        """The address its bar shows: the page open, or the one on its way while a slow page has not answered."""
        current = self.address()
        return current if browsed.web(current) else (self._reading or {}).get("url", "")

    def ready(self, address: str = "") -> bool:
        """The pane open and in front with a page loaded: on `address` when it is given and the page open is
        on another site, or none is open. False when no page came up in time."""
        current = self.address()
        if address and (not browsed.web(current) or browsed.site_of(urlsplit(address).hostname or "")
                        != browsed.site_of(urlsplit(current).hostname or "")):
            self.open(address)
        elif not browsed.web(current):
            return False
        else:
            self.ui(lambda: (self._quiet(False), self._do("return")))
        began = time.monotonic()
        while time.monotonic() - began < OPEN_WITHIN_S:
            if self._page_up():
                return True
            time.sleep(0.3)
        return False

    def _page_up(self) -> bool:
        """The page in front is a web page whose document can be acted on."""
        if self._core is None or not browsed.web(self.address()):
            return False
        with contextlib.suppress(RuntimeError):
            state = self.cdp("Runtime.evaluate", {"expression": "document.readyState", "returnByValue": True},
                             timeout=5)
            return (state.get("result") or {}).get("value") in ("interactive", "complete")
        return False

    def operate(self, task: str, go_on: bool = False) -> None:
        """A run begins: the column beside the page shows it, and the person's moves in the pane pause it. Going
        on from a run that left the page to the person, the column keeps what was asked and the steps so far."""
        last = self._op_last
        if not (go_on and last and last["end"] in THEIRS and time.monotonic() - last["at"] < GO_ON_S):
            last = None
        self.op = {"task": last["task"] if last else task[:200], "step": 0, "note": "", "held": "", "end": "",
                   "why": "", "steps": last["steps"] if last else [], "card": None}
        with contextlib.suppress(RuntimeError):
            self.cdp("Page.enable")
        self.ui(self._watch_input)
        self.ui(self._hush)
        self._tell_op()

    def op_step(self, n: int, note: str) -> None:
        if self.op is not None:
            self.op.update(step=n, note=note[:120])
            self._tell_op()

    def op_said(self, text: str) -> None:
        """The step about to happen, in the person's words: the one before it is done. The same step again
        (another scroll) counts up instead of making a new line."""
        op = self.op
        if op is None or not text:
            return
        steps = op["steps"]
        last = steps[-1] if steps else None
        if last and last["state"] == "doing":
            last["state"] = "done"
        if (last and last["state"] == "done" and last["text"] == text[:120] and not last.get("why")
                and last.get("note", "") == op["note"]):
            last.update(state="doing", n=last.get("n", 1) + 1)
        else:
            # With what the step is for (the loop's note, op_step), which the column shows over it.
            steps.append({"text": text[:120], "state": "doing", **({"note": op["note"]} if op["note"] else {})})
            del steps[:-STEPS_KEPT]
        self._tell_op()

    def op_result(self, state: str, why: str = "") -> None:
        """How the step under way came out: "done", or "failed" with why in the person's words."""
        op = self.op
        if op is None or not op["steps"] or op["steps"][-1]["state"] != "doing":
            return
        op["steps"][-1].update(state=state, **({"why": why} if why else {}))
        self._tell_op()

    def op_card(self, card: dict, text: str) -> None:
        """A card waits on the person's press, beside the page: the column shows it, and `text` as the step."""
        op = self.op
        if op is None:
            return
        if op["steps"] and op["steps"][-1]["state"] == "doing":
            op["steps"][-1]["state"] = "done"
        op["steps"].append({"text": text[:160], "state": "waiting", "card": True,
                            **({"note": op["note"]} if op["note"] else {})})
        op["card"] = card
        self._tell_op()

    def op_answered(self, state: str, text: str) -> None:
        """The card is answered (or gone unanswered): its step says how, and the card goes."""
        op = self.op
        if op is None:
            return
        for step in reversed(op["steps"]):
            if step["state"] == "waiting":
                step.update(state=state, text=text[:160])
                break
        op["card"] = None
        self._tell_op()

    def op_end(self, status: str, note: str, unfinished: str = "") -> None:
        """The run ended: the column says how, and stays until the person closes it. A step it never finished
        says `unfinished`; ended waiting on a card, the card and its step stay, to be answered."""
        op = self.op
        if op is None:
            return
        self.ui(self._unwatch_input)
        waiting = status == "waiting" and op["card"] is not None
        for step in op["steps"]:
            if step["state"] == "doing" or (step["state"] == "waiting" and not waiting):
                step.update(state="done" if status == "done" else "stopped", why="" if status == "done" else unfinished)
        op.update(end=status, note=note[:300], why=handed(status, note), card=op["card"] if waiting else None)
        self._tell_op()
        self._op_last = {**op, "at": time.monotonic()}
        self.op = None

    def op_kept(self, yes: bool) -> None:
        """The card a run ended waiting on was answered: it goes, and a no ends the run as declined."""
        last = self._op_last
        if self.op is None and last and last["card"] is not None:
            for step in last["steps"]:
                if step["state"] == "waiting":
                    step["state"] = "done" if yes else "cancelled"
            last.update(card=None, **({} if yes else {"end": "declined"}))
            self.tell({"operating": {k: last.get(k) for k in SHOWN}})

    def op_steps(self) -> list:
        """The steps of the run under way, else of the last one."""
        return list((self.op or self._op_last or {}).get("steps") or [])

    def _tell_op(self) -> None:
        op = self.op
        self.tell({"operating": None if op is None else {k: op.get(k) for k in SHOWN}})

    def _take(self, stop: bool) -> None:
        """The bar's 停止 (or Esc) and 我来接手: the run stops at its next step."""
        if self.op is not None:
            self.op["held"] = "stopped" if stop else "paused"
            self._tell_op()

    def _watch_input(self) -> None:
        from System.Windows.Forms import Timer
        self._unwatch_input()
        timer = Timer()
        timer.Interval = WATCH_MS
        self._op_seen = last_input_tick()
        self._op_looked = ctypes.windll.kernel32.GetTickCount()
        # A key pressed before the run (the Enter that sent the request) is cleared from "pressed since the last read".
        _keys_down()
        timer.Tick += self._op_tick
        timer.Start()
        self._op_timer = timer

    def _unwatch_input(self) -> None:
        if self._op_timer is not None:
            self._op_timer.Stop()
            self._op_timer.Dispose()
            self._op_timer = None

    def _input_tick(self) -> None:
        """The person's own click or key on the page in the pane (a pointer passing over it or its wheel does not
        count, nor a press on the chat or a card laid over it): Esc stops the run, anything else pauses it."""
        from System.Windows.Forms import Cursor
        seen = last_input_tick()
        moved, self._op_seen = seen != self._op_seen, seen
        looked, self._op_looked = self._op_looked, ctypes.windll.kernel32.GetTickCount()
        if not moved or self.op is None or self._view is None or self.op.get("held") or not self._view.Visible:
            return
        # The keys and buttons down or pressed since the last tick, read once.
        down = _keys_down()
        point = self._view.PointToClient(Cursor.Position)
        # The cuts that stood when the input came, which a press on a card changes: for a press, the ones at the
        # watch's last look (the page may be re-laid and the pointer moved on since the press); for keys, the ones
        # at the newest input (GetLastInputInfo's tick).
        cuts = cuts_at(looked if down & POINTER_BUTTONS else seen, self._cuts_before, self._cuts)
        at_page = on_page(point.X, point.Y, self._view.Width, self._view.Height, [] if self._full else cuts,
                          self._scale)
        if not went_to_page(bool(down & POINTER_BUTTONS), at_page, bool(down - POINTER_BUTTONS),
                            self._view.ContainsFocus):
            return
        # Waiting for their sign-in, the page is theirs to type in: only Esc stops the run.
        if self.op.get("wait") and VK_ESCAPE not in down:
            return
        self.op["held"] = "stopped" if VK_ESCAPE in down else "paused"
        self._tell_op()
