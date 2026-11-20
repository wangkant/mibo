"""Sight across the two processes, as the loops already split their work.

The pane and the granted windows live in the app's process, where the cards
are shown; the model is called from the service. `serve` is the app's side: it
answers the two ops a loop's local API forwards ("see_look", "see_act") from
one `act.Sight` per task. `RemoteSight` is the service's side, with the shape
run.run drives (`look`, `act`, `held`, `profile`, `surface.name`), posting
those ops through the loop's own `_post`.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from types import SimpleNamespace

from . import act, capture
from . import frame as fr
from .profile import Profile


async def serve(sight: act.Sight, op: str, fields: dict) -> dict:
    """The app's side of one op."""
    if op == "see_look":
        try:
            return {"status": "ok", "frame": fr.pack(await sight.look())}
        except capture.Refused as e:
            return {"status": "refused", "line": str(e)}
    if op == "see_act":
        action = dict(fields.get("action") or {})
        for key in ("at", "to"):
            if action.get(key) is not None:
                action[key] = tuple(float(v) for v in action[key])
        return await sight.act(action)
    return {"status": "failed", "line": f"[failed] no op {op!r}"}


class RemoteSight:
    """The service's side. `post(op, timeout, **fields)` is the loop's Remote._post; `prof` is the person's
    model's profile, which decides how pictures are asked. `frame` is the latest picture."""

    def __init__(self, post: Callable[..., dict], prof: Profile, name: str, *, held: Callable[[], str] = lambda: "",
                 card_s: float = 300):
        self.post = post
        self.profile = prof
        self.frame: fr.Frame | None = None
        self.surface = SimpleNamespace(name=name)
        self.held = held
        self.card_s = card_s

    async def look(self) -> fr.Frame:
        answer = await asyncio.to_thread(self.post, "see_look", 60)
        if answer.get("status") != "ok":
            raise capture.Refused(answer.get("line") or "[failed] no picture")
        self.frame = fr.unpack(answer["frame"])
        return self.frame

    async def act(self, action: dict) -> dict:
        return await asyncio.to_thread(self.post, "see_act", self.card_s + 90, action=action)
