"""The app's local page: setup, settings and chat, behind its own token. No
account is needed to open it. `create_app` builds the page and its boundary,
each area's routes mounted from their own module; `main` starts it, in its own
window or in the browser."""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import functools
import importlib
import json
import os
import secrets
import socket
import subprocess
import sys
import threading
import traceback
import webbrowser
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from . import __version__, i18n, langs, life, quiet, settingsfile, updates
from . import home as homes
from . import setup_wizard as sw
from . import window as appwindow
from .library import item_id
from .panels import modelbar
from .see import when
from .storage import FileLock, LockUnavailable, atomic_write_text
from .workspace import Workspace

ASSETS = Path(__file__).with_name("static") / "welcome"
# Parts of the page beyond its four first views. Each is a module in
# mibo/panels with `mount(app, workspace, body)`, drawn by the app
# page's own files (setup.js and its sections, chat.js).
PANELS = ("runtime", "desk", "tuning", "detect", "signin", "feedpage", "sources", "look", "profile", "quiet", "remarks",
          "browser", "colors", "compose", "links", "modelbar", "signins", "tools", "pet", "schedule", "walks")
# The figures the pet can be, <key>.svg under the page's figures folder; the first is the
# default, and a character of one's own is it too.
PET_FIGURES = ("mibo", "chatgpt", "deepseek", "claude")
TOKEN_HEADER = "x-mibo-setup-token"
# Bytes; a chat message may be 8000 characters, three bytes each in Chinese.
MAX_BODY = 32_768
# Characters; the shipped personas are under 800, imported cards often run past 4,000,
# and the engine itself sets no limit. Every reply sends the whole persona.
PERSONA_LIMIT = 16_000
# The error codes a refused request names to the page; any other is "generic". Each panel adds its ERRORS.
ERRORS = frozenset({
    "busy", "invalid_provider", "key_required", "invalid_url", "https_required", "model_required",
    "invalid_character", "key_rejected", "model_limited", "model_unreachable", "model_no_balance", "model_not_found",
    "model_window_small", "key_malformed", "key_again", "name_required", "invalid_message", "invalid_chat",
    "activity_unavailable", "activity_changed", "memory_secret", "memory_not_instructions", "memory_paused",
    "memory_health_off", "avatar_type", "avatar_too_large", "item_gone", "invalid_title", "attach_too_many",
    "picture_type", "picture_too_large", "file_type", "file_too_large", "file_unreadable"})

# The page listens here only: it is this computer's alone.
PAGE_HOST = "127.0.0.1"
# Seconds a start after a restore or a reset waits for the app before it to close.
RESTART_WAIT_S = 60
LOOPBACK = ("localhost", "127.0.0.1", "::1")
FORWARDED = ("x-forwarded-host", "forwarded", "x-forwarded-for")


def _refuse(code: str = "forbidden", status: int = 403) -> JSONResponse:
    return JSONResponse({"error": code}, status_code=status)


def _judge(request: Request, token: str) -> JSONResponse | None:
    """None when the request may go on: addressed to a loopback name, and to the
    API only with the token, from the page's own origin, through no proxy."""
    try:
        host = urlsplit("//" + request.headers.get("host", "")).hostname
    except ValueError:
        return _refuse()
    if host not in LOOPBACK:
        return _refuse()
    if request.url.path.startswith("/api/"):
        if not secrets.compare_digest(request.headers.get(TOKEN_HEADER, "").encode(), token.encode()):
            return _refuse()
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
            return _refuse()
        if any(request.headers.get(key) for key in FORWARDED):
            return _refuse()
    return None


async def _body(request: Request, limit: int = MAX_BODY) -> dict:
    """The request's JSON object, read up to `limit` bytes."""
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > limit:
            raise HTTPException(413, "too_large")
    try:
        value = json.loads(raw or b"{}")
    except ValueError:
        raise HTTPException(400, "invalid_json") from None
    if not isinstance(value, dict):
        raise HTTPException(400, "invalid_json")
    return value


