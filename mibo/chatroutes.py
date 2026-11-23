"""The app page's routes for the chats, what the character knows of the person, and what it found
(`mount`, called by welcome.create_app)."""
from __future__ import annotations

import asyncio
import time
import traceback
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from .character import NotReady
from .chatmedia import ATTACH_ROOM, PICTURE_TYPES
from .memstore import MemoryFileDamaged
from .pagechat import MAIN_CHAT
from .welcome import MAX_BODY
from .workspace import Workspace, chat_failure

LIBRARY_PICTURE_TYPES = {".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


def _number(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def mount(app: FastAPI, workspace: Workspace, body) -> None:
    _mount_chat(app, workspace, body)
    _mount_chats(app, workspace, body)
    _mount_person(app, workspace, body)
    _mount_finds(app, workspace)


def _mount_chat(app: FastAPI, workspace: Workspace, body) -> None:
    @app.post("/api/chat")
    async def chat(request: Request):
        # Room for what is attached: pictures go as base64.
        payload = await body(request, MAX_BODY + ATTACH_ROOM)
        workspace.busy("thinking")
        try:
            return await workspace.chat(str(payload.get("text") or ""), _number(payload.get("after")),
                                        _number(payload.get("retry")), str(payload.get("chat") or MAIN_CHAT),
                                        str(payload.get("reply_to") or ""), payload.get("attachments"),
                                        **({"choices": payload["choices"]} if payload.get("choices") else {}))
        except ValueError:
            raise
        except Exception as error:
            return JSONResponse({"error": chat_failure(error)}, status_code=502)
        finally:
            workspace.busy("")

    @app.get("/api/chat/doing")
    async def chat_doing(after: int | None = None):
        # The line above the pet's head: whether a reply is on its way, the main chat's step, and its last
        # message's number; with `after`, the last words the character said since (the bubble of a reply
        # that came in after its compact chat was put away). Nothing shared.
        view = workspace.history(1 << 30 if after is None else after)
        said = [m.get("text") for m in view.get("messages") or [] if m.get("role") != "user" and m.get("text")]
        return {"busy": workspace._chat_lock.locked(), "doing": view.get("doing"), "last": view["last"],
                "said": said[-1] if after is not None and said else ""}

    @app.post("/api/chat/stop")
    async def stop(request: Request):
        payload = await body(request)
        return await workspace.stop_chat(str(payload.get("chat") or MAIN_CHAT), str(payload.get("why") or "stopped"))

    @app.post("/api/chat/reset")
    async def reset(request: Request):
        await body(request)
        async with workspace._chat_lock:
            workspace.reset_chat()
        return {"ok": True}

    @app.post("/api/chat/forget")
    async def forget(request: Request):
        await body(request)
        return await workspace.forget_chat()

    @app.get("/api/chat/context")
    async def chat_context(chat: str = MAIN_CHAT):
        # On the loop the character runs on: the gauge reads its turns as they are between two awaits.
        return workspace.chat_context(chat)

    @app.post("/api/chat/compact")
    async def compact_chat(request: Request):
        return await workspace.compact_chat(str((await body(request)).get("chat") or MAIN_CHAT))

    @app.post("/api/chat/clear")
    async def clear_context(request: Request):
        return await workspace.clear_context(str((await body(request)).get("chat") or MAIN_CHAT))

    @app.get("/api/chat/history")
    async def history(after: int | None = None, chat: str = MAIN_CHAT):
        # Not in the middle of a reply, when the page looks only for what it is looking up.
        if workspace._chat(chat) is workspace._main and not workspace._chat_lock.locked():
            # Looked at: what the character found may come in now, when it is time.
            try:
                await workspace.share()
            except Exception:
                # The chat still opens with what it holds; the loop tries again.
                traceback.print_exc()
        return workspace.history(after, chat)

    @app.post("/api/chat/bring")
    async def bring(request: Request):
        return await workspace.bring(await body(request))

    @app.get("/api/chat/picture/{name}")
    async def chat_picture(name: str):
        path = workspace.media.picture(name)
        if path is None:
            raise HTTPException(404)
        # Not cached: a picture removed since must show as removed.
        return FileResponse(path, media_type=PICTURE_TYPES[path.suffix[1:]])

    @app.get("/api/chat/file/{name}")
    async def chat_file(name: str):
        path = workspace.media.file(name)
        if path is None:
            raise HTTPException(404)
        # Stored as UTF-8 text whatever it was written in; never run or shown as a page.
        return FileResponse(path, media_type="text/plain; charset=utf-8")


def _mount_chats(app: FastAPI, workspace: Workspace, body) -> None:
    @app.get("/api/chats")
    async def chats():
        return workspace.chats()

    @app.post("/api/chats")
    async def new_chat(request: Request):
        return await workspace.new_chat((await body(request)).get("private") is True)

    @app.post("/api/chats/rename")
    async def rename_chat(request: Request):
        return await workspace.rename_chat(await body(request))

    @app.post("/api/chats/delete")
    async def delete_chat(request: Request):
        return await workspace.delete_chat(await body(request))


def _mount_person(app: FastAPI, workspace: Workspace, body) -> None:
    @app.get("/api/person")
    async def person_view():
        try:
            return await asyncio.to_thread(workspace.character.person_view)
        except MemoryFileDamaged:
            raise ValueError("activity_unavailable") from None

    @app.get("/api/person/said/{item}")
    async def person_said(item: str):
        """The chat lines one kept item came from (查看原话)."""
        try:
            return {"lines": await workspace.character.person_said(item[:64])}
        except NotReady:
            raise ValueError("activity_unavailable") from None

    def person_export(fmt: str) -> dict:
        if fmt not in ("json", "md"):
            raise ValueError("invalid_chat")
        day = time.strftime("%Y-%m-%d")
        return {"file": f"mibo-memory-{day}.{fmt}", "text": workspace.character.person_export(fmt)}

    @app.get("/api/person/export")
    async def person_export_get(format: str = "json"):
        """Everything kept, as a file's name and words; a browser page saves it itself."""
        return await asyncio.to_thread(person_export, format)

    @app.post("/api/person/export")
    async def person_export_save(request: Request):
        """In the app window: the system's Save dialog, and the file written where the person chose; cancelled,
        nothing is written."""
        out = await asyncio.to_thread(person_export, str((await body(request)).get("format") or ""))
        window = getattr(app.state, "window", None)
        if window is None:
            raise ValueError("no_window")
        path = await asyncio.to_thread(window.save_file, out["file"])
        if path:
            await asyncio.to_thread(Path(path).write_text, out["text"], encoding="utf-8")
        return {"saved": bool(path)}

    @app.post("/api/person/{action}")
    async def person_write(request: Request, action: str):
        return await workspace.person_write(action, await body(request))


def _mount_finds(app: FastAPI, workspace: Workspace) -> None:
    @app.get("/api/home")
    async def home_now():
        return await asyncio.to_thread(workspace.character.now)

    @app.get("/api/library/picture/{ident}")
    async def library_picture(ident: str):
        path = workspace.library_picture(ident)
        if path is None or path.suffix not in LIBRARY_PICTURE_TYPES:
            raise HTTPException(404)
        return FileResponse(path, media_type=LIBRARY_PICTURE_TYPES[path.suffix])
