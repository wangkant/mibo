"""Quiet: while the person plays a game, watches something fullscreen or gives
a presentation, the app hides its pet and runs at a bare minimum.

`watch(runtime)` is the sensing task, one per process. The character service
the page starts runs it only until the page first tells it quiet's state
(`follow`, POST /v1/quiet): from then on only the page looks. On Windows it
looks at what is in front of the screen only when the system says something
changed there (a WinEvent hook, see `_Hook`); on macOS every SENSE_S. Quiet starts at once on
a signal (a plain fullscreen window only if a second look CONFIRM_S later
still sees it) and ends only after CALM_S without one, so alt-tab does not
flap it. Background loops call `await wait()` before their next step; replies
the person asks for never do. While quiet the process runs at below-normal
priority. `front()` is the window in front as the last look saw it, for
activity.py.

Signals on Windows: the shell's own notification state (a Direct3D fullscreen
game, presentation mode, a fullscreen app), the window in front covering its
whole monitor with no title bar, and a game in front even when windowed. On
macOS: the frontmost window covering a display, read through CoreGraphics
(bounds and owners need no permission). Nothing here is written to disk but
the setting.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

from .storage import atomic_write_text

logger = logging.getLogger("agent.quiet")

SETTINGS_FILE = "quiet.json"
# macOS: how often it looks.
SENSE_S = 2.0
CONFIRM_S = 1.0
CALM_S = 8.0
# Windows: while there is a signal, a look this often, for an end no event shows (a browser leaving F11).
LOOK_S = 5.0
# Something moved or was retitled in the program in front (the window itself, its caret, the cursor over
# it): a look this long after, the hook on that program off meanwhile, as a busy one sends dozens a second.
SETTLE_S = 1.0

# Where games are installed, as lower-case path parts, and games known by their exe.
GAME_DIRS = ("\\steamapps\\common\\", "\\epic games\\", "\\riot games\\", "\\mihoyo\\", "\\hoyoverse\\",
             "\\wegameapps\\", "\\xboxgames\\", "\\modifiablewindowsapps\\", "/steamapps/common/")
GAME_EXES = frozenset({"genshinimpact.exe", "yuanshen.exe", "starrail.exe", "zenlesszonezero.exe",
                       "league of legends.exe", "valorant-win64-shipping.exe", "cs2.exe", "dota2.exe",
                       "overwatch.exe", "wow.exe", "diablo iv.exe", "hearthstone.exe",
                       "fortniteclient-win64-shipping.exe", "r5apex.exe", "tslgame.exe",
                       "robloxplayerbeta.exe", "minecraft.windows.exe", "eldenring.exe"})
# Launchers and tools installed beside the games are not games.
LAUNCHERS = frozenset({"steam.exe", "steamwebhelper.exe", "epicgameslauncher.exe", "epicwebhelper.exe",
                       "riotclientservices.exe", "riotclientux.exe", "riot client.exe", "battle.net.exe",
                       "battle.net launcher.exe", "agent.exe", "wegame.exe", "launcher.exe", "hyp.exe",
                       "hoyoplay.exe", "unrealeditor.exe", "ue4editor.exe", "ui32.exe", "wallpaper32.exe",
                       "wallpaper64.exe"})
# A video watched in a normal window: a player, or a browser on a video site.
PLAYERS = frozenset({"vlc.exe", "potplayer.exe", "potplayermini.exe", "potplayermini64.exe", "mpc-hc.exe",
                     "mpc-hc64.exe", "mpc-be64.exe", "mpv.exe", "wmplayer.exe", "video.ui.exe",
                     "microsoft.media.player.exe", "qqplayer.exe", "kmplayer.exe",
                     "vlc", "iina", "quicktime player", "mpv"})
BROWSERS = frozenset({"chrome.exe", "msedge.exe", "firefox.exe", "opera.exe", "brave.exe", "vivaldi.exe",
                      "360se.exe", "360chrome.exe", "qqbrowser.exe", "sogouexplorer.exe"})
VIDEO_TITLES = ("youtube", "bilibili", "哔哩哔哩", "netflix", "twitch", "youku", "优酷", "iqiyi", "爱奇艺",
                "腾讯视频", "抖音", "douyin", "vimeo", "prime video", "disney+", "西瓜视频", "斗鱼", "虎牙")

_quiet = False
_why = ""
_since = time.time()
_video = False
_last_signal = 0.0
_watching = False
_calm: asyncio.Event | None = None
_listeners: list[Callable[[dict], None]] = []
# Told each time the window in front, or its title, changes (pacing.py).
_front_listeners: list[Callable[[], None]] = []
# When the caret last moved in the program in front (time.monotonic()): the person typing.
_typed = float("-inf")
_priority = 0
# The window in front at the last look (Windows), and the hook that looks.
_front = {"hwnd": 0, "pid": 0, "path": "", "title": "", "signal": ""}
_hook: _Hook | None = None
# Told by the page (the character service): its own looks no longer count.
_told = False
# A video full screen in the app's own window (window.py): it counts as any other program's.
_own_full = False


# ------------------------------------------------------------------ the state --

def state() -> dict:
    return {"quiet": _quiet, "why": _why, "since": _since, "video_front": _video}


def active() -> bool:
    return _quiet


def front() -> dict:
    """The window in front as the last look saw it: its process id, program
    path, title, and quiet's signal for it ('' for none). Windows, while `watch` runs."""
    return _front