def _lifespan(workspace: Workspace):
    @asynccontextmanager
    async def lifespan(app):
        # The character, with its own loops: its memory, its walks, the follow-up of a plan.
        await workspace.character.start()
        # The saved model measured once when nothing is kept for it, before the first reply (loop.py waits for it).
        modelbar.check_at_start(workspace)
        # Another program in front, or another tab: maybe a good moment to bring something (pacing.py).
        quiet.on_front(lambda: asyncio.ensure_future(workspace.pace.look()))
        later = [asyncio.create_task(loop) for loop in (
            # Games and fullscreen in front: the background loops wait and the pet hides (quiet.py).
            quiet.watch(workspace._runtime),
            # The public sources need no model: they are read whenever the page runs.
            app.state.sources.loop(),
            # What the character found comes into the main chat at its own pace, whether or not it is open.
            workspace.share_loop(),
            # The person's MCP servers run with the page and stop with it (mcp_hub.py).
            app.state.mcp.run(),
            # Scheduled tasks run when due, whether or not the window is open (panels/schedule.py).
            app.state.schedule.loop(),
            # Now and then a line about what the person is doing (remarks.py).
            app.state.remarks.loop())]
        try:
            yield
        finally:
            for task in later:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
            for stop in app.state.closers:
                await asyncio.to_thread(stop)
            await workspace.character.close()
            workspace.close()
    return lifespan


def create_app(home: Path, token: str, *, workspace: Workspace | None = None) -> FastAPI:
    """The page, for this computer alone: a loopback address, and the token for the API."""
    workspace = workspace or Workspace(home)
    app = FastAPI(lifespan=_lifespan(workspace), docs_url=None, redoc_url=None, openapi_url=None)
    app.state.workspace = workspace
    # What a panel started and must stop; called before the character stops.
    app.state.closers = []

    @app.middleware("http")
    async def boundary(request: Request, call_next):
        response = _judge(request, token) or await call_next(request)
        # Only the portraits set their own: they never change while the page runs.
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; "
            "connect-src 'self'; frame-src " + " ".join(f"https://{host}" for host in life.PLAYER_HOSTS) + "; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        return response

    panels = [importlib.import_module(f"{__package__}.panels.{name}") for name in PANELS]
    known = ERRORS.union(*(panel.ERRORS for panel in panels))

    @app.exception_handler(ValueError)
    async def bad_value(request, exc):
        error = str(exc)
        return JSONResponse({"error": error if error in known else "generic"}, status_code=400)

    _mount_areas(app, workspace, token, panels)
    return app


def _mount_areas(app: FastAPI, workspace: Workspace, token: str, panels: list) -> None:
    from . import appmap, cardwait, chatroutes, mcp_offer, pagefiles, standing, turnon
    from .shell import panel as shell_panel
    from .skills import panel as skills_panel
    pagefiles.mount(app, workspace)
    _mount_setup(app, workspace)
    chatroutes.mount(app, workspace, _body)
    _mount_controls(app)
    for panel in panels:
        panel.mount(app, workspace, _body)
    # A turn's MCP tools come from the hub the tools panel made (mcp_offer.py).
    mcp_offer.offer_source = app.state.mcp.offer
    # Commands on this computer: their questions, Settings' section and the log (shell/panel.py).
    shell_panel.mount(app, workspace, _body)
    # The question that turns a switched-off ability on from the chat (turnon.py).
    turnon.mount(app, workspace, _body)
    # The person's typed yes to a step waiting in the chat, for every place that asks (cardwait.py).
    cardwait.mount(app, workspace, _body)
    # The app's own settings and abilities, looked up, opened and changed by the character (appmap.py).
    appmap.mount(app, workspace, _body, token)
    # The person's standing rules, read by the reviewer, listed and removed in Settings (standing.py).
    standing.mount(app, workspace, _body)
    # Skills: Settings' section, adding and removing them (skills/panel.py).
    skills_panel.mount(app, workspace, _body)
    # Other programs' windows, on Windows: their questions, Settings' section and the log (desk/panel.py).
    if os.name == "nt":
        from .desk import panel as desk_panel
        desk_panel.mount(app, workspace, _body)


