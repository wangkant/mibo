"""The look panel: which figure the pet on the desktop is, chosen from the app's
settings page, and a check that the saved model still answers."""
from __future__ import annotations

import asyncio

from fastapi import Request

from .. import langs
from .. import setup_wizard as sw

ERRORS: frozenset[str] = frozenset({"invalid_figure", "invalid_lang"})
# Seconds; the save on the earlier page waits as long for the same probe.
CHECK_S = 20


def names(lang: str) -> list[dict]:
    """The figures as the pet's own menu names them, in `lang`."""
    from ..welcome import PET_FIGURES

    # A character's figure has its name; the sprout is no character and has its own.
    return [{"key": key, "name": sw.character_for(key).name_in(lang) if key in sw.PERSONA_KEYS
             else langs.say("Sprout", "小芽", lang)} for key in PET_FIGURES]


def mount(app, workspace, body) -> None:
    from ..welcome import PET_FIGURES, app_settings, pet_figure, save_app_settings

    desktop = workspace.home / "runtime" / "desktop"

    def look(lang: str) -> dict:
        # As the window's figure() picks it.
        return {"figure": pet_figure(desktop, workspace.config()), "figures": names(langs.normalize(lang) or langs.terminal_lang()),
                "toured": bool(app_settings(desktop).get("toured"))}

    @app.get("/api/look")
    async def read_look(lang: str = ""):
        return await asyncio.to_thread(look, lang)

    @app.post("/api/look")
    async def choose_look(request: Request):
        payload = await body(request)
        key = str(payload.get("figure") or "")
        if key not in PET_FIGURES:
            raise ValueError("invalid_figure")
        # The pet reads this file each time it draws, as when its own menu writes it; told to draw now.
        await asyncio.to_thread(save_app_settings, desktop, pet=key)
        workspace.figure_changed()
        return await asyncio.to_thread(look, str(payload.get("lang") or ""))

    @app.post("/api/look/toured")
    async def toured(request: Request):
        # The first run was walked or skipped: it is not shown again.
        await body(request)
        await asyncio.to_thread(save_app_settings, desktop, toured=True)
        # Sharing what it found waits for the tour: it may start now.
        workspace.found()
        return {"toured": True}

    @app.post("/api/look/lang")
    async def choose_lang(request: Request):
        # The first step of the first run: kept before any model is connected.
        payload = await body(request)
        lang = langs.normalize(payload.get("lang"))
        if not lang:
            raise ValueError("invalid_lang")
        await asyncio.to_thread(sw.write_env, workspace.env, {"AGENT_LANG": lang})
        return {"lang": lang}

    def check() -> dict:
        values = workspace.config()
        key = values.get("LLM_API_KEY", "")
        if not key:
            return {"ok": False, "error": "key_required"}
        try:
            probe = sw.probe_key(values.get("LLM_BASE_URL", ""), key, values.get("LLM_MODEL", ""),
                                 timeout=CHECK_S)
        except Exception:
            return {"ok": False, "error": "model_unreachable"}
        if probe.ok:
            return {"ok": True, "error": ""}
        # The codes the save gives for the same answers; never the service's own text.
        return {"ok": False, "error": "key_rejected" if probe.status in (401, 403)
                else "model_limited" if probe.status == 429 else "model_unreachable"}

    @app.post("/api/look/check")
    async def check_model(request: Request):
        await body(request)
        return await asyncio.to_thread(check)
