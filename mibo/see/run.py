"""The loop of one task by sight, which either loop hands a window or a page to.

Like web/operate.run and desk/operate.run: one model call a look, the latest
picture only, one-line results of the steps before, caps on calls and
actions, and the stop rules (held by the person, a no on a card, nothing
changing three times running). For a weak pointer whose profile says so, a
click gets a second look at a crop beside the whole picture before it is sent.

A picture is no proof by itself, so "done" is taken only on a change seen: in
a reply after the picture that followed the last action, and once an action
has changed the picture. A done before anything changed is asked again once;
said again, the run ends "unchanged", with what the model read kept as its
result (a question about what the window shows ends so, and a task that
needed an action is not called done).
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from . import ask
from .capture import Refused

logger = logging.getLogger("mibo.see")

CALLS_MAX = 16
ACTIONS_MAX = 30
STUCK_AFTER = 3
BAD_AFTER = 3
HISTORY_SHOWN = 6

AskModel = Callable[[str, list[dict]], Awaitable[str]]


@dataclass
class _Tally:
    """One run so far: the one-line results of its steps, what it spent, and the counts its stop rules go by."""
    steps: list[str] = field(default_factory=list)
    calls: int = 0
    actions: int = 0
    stuck: int = 0
    bad: int = 0
    changed: bool = False
    checked: bool = False

    def finish(self, status: str, result: str = "") -> dict:
        return {"status": status, "result": result, "steps": self.steps, "calls": self.calls, "actions": self.actions}


async def run(ask_model: AskModel, sight, task: str, *,
              on_step: Callable[[str], None] = lambda note: None, calls_max: int = CALLS_MAX) -> dict:
    """Do `task` by sight. Returns {"status", "result", "steps", "calls", "actions"}: status done, unchanged,
    failed, asked, declined, refused, handover, cap, or why the person held it."""
    prof = sight.profile
    tally = _Tally()
    while True:
        why = sight.held()
        if why:
            return tally.finish(why, "held by the person")
        try:
            frame = await sight.look()
        except Refused as e:
            return tally.finish("handover", str(e))
        if tally.calls >= calls_max or tally.actions >= ACTIONS_MAX:
            return tally.finish("cap", f"stopped after {tally.calls} model calls")
        content = ask.prompt(task, tally.steps[-HISTORY_SHOWN:], frame, prof, sight.surface.name)
        tally.calls += 1
        answer = await ask_model(ask.RULES, [{"role": "user", "content": content}])
        note, planned, error = ask.read(answer, frame, prof)
        if error:
            tally.bad += 1
            tally.steps.append(f"[failed] your answer was refused ({error}); nothing was done")
            if tally.bad >= BAD_AFTER:
                return tally.finish("handover", "three answers in a row were not usable")
            continue
        tally.bad = 0
        if note:
            on_step(note)
        ended = await _carry_out(ask_model, sight, frame, planned, tally)
        if ended is not None:
            return ended


async def _carry_out(ask_model: AskModel, sight, frame, planned: list[dict], tally: _Tally) -> dict | None:
    """The actions of one reply in order: the run's result when one ends it, or None to look again."""
    acted = False
    for a in planned:
        if a["do"] == "done":
            return _done(a, acted, tally)
        if a["do"] == "ask_person":
            return tally.finish("asked", a["question"])
        if (sight.profile.zoom == "ctx" and a.get("at") and "mark" not in a
                and a["do"] in ("click", "double_click", "type")):
            tally.calls += 1
            await _second_look(ask_model, frame, a)
        tally.actions += 1
        acted = True
        result = await sight.act(a)
        line = result["line"]
        tally.steps.append(line)
        logger.info("[Agent] see %s", line[:300])
        if result["status"] not in ("ok", "failed"):
            return tally.finish(result["status"], line)
        tally.changed = tally.changed or bool(result.get("changed"))
        unchanged = result["status"] == "ok" and not result.get("changed") and a["do"] != "wait"
        tally.stuck = tally.stuck + 1 if unchanged else 0
        if tally.stuck >= STUCK_AFTER:
            return tally.finish("handover", "nothing changed three times running")
        # After a drag, a scroll or typing the picture has moved: the other planned points may be wrong now.
        if result["status"] != "ok" or a["do"] in ("drag", "scroll", "type"):
            return None
    return None


def _done(a: dict, acted: bool, tally: _Tally) -> dict | None:
    """A done: the run's result, or None with a step saying why it is not taken yet."""
    if acted:
        tally.steps.append("[look] done is taken only in a reply after the picture that shows it, not in the "
                           "reply that acted: check this picture, then say done again")
        return None
    if a["success"] and not tally.changed:
        if tally.checked:
            return tally.finish("unchanged", a["result"])
        tally.checked = True
        tally.steps.append("[check] nothing you did has changed the window yet, so the task is not done by "
                           "anything here. Act, or, if the task only asks what the window shows, say done "
                           "again with what it shows")
        return None
    return tally.finish("done" if a["success"] else "failed", a["result"])


async def _second_look(ask_model: AskModel, frame, a: dict) -> None:
    """A weak pointer's second look at a crop round its point, beside the whole picture: the point moves to
    where that look says, unless it gave none."""
    second, back = ask.zoom(frame, a["at"], a["target"])
    point = ask.read_zoom(await ask_model("You point at things in pictures.",
                                          [{"role": "user", "content": second}]), back)
    if point is not None:
        a["at"] = point