def _mount_setup(app: FastAPI, workspace: Workspace) -> None:
    """The setup's routes: what is saved, the services and characters to choose from, and the character's picture."""
    @app.get("/api/state")
    async def state():
        summary = await asyncio.to_thread(workspace.summary)
        summary["modelUnreachable"] = workspace.character.model_unreachable()
        return summary

    @app.get("/api/catalog")
    async def catalog(request: Request):
        values = await asyncio.to_thread(workspace.config)
        # The saved language, else the one this computer's browser asks for: DeepSeek leads for Chinese.
        lang = langs.normalize(values.get("AGENT_LANG")) or request.headers.get("accept-language", "")
        # Names and notes in the interface's language.
        words = i18n.words("catalog", i18n.lang(values))["providers"]
        return {"providers": [{"id": p.key, "name": words[p.key]["name"], "baseUrl": p.base_url,
                               "model": p.model, "keyUrl": p.key_url, "note": words[p.key].get("note", ""),
                               "local": not p.needs_key} for p in sw.providers_for(lang)],
                "characters": [{"id": c.key,
                                # By the character's language; ownNames adds the names it had before.
                                "defaultNames": {code: c.name_in(code) for code in sw.LANGS} if c.stem else None,
                                "ownNames": sorted(c.own_names),
                                "avatar": f"/assets/characters/{c.key}.webp" if sw.portrait(c.key) else None}
                               for c in sw.CHARACTERS],
                "ownAvatarLimit": sw.MAX_OWN_AVATAR, "personaLimit": PERSONA_LIMIT}

    @app.post("/api/config")
    async def config(request: Request):
        saved = await asyncio.to_thread(workspace.save, await _body(request))
        # The chooser said where page text, window pictures and file text go before this save (setup/modelpick.js).
        await asyncio.to_thread(when.tell, workspace.home / "runtime" / "desktop", when.host_of(workspace.config()))
        return saved

    @app.get("/api/model/notice")
    async def model_notice():
        """The model service's host the person was last told about, so the chooser says it once per host."""
        return {"host": await asyncio.to_thread(when.told, workspace.home / "runtime" / "desktop")}

    @app.get("/api/avatar")
    async def own_avatar():
        path = sw.own_avatar(workspace.home)
        if path is None:
            raise HTTPException(404)
        return FileResponse(path, media_type=sw.OWN_AVATAR_TYPES[path.suffix[1:]])

    @app.post("/api/avatar")
    async def save_own_avatar(request: Request):
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > sw.MAX_OWN_AVATAR:
            raise ValueError("avatar_too_large")
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > sw.MAX_OWN_AVATAR:
                raise ValueError("avatar_too_large")
        return await asyncio.to_thread(workspace.save_own_avatar, bytes(raw))

    @app.post("/api/avatar/remove")
    async def remove_own_avatar(request: Request):
        await _body(request)
        return await asyncio.to_thread(workspace.remove_own_avatar)


def _mount_controls(app: FastAPI) -> None:
    """The app itself: its window brought to the front, and the app closed."""
    @app.post("/api/show")
    async def show(request: Request):
        await _body(request)
        callback = getattr(app.state, "show", None)
        return {"ok": True, "window": bool(callback and await asyncio.to_thread(callback))}

    @app.post("/api/exit")
    async def exit_app(request: Request):
        await _body(request)
        callback = getattr(app.state, "shutdown", None)
        if callback:
            callback()
        return {"ok": True}


def _raise_window(url: str) -> bool:
    """Ask the mibo already running to bring its window to the front."""
    address = urlsplit(url)
    if os.name == "nt":
        import ctypes
        # Windows lets a window take the foreground only when the process the
        # person just started says it may.
        ctypes.windll.user32.AllowSetForegroundWindow(-1)
    try:
        answer = httpx.post(f"{address.scheme}://{address.netloc}/api/show", json={}, timeout=5,
                            trust_env=False,
                            headers={TOKEN_HEADER: address.fragment.partition("token=")[2]})
        return bool(answer.json().get("window"))
    except (httpx.HTTPError, ValueError, AttributeError):
        return False


def app_settings(desktop: Path) -> dict:
    """What the person chose about the app itself, not about the character."""
    return sw._read_json(desktop / "app.json")


def save_app_settings(desktop: Path, **changes) -> dict:
    values = {**app_settings(desktop), **changes}
    atomic_write_text(desktop / "app.json", json.dumps(values))
    return values


def pet_figure(desktop: Path, config: dict) -> str:
    """Which figure the pet is: the one chosen from its menu, else the character's own, else the first."""
    settings = app_settings(desktop)
    if settings.get("pet") in PET_FIGURES:
        return settings["pet"]
    avatar = config.get("PERSONA_AVATAR", "")
    return avatar if avatar in PET_FIGURES else PET_FIGURES[0]


