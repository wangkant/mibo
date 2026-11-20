"""Hiding during games and fullscreen (see `quiet`): its setting, on unless
the person turned it off, and what the sensing sees now, for the page.
The lifespan starts `quiet.watch(workspace._runtime)` with its other tasks.
"""
from __future__ import annotations

import asyncio

from fastapi import Request

from .. import quiet

ERRORS: frozenset[str] = frozenset({"quiet_invalid"})


def mount(app, workspace, body) -> None:
    @app.get("/api/quiet")
    async def quiet_state():
        return quiet.state()

    @app.get("/api/quiet/settings")
    async def quiet_settings():
        return await asyncio.to_thread(quiet.settings, workspace._runtime())

    @app.post("/api/quiet/settings")
    async def quiet_save(request: Request):
        on = (await body(request)).get("on")
        if not isinstance(on, bool):
            raise ValueError("quiet_invalid")
        return await asyncio.to_thread(quiet.save_settings, workspace._runtime(), on)
