"""The privacy panel: whether the character may read what the person's mail and
private messages say (privacy.py), and the line it says about them while it may not.

`GET/POST /api/privacy/settings` is the switch, with the model service the
text would go to. The lifespan calls `app.state.privacy.attach()`: a look finds
new mail in a worker thread, and the line is said on the event loop, into the
main chat and, in the window app, by the pet.
"""
from __future__ import annotations

import asyncio

from fastapi import Request

from .. import life, privacy

ERRORS: frozenset[str] = frozenset({"privacy_invalid", "privacy_unsafe", "privacy_no_model"})
# While a reply is under way in the main chat the line waits, this often, at most this many times.
SAY_WAIT_S = 5
SAY_TRIES = 24


class Privacy:
    def __init__(self, app, workspace):
        self.app, self.ws = app, workspace

    def settings(self) -> dict:
        return privacy.settings(self.ws._runtime(), self.ws.config())

    def save(self, payload: dict) -> dict:
        on = payload.get("on")
        if not isinstance(on, bool):
            raise ValueError("privacy_invalid")
        return privacy.save(self.ws._runtime(), self.ws.config(), on)

    def attach(self) -> None:
        """Call on the event loop: lines from the looks' threads are said on it."""
        loop = asyncio.get_running_loop()
        privacy.listen(lambda text: loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self.say(text))))

    async def say(self, text: str) -> None:
        for _ in range(SAY_TRIES):
            if await self.ws.remark(text):
                break
            await asyncio.sleep(SAY_WAIT_S)
        else:
            return
        # The pet takes it as it takes a remark (panels/remarks.py).
        remarks = self.app.state.remarks
        now = life.clock()
        remarks.pending = {"id": f"{int(now * 1000)}", "text": text, "activity": "", "at": int(now)}
        remarks.said()


def mount(app, workspace, body) -> None:
    panel = Privacy(app, workspace)
    app.state.privacy = panel

    @app.get("/api/privacy/settings")
    async def privacy_settings():
        return await asyncio.to_thread(panel.settings)

    @app.post("/api/privacy/settings")
    async def privacy_save(request: Request):
        return await asyncio.to_thread(panel.save, await body(request))