def _app_window(app: FastAPI, url: str, desktop: Path, hidden: bool) -> appwindow.AppWindow:
    """The page's window, with the pet, its menus and the app's link choice; the workspace tells it what changed."""
    workspace = app.state.workspace

    def words() -> dict:
        # The notification-area icon's menu and the pet's own.
        return i18n.words("tray", i18n.lang(workspace.config()))

    def figures() -> list[tuple[str, str]]:
        from .panels import look
        return [(row["key"], row["name"]) for row in look.names(workspace, "")]

    def choose(key: str) -> None:
        # The pet's menu chooses a whole character, as the app's pickers do.
        from .panels import look
        look.choose_figure(workspace, key)

    window = appwindow.AppWindow(
        url, storage=desktop / "webview", words=words,
        background=lambda: bool(app_settings(desktop).get("background")),
        # Hidden only makes sense where closing can hide too.
        start_hidden=hidden and bool(app_settings(desktop).get("background")),
        pet=True, figure=lambda: pet_figure(desktop, workspace.config()), figures=figures,
        choose=choose,
        # Links open in the browser inside the app window unless the person chose the system's
        # (panels/browser.py), where a find's reading is timed: the library knows a find by its address.
        links=lambda: app_settings(desktop).get("links", "app"),
        find=lambda address: getattr(workspace._library().get(item_id(address)), "id", ""),
        address=lambda ident: getattr(workspace._library().get(ident), "url", ""))
    # The window's pages are told of a chat or a figure that changed, or of something found, and need not keep asking.
    workspace.chat_changed = lambda: window.chats_changed()
    workspace.figure_changed = lambda: window.refigure()
    workspace.news = lambda: window.pet_look()
    workspace.busy = lambda doing: window.pet_busy(doing)
    return window


def _serve_in_window(app: FastAPI, server, sockets: list, url: str, desktop: Path,
                     hidden: bool = False) -> None:
    """The page in its own window on this thread, the server behind it on another."""
    window = _app_window(app, url, desktop, hidden)
    app.state.window = window

    def stop() -> None:
        server.should_exit = True
        window.close()

    def serve() -> None:
        try:
            server.run(sockets=sockets)
        finally:
            window.close()

    app.state.shutdown = stop
    app.state.show = window.show
    serving = threading.Thread(target=serve, name="mibo-page")
    serving.start()
    try:
        # No error and no window: it was closed before it finished opening.
        if not window.run() and window.error:
            app.state.show = None
            print(i18n.t("start.noWindow", i18n.lang(app.state.workspace.config()))
                  + f" ({window.error})", flush=True)
            webbrowser.open(url)
            while serving.is_alive():
                serving.join(0.5)
    except KeyboardInterrupt:
        # Ctrl+C closed the window; the signal itself may land only here.
        pass
    finally:
        stop()
        serving.join()