async def wait() -> None:
    """At once when not quiet, else when quiet ends."""
    while _quiet:
        await _calm.wait()


def listen(fn: Callable[[dict], None]) -> None:
    """`fn(state())` on the sensing task's loop each time quiet starts or ends."""
    _listeners.append(fn)


def on_front(fn: Callable[[], None]) -> None:
    """`fn()` on the sensing task's loop each time the window in front or its title changes (Windows)."""
    _front_listeners.append(fn)


def typed_ago() -> float:
    """Seconds since the caret last moved in the program in front; inf when never seen (Windows only)."""
    return time.monotonic() - _typed


def own_full_screen(on: bool) -> None:
    global _own_full
    _own_full = on
    if _hook is not None:
        _hook.poke()


def _tell(listeners: list[Callable], *args) -> None:
    """Each listener told; one that fails is logged and the others still hear."""
    for fn in listeners:
        try:
            fn(*args)
        except Exception:
            logger.exception("quiet: a listener failed")


def _moved() -> None:
    if not _told:
        _tell(_front_listeners)


def settings(runtime: Path) -> dict:
    try:
        on = json.loads((Path(runtime) / SETTINGS_FILE).read_text(encoding="utf-8")).get("on", True)
    except (OSError, ValueError, AttributeError):
        on = True
    return {"on": on is not False}


def save_settings(runtime: Path, on: bool) -> dict:
    Path(runtime).mkdir(parents=True, exist_ok=True)
    atomic_write_text(Path(runtime) / SETTINGS_FILE, json.dumps({"on": bool(on)}))
    if _hook is not None:
        # A look now, by the new setting; the service hears the outcome from the page (follow).
        _hook.poke()
    return {"on": bool(on)}


def _change(quiet: bool, why: str, now: float) -> None:
    global _quiet, _why, _since
    _quiet, _why, _since = quiet, why, now
    _lower(quiet)
    if quiet:
        _calm.clear()
    else:
        _calm.set()
    logger.info("quiet: %s", f"on ({why})" if quiet else "off")
    _tell(_listeners, state())


def step(signal: str, video: bool, on: bool, now: float) -> None:
    """One look's outcome: `signal` is why it is quiet now ('' for nothing)."""
    global _last_signal, _video, _why
    _video = video
    if signal and on:
        _last_signal = now
        if not _quiet:
            _change(True, signal, now)
        else:
            _why = signal
    elif _quiet and (not on or now - _last_signal >= CALM_S):
        _change(False, "", now)


def _seen(signal: str, video: bool, on: bool, now: float) -> None:
    """A look of this process's own, unless the page now tells it."""
    if not _told:
        step(signal, video, on, now)


def follow(quiet: bool, why: str) -> None:
    """The character service, told by the page that started it whether quiet
    holds: its own hook stops the first time, and quiet goes as the page says."""
    global _hook, _told
    if not _told:
        logger.info("quiet: told by the page from now on")
    _told = True
    if _hook is not None:
        _hook.stop()
        _hook = None
    if quiet != _quiet:
        _change(quiet, why, time.time())


