"""The runtime panel: keep running behind the window, the app window's bar, and whether a new release is out."""
from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import Request

from .. import __version__, updates, usage
from ..window import ACTIONS

# Error codes this panel raises as ValueError, which the page may show.
ERRORS: frozenset[str] = frozenset({"background_unavailable", "window_unavailable"})
# The key the app window's own page sends to draw and use the window's bar.
WINDOW_HEADER = "X-Personagent-Window"


def mount(app, workspace, body) -> None:
    from ..welcome import app_settings, pet_figure, save_app_settings

    desktop = workspace.home / "runtime" / "desktop"

    def summary() -> dict:
        window = getattr(app.state, "window", None)
        last = updates._read(workspace.home)
        checked = last.get("checked")
        return {
            "version": __version__,
            "background": bool(app_settings(desktop).get("background")),
            "canHide": bool(window is not None and window.can_hide),
            "update": updates.notice(workspace.home, always=True),
            "checked": checked if isinstance(checked, (int, float)) else None,
            # The last attempt did not reach the release page: "up to date" would be a guess.
            "checkFailed": bool(last.get("failed")),
            "usage": usage.read_summary(usage_file()),
        }

    def usage_file() -> Path:
        # Beside the memory file, where the character keeps its tally.
        memory = Path(str(workspace.config().get("MEMORY_FILE") or "memory.json"))
        memory = memory if memory.is_absolute() else workspace.home / "runtime" / memory
        return memory.with_name(usage.USAGE_FILE)

    @app.get("/api/runtime")
    async def runtime():
        return await asyncio.to_thread(summary)

    @app.post("/api/runtime/background")
    async def background(request: Request):
        on = bool((await body(request)).get("on"))
        window = getattr(app.state, "window", None)
        if on and not (window is not None and window.can_hide):
            raise ValueError("background_unavailable")
        save_app_settings(desktop, background=on)
        return await asyncio.to_thread(summary)

    def own_window(request: Request):
        """The app window, for the page inside it and nobody else: a browser
        tab on the same address draws no window bar and is sent nowhere by the pet."""
        window = getattr(app.state, "window", None)
        if window is None or not window.is_own_page(request.headers.get(WINDOW_HEADER, "")):
            return None
        return window

    def frame(window, goto: str = "") -> dict:
        # Without a title bar of its own the window leaves the bar and its buttons to the page.
        return {"frameless": bool(window is not None and window.frameless),
                "maximized": bool(window is not None and window.maximized),
                # A browser tab draws the figure the pet would be.
                "figure": window.figure() if window is not None else pet_figure(desktop, workspace.config()),
                "goto": goto}

    @app.get("/api/window")
    async def window_frame(request: Request):
        window = own_window(request)
        if window is None:
            return await asyncio.to_thread(frame, None)
        window.frame_seen()
        # Where the pet sent the page goes out once. The figure is read from the settings file.
        return await asyncio.to_thread(frame, window, window.take_goto())

    @app.post("/api/window")
    async def window_control(request: Request):
        action = str((await body(request)).get("action") or "")
        window = own_window(request)
        if window is None or not window.frameless or action not in ACTIONS:
            raise ValueError("window_unavailable")
        if not await asyncio.to_thread(window.control, action):
            raise ValueError("window_unavailable")
        return frame(window)

    @app.post("/api/runtime/check")
    async def check(request: Request):
        await body(request)
        await asyncio.to_thread(updates.check, workspace.home, 10.0)
        return await asyncio.to_thread(summary)
