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

from . import ask
from .capture import Refused

logger = logging.getLogger("mibo.see")

CALLS_MAX = 16
ACTIONS_MAX = 30
STUCK_AFTER = 3
BAD_AFTER = 3
HISTORY_SHOWN = 6


async def run(ask_model: Callable[[str, list[dict]], Awaitable[str]], sight, task: str, *,
              on_step: Callable[[str], None] = lambda note: None, calls_max: int = CALLS_MAX) -> dict:
    """Do `task` by sight. Returns {"status", "result", "steps", "calls", "actions"}: status done, unchanged,
    failed, asked, declined, refused, handover, cap, or why the person held it."""
    prof = sight.profile
    steps: list[str] = []
    calls = actions = stuck = bad = 0
    changed = checked = False

    def finish(status: str, result: str = "") -> dict:
        return {"status": status, "result": result, "steps": steps, "calls": calls, "actions": actions}

    while True:
        why = sight.held()
        if why:
            return finish(why, "held by the person")
        try:
            frame = await sight.look()
        except Refused as e:
            return finish("handover", str(e))
        if calls >= calls_max or actions >= ACTIONS_MAX:
            return finish("cap", f"stopped after {calls} model calls")
        content = ask.prompt(task, steps[-HISTORY_SHOWN:], frame, prof, sight.surface.name)
        calls += 1
        answer = await ask_model(ask.RULES, [{"role": "user", "content": content}])
        note, planned, error = ask.read(answer, frame, prof)
        if error:
            bad += 1
            steps.append(f"[failed] your answer was refused ({error}); nothing was done")
            if bad >= BAD_AFTER:
                return finish("handover", "three answers in a row were not usable")
            continue
        bad = 0
        if note:
            on_step(note)
        acted = False
        for a in planned:
            if a["do"] == "done":
                if acted:
                    steps.append("[look] done is taken only in a reply after the picture that shows it, not in the "
                                 "reply that acted: check this picture, then say done again")
                    break
                if a["success"] and not changed:
                    if checked:
                        return finish("unchanged", a["result"])
                    checked = True
                    steps.append("[check] nothing you did has changed the window yet, so the task is not done by "
                                 "anything here. Act, or, if the task only asks what the window shows, say done "
                                 "again with what it shows")
                    break
                return finish("done" if a["success"] else "failed", a["result"])
            if a["do"] == "ask_person":
                return finish("asked", a["question"])
            if prof.zoom == "ctx" and a.get("at") and "mark" not in a and a["do"] in ("click", "double_click", "type"):
                second, back = ask.zoom(frame, a["at"], a["target"])
                calls += 1
                point = ask.read_zoom(await ask_model("You point at things in pictures.",
                                                      [{"role": "user", "content": second}]), back)
                if point is not None:
                    a["at"] = point
            actions += 1
            acted = True
            result = await sight.act(a)
            line = result["line"]
            steps.append(line)
            logger.info("[Agent] see %s", line[:300])
            if result["status"] not in ("ok", "failed"):
                return finish(result["status"], line)
            changed = changed or bool(result.get("changed"))
            stuck = stuck + 1 if result["status"] == "ok" and not result.get("changed") and a["do"] != "wait" else 0
            if stuck >= STUCK_AFTER:
                return finish("handover", "nothing changed three times running")
            # After a drag, a scroll or typing the picture has moved: the other planned points may be wrong now.
            if result["status"] != "ok" or a["do"] in ("drag", "scroll", "type"):
                break
