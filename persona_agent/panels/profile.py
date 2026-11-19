"""The profile panel: what the character knows of its owner, for the owner to read and edit.

`GET /api/profile` is the texts, the source leans, the walk words, the pinned
lines and the hard rules, the sources a lean may name, and the character's
model calls per month. `POST /api/profile` takes the owner's edits; a changed
text asks for a rewrite at once, so a "not this" becomes a rule. `POST
/api/profile/answer` is the first run's free-text answer, rewritten at once.
"""
from __future__ import annotations

import asyncio

from fastapi import Request

from .. import langs, profile

ERRORS: frozenset[str] = frozenset({"profile_invalid"})


class Profile:
    def __init__(self, workspace):
        self.ws = workspace

    def view(self) -> dict:
        runtime = self.ws._runtime()
        zh = 1 if langs.normalize(self.ws.config().get("AGENT_LANG")) in ("zh", "zh-TW") else 0
        return {**profile.load(runtime),
                "sources": [{"key": s.key, "name": s.name[zh], "about": s.about[zh]}
                            for s in profile.readable_sources(runtime).values()],
                "calls": profile.calls(runtime)}

    async def edit(self, payload: dict) -> dict:
        if not isinstance(payload, dict):
            raise ValueError("profile_invalid")
        changed = await asyncio.to_thread(profile.edit, self.ws._runtime(), payload)
        rewritten = changed and await profile.rewrite(self.ws._runtime(), self.ws.home)
        return {**await asyncio.to_thread(self.view), "rewritten": rewritten}

    async def answer(self, payload: dict) -> dict:
        rewritten = await profile.answer(self.ws._runtime(), self.ws.home, (payload or {}).get("text"))
        return {**await asyncio.to_thread(self.view), "rewritten": rewritten}


def mount(app, workspace, body) -> None:
    panel = Profile(workspace)

    @app.get("/api/profile")
    async def profile_view():
        return await asyncio.to_thread(panel.view)

    @app.post("/api/profile")
    async def profile_edit(request: Request):
        return await panel.edit(await body(request))

    @app.post("/api/profile/answer")
    async def profile_answer(request: Request):
        return await panel.answer(await body(request))