class _Setting:
    """The setting as the file says, read again only when the file changed."""

    def __init__(self, path: Path):
        self.path, self.stamp, self.on = path, None, True

    def __call__(self) -> bool:
        try:
            stamp = self.path.stat().st_mtime_ns
        except OSError:
            stamp = 0
        if stamp != self.stamp:
            self.stamp, self.on = stamp, settings(self.path.parent)["on"]
        return self.on


async def watch(runtime: Callable[[], Path]) -> None:
    """The sensing task; cancelled with the process's other tasks."""
    global _watching, _calm, _hook
    if _watching:
        return
    _watching, _calm = True, asyncio.Event()
    _calm.set()
    setting = _Setting(Path(runtime()) / SETTINGS_FILE)
    try:
        if sys.platform == "win32":
            loop = asyncio.get_running_loop()
            _hook = _Hook(setting, lambda *look: loop.call_soon_threadsafe(_seen, *look),
                          lambda: loop.call_soon_threadsafe(_moved))
            _hook.start()
            # Until cancelled: the hook's thread does the looking, or the page (follow).
            await asyncio.Future()
        elif sys.platform == "darwin":
            await _poll(setting)
            await asyncio.Future()
    finally:
        if _hook is not None:
            _hook.stop()
            _hook = None
        if _quiet:
            _change(False, "", time.time())
        _watching = False


async def _poll(setting: _Setting) -> None:
    """macOS: a look every SENSE_S, until the page tells it (follow)."""
    failing = False
    while not _told:
        on = setting()
        try:
            signal, video = await asyncio.to_thread(sense) if on else ("", False)
            if signal == "fullscreen" and not _quiet:
                # Alt-tab, a screenshot's overlay: gone a moment later; a fullscreen video is not.
                await asyncio.sleep(CONFIRM_S)
                signal, video = await asyncio.to_thread(sense)
            failing = False
        except Exception:
            if not failing:
                logger.exception("quiet: a look failed")
            signal, video, failing = "", False, True
        _seen(signal, video, on, time.time())
        await asyncio.sleep(SENSE_S)


# --------------------------------------------------------------- what it is --

def game_path(path: str) -> bool:
    """Whether a process image at `path` is a game."""
    low = path.lower()
    name = low.replace("/", "\\").rsplit("\\", 1)[-1]
    if name in LAUNCHERS:
        return False
    return name in GAME_EXES or any(part in low for part in GAME_DIRS)


def video_front(name: str, title: str) -> bool:
    """Whether the program `name` (exe or app name) with this window title shows a video."""
    name, title = name.lower(), title.lower()
    return name in PLAYERS or (name in BROWSERS and any(word in title for word in VIDEO_TITLES))


def sense() -> tuple[str, bool]:
    """('game' | 'presentation' | 'fullscreen' | '', whether a video is in front)."""
    if sys.platform == "win32":
        return _sense_windows()
    if sys.platform == "darwin":
        return _sense_mac()
    return "", False


