"""Settings' 显示桌宠 (petoff.py): whether the figure is on the desktop."""
from __future__ import annotations

import asyncio

from fastapi import Request

from .. import petoff

ERRORS: frozenset[str] = frozenset({"pet_unavailable"})


def mount(app, workspace, body) -> None:
    def state() -> dict:
        window = getattr(app.state, "window", None)
        has = window is not None and window.pet
        return {"available": bool(has),
                "shown": petoff.shown(window) if has else True}

    @app.get("/api/pet")
    async def pet_state():
        return await asyncio.to_thread(state)

    @app.post("/api/pet")
    async def pet_save(request: Request):
        shown = (await body(request)).get("shown")
        if not isinstance(shown, bool) or not state()["available"]:
            raise ValueError("pet_unavailable")
        await asyncio.to_thread(petoff.turn, app.state.window, shown)
        return await asyncio.to_thread(state)