def main(argv: list[str] | None = None, prog: str = "mibo start") -> int:
    lang = i18n.lang()
    parser = argparse.ArgumentParser(prog=prog, description=i18n.t("start.about", lang))
    parser.add_argument("--browser", action="store_true", help=i18n.t("start.browser", lang))
    parser.add_argument("--no-browser", action="store_true", help=i18n.t("start.noBrowser", lang))
    parser.add_argument("--background", action="store_true", help=i18n.t("start.background", lang))
    parser.add_argument("--port", type=int, default=0, help=i18n.t("start.port", lang))
    # Started by the app itself after a restore or a reset: it waits for the one before to close.
    parser.add_argument("--restart", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    home = homes.find_home()
    # Before anything is written in it: app.log and welcome.json hold the page's token link.
    sw.secure_home(home)
    desktop = home / "runtime" / "desktop"
    # Started by pythonw, as the shortcut does: no terminal, so sentences go to
    # a log and a refusal to a dialog.
    quiet = sys.stdout is None or sys.stderr is None
    log = None
    if quiet:
        desktop.mkdir(parents=True, exist_ok=True)
        # Appended: a second start must not empty the log of the one running.
        log = sys.stdout = sys.stderr = (desktop / "app.log").open("a", encoding="utf-8", buffering=1)

    def refuse(text: str) -> int:
        print(text, flush=True)
        if quiet:
            appwindow.alert(text)
        return 1

    try:
        return _start(args, home, refuse, log)
    except Exception:
        if not quiet:
            raise
        traceback.print_exc()
        appwindow.alert(i18n.t("cli.broken", lang, log=desktop / "app.log"))
        return 1


def _start(args: argparse.Namespace, home: Path, refuse: Callable[[str], int], log=None) -> int:
    from .textproc import DESKTOP_ENV
    # The desktop app keeps this computer's clock (textproc.default_tz_offset).
    os.environ[DESKTOP_ENV] = "1"
    info = home / "runtime" / "desktop" / "welcome.json"
    lang = i18n.lang()
    lock = FileLock(info.with_suffix(".lock"), timeout=RESTART_WAIT_S if args.restart else 0)
    try:
        lock.acquire()
        if log:
            # This start is the one that runs: its log begins here.
            log.truncate(0)
    except LockUnavailable:
        return _show_running(args, info, refuse, lang)
    sockets: list[socket.socket] = []
    try:
        port = args.port or _page_port(home)
        if port is None:
            return refuse(i18n.t("start.pagePortBad", lang))
        from .panels import desk
        desk.apply_pending(home)
        try:
            sockets = [_listen(port)]
        except OSError:
            if args.port:
                return refuse(i18n.t("start.portFlagBusy", lang, port=args.port))
            return refuse(i18n.t("start.portBusy", lang, port=port))
        return _serve(args, home, sockets, info, lang)
    finally:
        for sock in sockets:
            sock.close()
        info.unlink(missing_ok=True)
        lock.release()


def _show_running(args: argparse.Namespace, info: Path, refuse: Callable[[str], int], lang: str) -> int:
    """Another start holds the home: its window comes to the front, or its page opens in the browser."""
    url = sw._read_json(info).get("url", "")
    if not url:
        return refuse(i18n.t("start.starting", lang))
    print(url, flush=True)
    if not args.no_browser and (args.browser or not _raise_window(url)):
        webbrowser.open(url)
    return 0


def _serve(args: argparse.Namespace, home: Path, sockets: list[socket.socket], info: Path, lang: str) -> int:
    """The page on the socket bound, its link written to `info`, in its own window or the browser until closed."""
    import uvicorn
    token = secrets.token_urlsafe(32)
    port = sockets[0].getsockname()[1]
    url = f"http://{PAGE_HOST}:{port}/#token={token}"
    atomic_write_text(info, json.dumps({"url": url}))
    windowed = not (args.browser or args.no_browser) and appwindow.available()
    print(i18n.t("start.inWindow" if windowed else "start.inTerminal", lang, version=__version__, url=url), flush=True)
    # What became of an update the run before began (updates.settle): the page says it once.
    updates.settle(home)
    found = updates.notice(home)
    if found:
        print(i18n.t("start.update", lang, **found), flush=True)
    app = create_app(home, token)
    app.state.relaunch = functools.partial(relaunch, home, args)
    server = uvicorn.Server(uvicorn.Config(app, host=PAGE_HOST, port=port, log_level="warning"))
    if windowed:
        _serve_in_window(app, server, sockets, url, home / "runtime" / "desktop", hidden=args.background)
        return 0
    if not args.no_browser:
        # The socket already listens, so an early request waits its turn.
        timer = threading.Timer(0, webbrowser.open, args=(url,))
        timer.daemon = True
        timer.start()
    app.state.shutdown = lambda: setattr(server, "should_exit", True)
    server.run(sockets=sockets)
    return 0


def relaunch(home: Path, args: argparse.Namespace) -> None:
    """Start the app again as it was started, to take the home over once this one has closed."""
    from . import autostart
    command = [sys.executable, "start"] if autostart.frozen() else [sys.executable, "-m", "mibo", "start"]
    command += ["--home", str(home), "--restart"]
    if args.port:
        command += ["--port", str(args.port)]
    if args.no_browser or args.browser:
        command.append("--no-browser" if args.no_browser else "--browser")
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    subprocess.Popen(command, stdin=subprocess.DEVNULL, close_fds=True, creationflags=flags,
                     start_new_session=os.name != "nt")


def _page_port(home: Path) -> int | None:
    """PAGE_PORT, the environment over the home's settings: 0 when blank, None when it is no port."""
    raw = (os.environ.get("PAGE_PORT") or settingsfile.values(home, keys=False).get("PAGE_PORT") or "").strip()
    if not raw:
        return 0
    return int(raw) if raw.isdigit() and 0 < int(raw) < 65536 else None


def _listen(port: int) -> socket.socket:
    """The page's socket, on this computer only. OSError when it cannot bind."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if os.name != "nt":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((PAGE_HOST, port))
        sock.listen(128)
    except (OSError, OverflowError):
        sock.close()
        raise OSError("bind") from None
    return sock