# ------------------------------------------------------------------ Windows --

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _shell32 = ctypes.WinDLL("shell32")
    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.MonitorFromWindow.restype = wintypes.HANDLE
    _user32.MonitorFromWindow.argtypes = (wintypes.HWND, wintypes.DWORD)
    _user32.GetWindowLongW.restype = wintypes.LONG
    _user32.GetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int)
    _user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    _user32.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    _user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    _user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
    for _fn in (_user32.IsIconic, _user32.IsZoomed, _user32.IsWindowVisible):
        _fn.argtypes = (wintypes.HWND,)
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _kernel32.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                     ctypes.POINTER(wintypes.DWORD))
    _kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    _kernel32.GetPriorityClass.argtypes = (wintypes.HANDLE,)
    _kernel32.SetPriorityClass.argtypes = (wintypes.HANDLE, wintypes.DWORD)

    class _MonitorInfo(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD)]

    _user32.GetMonitorInfoW.argtypes = (wintypes.HANDLE, ctypes.POINTER(_MonitorInfo))

    # shellapi.h QUERY_USER_NOTIFICATION_STATE
    _QUNS_BUSY, _QUNS_D3D, _QUNS_PRESENTATION = 2, 3, 4
    _WS_CAPTION = 0x00C00000
    # The desktop, the taskbar, alt-tab and task view: never quiet.
    _SHELL = frozenset({"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd",
                        "XamlExplorerHostIslandWindow", "MultitaskingViewFrame", "ForegroundStaging",
                        "TaskSwitcherWnd"})
    # Shell surfaces, the lock screen and screenshot overlays cover the screen for a moment.
    _SHELL_EXES = frozenset({"shellexperiencehost.exe", "startmenuexperiencehost.exe", "searchhost.exe",
                             "searchapp.exe", "lockapp.exe", "gamebar.exe", "screenclippinghost.exe",
                             "snippingtool.exe", "snipaste.exe", "pixpin.exe", "sharex.exe"})
    _PRESENTING = frozenset({"screenClass", "PodiumParent"})   # PowerPoint's slide show and presenter view
    _BELOW_NORMAL = 0x4000
    # The app's own windows (the page and its pet, in the page's process) never count.
    _OWN = os.getpid()

    # winuser.h: the events the hook follows, and the message loop.
    _EVENT_FOREGROUND, _EVENT_DESKTOP, _EVENT_LOCATION, _EVENT_NAME = 0x0003, 0x0020, 0x800B, 0x800C
    _OBJID_CARET = -8
    _QS_ALLINPUT, _PM_REMOVE, _WM_QUIT, _WM_APP, _INFINITE = 0x04FF, 1, 0x0012, 0x8000, 0xFFFFFFFF
    _EventProc = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND, wintypes.LONG,
                                    wintypes.LONG, wintypes.DWORD, wintypes.DWORD)
    _user32.SetWinEventHook.restype = wintypes.HANDLE
    _user32.SetWinEventHook.argtypes = (wintypes.DWORD, wintypes.DWORD, wintypes.HMODULE, _EventProc,
                                        wintypes.DWORD, wintypes.DWORD, wintypes.DWORD)
    _user32.UnhookWinEvent.argtypes = (wintypes.HANDLE,)
    _user32.MsgWaitForMultipleObjects.argtypes = (wintypes.DWORD, ctypes.c_void_p, wintypes.BOOL, wintypes.DWORD,
                                                  wintypes.DWORD)
    _user32.PeekMessageW.argtypes = (ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT,
                                     wintypes.UINT)
    _user32.DispatchMessageW.argtypes = (ctypes.POINTER(wintypes.MSG),)
    _user32.PostThreadMessageW.argtypes = (wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    _user32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)


