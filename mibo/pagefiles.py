"""The app page's own files: its pages, scripts and styles, its catalogs of words, the pet's figures and the
characters' portraits, each served by name from the page's folder (`mount`, called by welcome.create_app)."""
from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response

from . import i18n, langs
from . import setup_wizard as sw
from .welcome import ASSETS, PET_FIGURES, app_settings
from .workspace import Workspace

# The page's own files, served by name.
PAGE_ASSETS = ("i18n.js", "app.js", "app.css", "chat.js", "chat.css", "finds.js", "finds.css", "signin.css",
               "onboard.js", "onboard.css", "setup.js", "setup.css", "faces.js", "sidechats.js", "browserun.js",
               "pet.js", "petclips.js", "petwalk.js", "petpaint.js", "petlife.js", "petbring.js", "pethand.js",
               "petpointer.js", "pet.css", "card.js", "card.css", "characters.js", "characters.css",
               "browse.js", "browsetabs.js", "browsemenu.js", "browsestrip.js", "browse.css", "plus.js", "plus.css",
               "activity.js", "activity.css",
               "linkcard.js", "linkcard.css", "modelbar.js", "modelbar.css", "providermarks.js", "sites.js", "sites.css",
               "toolcard.js", "petux.css", "petbox.js", "petline.js", "petedge.js", "petdial.js",
               "petclick.js", "petoff.js", "compact.js", "compact.css", "schedulechat.js", "markdown-it.umd.min.js",
               "chatkit.js", "chattext.js", "findcard.js", "attach.js", "chatthread.js")
# Settings' sections, each a script of its own under ASSETS/setup (setup.js is their shell), and the scripts they
# draw on (the model chooser, the connectors' words, the zip of a chosen folder).
SETUP_PARTS = ("character", "model", "connect", "language", "recs", "walks", "memory", "privacy", "device", "about",
               "shell", "programs", "skills", "tools", "schedule", "modelpick", "toolswords", "zip")
FIGURE_TYPES = {"svg": "image/svg+xml", "webp": "image/webp", "pet.webp": "image/webp", "pet.json": "application/json"}


def mount(app: FastAPI, workspace: Workspace) -> None:
    _mount_pages(app, workspace)
    _mount_assets(app, workspace)


def _mount_pages(app: FastAPI, workspace: Workspace) -> None:
    @app.get("/")
    async def index():
        # The app: what the character found, and the chat.
        return FileResponse(ASSETS / "app.html")

    @app.get("/pet")
    async def pet():
        # The character alone, for the small window mibo starts as.
        return FileResponse(ASSETS / "pet.html")

    @app.get("/compact")
    async def compact():
        # The app page again, laid out as the small chat beside the pet (compact.js).
        return FileResponse(ASSETS / "app.html")

    @app.get("/locale.js")
    async def locale_script():
        # The interface's language and its catalog, English beside it, for the page's other scripts (i18n.js).
        code = i18n.lang(await asyncio.to_thread(workspace.config))
        data = json.dumps([code, i18n.catalog(code), i18n.catalog("en")], ensure_ascii=False)
        return Response(f"paI18n.load(...{data});\n", media_type="text/javascript; charset=utf-8",
                        headers={"Cache-Control": "no-store"})

    @app.get("/assets/locales/{name}")
    async def locale_file(name: str):
        # A language's catalog, for a page that changes to it.
        if name.removesuffix(".json") not in langs.CODES or not name.endswith(".json"):
            raise HTTPException(404)
        return FileResponse(i18n.LOCALES / name, media_type="application/json")

    @app.get("/health")
    async def health():
        # That the page answers, nothing more.
        return {"ok": True}


def _mount_assets(app: FastAPI, workspace: Workspace) -> None:
    @app.get("/assets/{name}")
    async def asset(name: str):
        if name not in PAGE_ASSETS:
            raise HTTPException(404)
        return FileResponse(ASSETS / name)

    @app.get("/assets/figures/{name}")
    async def pet_figure(name: str):
        # A figure is a drawing (<key>.svg) or a sheet of frames cut from a painting (<key>.webp),
        # and a painted one has the pet's poses too (<key>.pet.webp, laid out in <key>.pet.json).
        key, _, kind = name.partition(".")
        path = ASSETS / "figures" / name
        if key not in PET_FIGURES or kind not in FIGURE_TYPES or not path.is_file():
            raise HTTPException(404)
        if name == "mibo.svg":
            # Mibo in the colours chosen for it.
            from .panels import colors
            chosen = colors.chosen(await asyncio.to_thread(app_settings, workspace.home / "runtime" / "desktop"))
            return Response(colors.paint(path.read_text(encoding="utf-8"), chosen), media_type="image/svg+xml")
        return FileResponse(path, media_type=FIGURE_TYPES[kind])

    @app.get("/assets/setup/{name}")
    async def setup_part(name: str):
        stem, _, kind = name.rpartition(".")
        # A section's script, and the styles of the one that has its own (skills.css).
        if stem not in SETUP_PARTS or kind not in ("js", "css") or not (ASSETS / "setup" / name).is_file():
            raise HTTPException(404)
        return FileResponse(ASSETS / "setup" / name)

    @app.get("/assets/characters/{name}")
    async def character_portrait(name: str):
        path = sw.portrait(name.removesuffix(".webp")) if name.endswith(".webp") else None
        if path is None:
            raise HTTPException(404)
        return FileResponse(path, media_type="image/webp", headers={"Cache-Control": "max-age=86400"})