class _Hook(threading.Thread):
    """Windows: the window in front, followed through the system's own window
    events on a thread with its own message loop. The hooks are out of context
    (nothing is loaded into other programs): the foreground changing anywhere,
    a switch of desktop (the lock screen, a UAC prompt, and back), and, while
    nothing holds quiet, anything moving or retitled in the program in front,
    followed in that process alone, one event per look (see SETTLE_S). Each
    sends a look (`sense`); so do the times quiet keeps: the confirming look,
    the end of the calm, and every LOOK_S while there is a signal or nothing
    in front, for a change no event shows. Nothing else wakes it."""

    def __init__(self, setting: _Setting, tell: Callable[[str, bool, bool, float], None],
                 moved: Callable[[], None]):
        super().__init__(name="mibo-front", daemon=True)
        self.setting, self.tell, self.moved = setting, tell, moved
        # The window and title in front at the last look, to tell `moved` of a change.
        self.shown = (0, "")
        self.callback = _EventProc(self._event)
        self.tid, self.ready = 0, threading.Event()
        # The process followed for moves and titles, and its hook.
        self.pid, self.followed = 0, None
        # The signal at the last look, and when a plain fullscreen window counts (CONFIRM_S after first seen).
        self.held, self.confirm_at = "", None
        # When a look last told a signal (time.time(), as `step` counts).
        self.signal_at = 0.0
        # A look to come at `next` (monotonic).
        self.next = None

    def poke(self) -> None:
        if self.ready.is_set():
            _user32.PostThreadMessageW(self.tid, _WM_APP, 0, 0)

    def stop(self) -> None:
        self.ready.wait()
        _user32.PostThreadMessageW(self.tid, _WM_QUIT, 0, 0)

    def later(self, seconds: float) -> None:
        at = time.monotonic() + seconds
        self.next = at if self.next is None else min(self.next, at)

    def run(self) -> None:
        self.tid = _kernel32.GetCurrentThreadId()
        hooks = [_user32.SetWinEventHook(event, event, None, self.callback, 0, 0, 0)
                 for event in (_EVENT_FOREGROUND, _EVENT_DESKTOP)]
        self.ready.set()
        msg = wintypes.MSG()
        try:
            self.look()
            while True:
                wait = _INFINITE if self.next is None else max(0, int((self.next - time.monotonic()) * 1000))
                _user32.MsgWaitForMultipleObjects(0, None, False, wait, _QS_ALLINPUT)
                while _user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, _PM_REMOVE):
                    if msg.message == _WM_QUIT:
                        return
                    if msg.message == _WM_APP and not msg.hWnd:
                        self.later(0)
                    _user32.DispatchMessageW(ctypes.byref(msg))
                if self.next is not None and time.monotonic() >= self.next:
                    self.look()
        finally:
            for hook in hooks:
                _user32.UnhookWinEvent(hook)
            if self.followed:
                _user32.UnhookWinEvent(self.followed)

    def _event(self, _hook, event, _hwnd, object_id, *_about) -> None:
        global _typed
        if event == _EVENT_FOREGROUND:
            self.later(0)
        elif event == _EVENT_DESKTOP:
            # Back from the lock screen or a UAC prompt the window in front may be the same, with no
            # foreground event: looked at once the desktop is back.
            self.later(SETTLE_S)
        else:
            if event == _EVENT_LOCATION and object_id == _OBJID_CARET:
                _typed = time.monotonic()
            # The program in front moved something or changed a title (made fullscreen, another tab).
            self._follow(0)
            self.later(SETTLE_S)

    def _follow(self, pid: int) -> None:
        """Moves and titles from this process alone: the one whose window is in front."""
        if pid == self.pid:
            return
        if self.followed:
            _user32.UnhookWinEvent(self.followed)
        self.pid = pid
        self.followed = (_user32.SetWinEventHook(_EVENT_LOCATION, _EVENT_NAME, None, self.callback, pid, 0, 0)
                         if pid and pid != _OWN else None)

    def look(self) -> None:
        self.next = None
        on = self.setting()
        try:
            signal, video = _sense_windows()
        except Exception:
            logger.exception("quiet: a look failed")
            signal, video = "", False
        # Moves and titles only while nothing holds quiet: a game sends them all the time, and its
        # end shows by a foreground event or the LOOK_S look.
        self._follow(0 if signal else _front["pid"])
        if (_front["hwnd"], _front["title"]) != self.shown:
            self.shown = (_front["hwnd"], _front["title"])
            self.moved()
        if signal == "fullscreen" and on and not _quiet:
            # Alt-tab, a screenshot's overlay: gone a moment later; a fullscreen video is not.
            if self.confirm_at is None:
                self.confirm_at = time.monotonic() + CONFIRM_S
            if time.monotonic() < self.confirm_at:
                self.later(self.confirm_at - time.monotonic())
                return
        self.confirm_at = None
        now = time.time()
        if not signal and self.held:
            # The signal lasted until this look: the calm counts from here.
            self.tell(self.held, video, on, now)
            self.signal_at = now
        elif signal or _quiet or video != _video:
            # Nothing at all to tell the loop otherwise, as for most looks while the person types.
            self.tell(signal, video, on, now)
            if signal:
                self.signal_at = now
        self.held = signal
        if signal or not _front["hwnd"]:
            # Nothing in front: another desktop shows (locked, a UAC prompt). Back on this one the same
            # window may come to the front with no foreground event.
            self.later(LOOK_S)
        elif _quiet or now - self.signal_at < CALM_S:
            # A look when the calm is over, whatever looked in between.
            self.later(max(0.1, self.signal_at + CALM_S + 0.1 - now))


def _image(pid: int) -> str:
    handle = _kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        return buf.value if _kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)) else ""
    finally:
        _kernel32.CloseHandle(handle)


_pid_path = (0, "")


def _sense_windows() -> tuple[str, bool]:
    """The look: what is in front, kept in `_front`, and quiet's signal for it."""
    global _front, _pid_path
    hwnd = _user32.GetForegroundWindow()
    pid = wintypes.DWORD()
    if hwnd:
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value != _pid_path[0]:
        # The program is read once per process brought to the front, not on every look.
        _pid_path = (pid.value, _image(pid.value) if pid.value else "")
    path = _pid_path[1]
    title = ctypes.create_unicode_buffer(_user32.GetWindowTextLengthW(hwnd) + 1 if hwnd else 1)
    if hwnd:
        _user32.GetWindowTextW(hwnd, title, len(title))
    signal, video = _judge(hwnd, pid.value, path, title.value) if hwnd else ("", False)
    _front = {"hwnd": hwnd or 0, "pid": pid.value, "path": path, "title": title.value, "signal": signal}
    return signal, video


def _judge(hwnd, pid: int, path: str, title: str) -> tuple[str, bool]:
    if pid == _OWN:
        return ("fullscreen", True) if _own_full else ("", False)
    cls = ctypes.create_unicode_buffer(256)
    _user32.GetClassNameW(hwnd, cls, 256)
    if cls.value in _SHELL:
        return "", False
    name = path.replace("/", "\\").rsplit("\\", 1)[-1].lower()
    if name in _SHELL_EXES:
        return "", False
    video = video_front(name, title)
    if path and game_path(path):
        return "game", video
    notice = ctypes.c_int()
    if _shell32.SHQueryUserNotificationState(ctypes.byref(notice)) == 0:
        if notice.value == _QUNS_D3D:
            return "game", video
        if notice.value == _QUNS_PRESENTATION or cls.value in _PRESENTING:
            return "presentation", video
    if _covers_monitor(hwnd) or (notice.value == _QUNS_BUSY and not _user32.IsIconic(hwnd)
                                 and not _user32.IsZoomed(hwnd)):
        return "fullscreen", video
    return "", video


def _covers_monitor(hwnd) -> bool:
    """The window fills its whole monitor and has no title bar: fullscreen. A
    maximized frameless app (WeChat, Discord) fills it too where the monitor
    has no taskbar or it hides, so a maximized window counts only when it also
    covers the taskbar's strip (a window maximized first, then made fullscreen)."""
    if _user32.IsIconic(hwnd) or not _user32.IsWindowVisible(hwnd):
        return False
    if _user32.GetWindowLongW(hwnd, -16) & _WS_CAPTION == _WS_CAPTION:   # GWL_STYLE
        return False
    rect, info = wintypes.RECT(), _MonitorInfo()
    info.cbSize = ctypes.sizeof(_MonitorInfo)
    if not _user32.GetWindowRect(hwnd, ctypes.byref(rect)) or \
            not _user32.GetMonitorInfoW(_user32.MonitorFromWindow(hwnd, 2), ctypes.byref(info)):
        return False
    mon, work = info.rcMonitor, info.rcWork
    if not (rect.left <= mon.left and rect.top <= mon.top and rect.right >= mon.right and rect.bottom >= mon.bottom):
        return False
    return not _user32.IsZoomed(hwnd) or \
        (work.left, work.top, work.right, work.bottom) != (mon.left, mon.top, mon.right, mon.bottom)


def _lower(quiet: bool) -> None:
    """Below-normal priority while quiet, the one it had before after."""
    global _priority
    if sys.platform != "win32":
        # macOS lets a process lower its priority but not raise it back.
        return
    me = _kernel32.GetCurrentProcess()
    if quiet:
        _priority = _kernel32.GetPriorityClass(me)
        _kernel32.SetPriorityClass(me, _BELOW_NORMAL)
    elif _priority:
        _kernel32.SetPriorityClass(me, _priority)


# -------------------------------------------------------------------- macOS --

if sys.platform == "darwin":
    import ctypes

    _cf = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    _cg = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
    _proc = ctypes.cdll.LoadLibrary("/usr/lib/libproc.dylib")

    class _Rect(ctypes.Structure):
        _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double), ("w", ctypes.c_double), ("h", ctypes.c_double)]

    _vp = ctypes.c_void_p
    for _fn, _res, _args in (
            (_cf.CFStringCreateWithCString, _vp, (_vp, ctypes.c_char_p, ctypes.c_uint32)),
            (_cf.CFArrayGetCount, ctypes.c_long, (_vp,)),
            (_cf.CFArrayGetValueAtIndex, _vp, (_vp, ctypes.c_long)),
            (_cf.CFDictionaryGetValue, _vp, (_vp, _vp)),
            (_cf.CFNumberGetValue, ctypes.c_bool, (_vp, ctypes.c_int, _vp)),
            (_cf.CFStringGetCString, ctypes.c_bool, (_vp, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32)),
            (_cf.CFRelease, None, (_vp,)),
            (_cg.CGWindowListCopyWindowInfo, _vp, (ctypes.c_uint32, ctypes.c_uint32)),
            (_cg.CGRectMakeWithDictionaryRepresentation, ctypes.c_bool, (_vp, ctypes.POINTER(_Rect))),
            (_cg.CGGetActiveDisplayList, ctypes.c_int32, (ctypes.c_uint32, _vp, ctypes.POINTER(ctypes.c_uint32))),
            (_cg.CGDisplayBounds, _Rect, (ctypes.c_uint32,)),
            (_proc.proc_pidpath, ctypes.c_int, (ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32))):
        _fn.restype, _fn.argtypes = _res, _args

    _UTF8 = 0x08000100
    _KEYS = {k: _cf.CFStringCreateWithCString(None, k.encode(), _UTF8)
             for k in ("kCGWindowLayer", "kCGWindowBounds", "kCGWindowOwnerPID", "kCGWindowOwnerName")}
    _OWN = os.getpid()


def _mac_int(entry, key: str) -> int:
    value = ctypes.c_int32()
    ref = _cf.CFDictionaryGetValue(entry, _KEYS[key])
    return value.value if ref and _cf.CFNumberGetValue(ref, 3, ctypes.byref(value)) else -1   # kCFNumberSInt32Type


def _sense_mac() -> tuple[str, bool]:
    windows = _cg.CGWindowListCopyWindowInfo(1 | 16, 0)   # on screen only, no desktop elements
    if not windows:
        # No window server for this process (started over ssh, or as a daemon).
        return "", False
    try:
        for i in range(_cf.CFArrayGetCount(windows)):
            entry = _cf.CFArrayGetValueAtIndex(windows, i)
            if _mac_int(entry, "kCGWindowLayer") != 0:
                continue
            pid = _mac_int(entry, "kCGWindowOwnerPID")
            if pid == _OWN:
                return "", False
            owner = ctypes.create_string_buffer(256)
            ref = _cf.CFDictionaryGetValue(entry, _KEYS["kCGWindowOwnerName"])
            if ref:
                _cf.CFStringGetCString(ref, owner, 256, _UTF8)
            video = video_front(owner.value.decode("utf-8", "replace"), "")
            path = ctypes.create_string_buffer(4096)
            if _proc.proc_pidpath(pid, path, 4096) > 0 and game_path(path.value.decode("utf-8", "replace")):
                return "game", video
            rect = _Rect()
            _cg.CGRectMakeWithDictionaryRepresentation(_cf.CFDictionaryGetValue(entry, _KEYS["kCGWindowBounds"]),
                                                       ctypes.byref(rect))
            ids, count = (ctypes.c_uint32 * 16)(), ctypes.c_uint32()
            _cg.CGGetActiveDisplayList(16, ids, ctypes.byref(count))
            for display in ids[:count.value]:
                b = _cg.CGDisplayBounds(display)
                if rect.x <= b.x and rect.y <= b.y and rect.x + rect.w >= b.x + b.w and rect.y + rect.h >= b.y + b.h:
                    return "fullscreen", video
            return "", video
        return "", False
    finally:
        _cf.CFRelease(windows)
