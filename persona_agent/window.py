"""The local page in a window of its own instead of a browser tab.

pywebview draws it: WebView2 on Windows, where it is installed with personagent,
and whatever `personagent[app]` finds on macOS and Linux. Without it, or when no
window opens, `personagent start` falls back to the browser.
"""
from __future__ import annotations

import contextlib
import hmac
import importlib.util
import json
import secrets
import signal
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Iterator
from urllib.parse import urlsplit, urlunsplit

from . import quiet

TITLE = "personagent"
ICON = Path(__file__).with_name("static") / "app"
# Windows files taskbar buttons under this, not under Python.
APP_ID = "wangkant.personagent"
SIZE = (1200, 820)
MIN_SIZE = (400, 560)
# How long the window has to appear before it counts as not opening.
SHOWN_WITHIN = 30
# How long the page has to ask for its title bar before the window takes its own back.
PAGE_WITHIN = 25
# What the page's own title bar may ask of a frameless window.
ACTIONS = ("minimize", "maximize", "restore", "close")
# The pet: a small window with nothing in it but the character.
PET_SIZE = (160, 190)
# How far from the right edge of the screen it first stands.
PET_MARGIN = 80
# How tall the strip of the figure that peeks over the app window is, from
# above its head to just under its eyes, until the page has measured the figure (CSS px).
PEEK_HEAD = 110
# How round the corners of the card beside it are: card.css's border-radius (CSS px).
CARD_RADIUS = 14
# How far left of the app window's right edge it peeks: clear of the corner,
# and of the window's buttons when it has to peek from inside (CSS px).
PEEK_INSET = 190
# How long the page takes to duck the figure out of sight, or to sink its head behind the edge.
DUCK_S = 0.24
# The app window rises into place from this far below, fading in: a quarter of a second.
RISE_PX, RISE_STEPS, RISE_STEP_S = 28, 15, 0.016
# Closed, it fades out over these steps.
FADE_STEPS, FADE_STEP_S = 8, 0.016
# How often a dragged pet catches up with the cursor, and a walking one takes a step.
DRAG_STEP_S = 0.008
WALK_STEP_S = 0.03
# winuser.h: the extended styles of a window that takes no focus and has no
# taskbar button, and of one that has a taskbar button.
_GWL_EXSTYLE, _WS_EX_NOACTIVATE, _WS_EX_TOOLWINDOW, _WS_EX_APPWINDOW = -20, 0x08000000, 0x00000080, 0x00040000
# The owner of a window that is not a child.
_GWLP_HWNDPARENT = -8
_WM_WINDOWPOSCHANGED = 0x0047
# SetWindowPos: keep focus; move only, keeping size, order and focus; keep
# order and focus; keep place, size and focus; and where in the order.
_NO_FOCUS = 0x0010
_MOVE_ONLY = 0x0001 | 0x0004 | _NO_FOCUS
_KEEP_ORDER = 0x0004 | _NO_FOCUS
_ORDER_ONLY = 0x0001 | 0x0002 | _NO_FOCUS
_HWND_TOPMOST, _HWND_NOTOPMOST = -1, -2
_RGN_OR = 2
_SW_HIDE, _SW_SHOWNOACTIVATE, _SW_RESTORE = 0, 4, 9
# Which mouse button is the primary one.
_SM_SWAPBUTTON, _VK_LBUTTON, _VK_RBUTTON = 23, 0x01, 0x02


def available() -> bool:
    try:
        return importlib.util.find_spec("webview") is not None
    except (ImportError, ValueError):
        return False


def _toolkit() -> str | None:
    """Which toolkit draws the window; None lets pywebview choose."""
    if sys.platform == "win32":
        return "edgechromium"
    # pywebview tries GTK first and prints a traceback when it is absent,
    # which it is where the app extra installed Qt.
    with contextlib.suppress(ImportError, ValueError):
        if (sys.platform.startswith("linux") and importlib.util.find_spec("gi") is None
                and importlib.util.find_spec("qtpy") is not None):
            return "qt"
    return None


def icon() -> Path:
    return ICON.with_suffix(".ico" if sys.platform == "win32" else ".png")


def alert(text: str) -> None:
    """A sentence for someone who started personagent with no terminal."""
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, TITLE, 0x30)


def _text_menus(window) -> bool:
    """pywebview turns right-click off on Windows. Put it back where there is
    text to paste into or to copy: an API key is often pasted that way.
    Also lets the page mark part of itself as the bar the window is moved by;
    True when this WebView2 can do that."""
    from System import Func, Type  # pythonnet, which pywebview has loaded

    form = window.native
    found = {"regions": False}

    def on_menu(sender, args) -> None:
        target = args.ContextMenuTarget
        args.Handled = not (target.IsEditable or target.HasSelection)

    def enable() -> None:
        core = form.browser.webview.CoreWebView2
        core.Settings.AreDefaultContextMenusEnabled = True
        core.ContextMenuRequested += on_menu
        # `app-region: drag` in the page; an older runtime has no such setting.
        with contextlib.suppress(Exception):
            core.Settings.IsNonClientRegionSupportEnabled = True
            found["regions"] = bool(core.Settings.IsNonClientRegionSupportEnabled)

    form.Invoke(Func[Type](enable))
    return found["regions"]


def _own_pages(window, origin: str) -> None:
    """Keep a Windows window on personagent's own pages. Any page it loads gets
    pywebview's bridge to Python, so nothing dropped on it loads, it goes to no
    other site, and a page's new windows open in the system browser when they
    are web addresses, never as whatever else Windows would start for them.
    The players' iframes are frames, not the window's page, and still load."""
    import webbrowser

    from System import Func, Type

    form = window.native

    def on_navigation(sender, args) -> None:
        address = urlsplit(str(args.Uri))
        args.Cancel = f"{address.scheme}://{address.netloc}" != origin

    def on_new_window(sender, args) -> None:
        args.Handled = True
        address = str(args.Uri)
        if urlsplit(address).scheme in ("http", "https"):
            webbrowser.open(address)

    def hold() -> None:
        form.browser.webview.AllowExternalDrop = False
        core = form.browser.webview.CoreWebView2
        core.NavigationStarting += on_navigation
        # pywebview's own handler gives any address at all to the system.
        core.NewWindowRequested -= form.browser.on_new_window_request
        core.NewWindowRequested += on_new_window

    form.Invoke(Func[Type](hold))


# Window messages and metrics the frameless window handles (winuser.h).
_WM_NCDESTROY, _WM_NCCALCSIZE, _WM_WINDOWPOSCHANGING = 0x0082, 0x0083, 0x0046
_SWP_NOSIZE = 0x0001
_WM_SIZE, _SIZE_RESTORED, _SIZE_MINIMIZED, _SIZE_MAXIMIZED = 0x0005, 0, 1, 2
_SM_CYSIZEFRAME, _SM_CXPADDEDBORDER = 33, 92
# shellapi.h: is there a taskbar that hides itself at this edge of this screen,
# and how far a maximized page stays from it.
_ABM_GETAUTOHIDEBAREX = 0x0000000B
_HIDDEN_TASKBAR_GAP = 2
# SetWindowPos: keep place, size and order, and work the frame out again.
_FRAME_CHANGED = 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020


def _strip_title_bar(window):
    """Take the title bar off a Windows window and leave everything else the
    system gives one: the resize borders at the sides and the bottom, the
    shadow, snapping and the taskbar entry. The page draws its own bar.

    Returns what must stay referenced while the window lives, or None when
    the title bar is still there."""
    import ctypes
    from ctypes import wintypes

    from System import Func, Type

    form = window.native
    # Libraries of our own: pywebview calls the shared ones with other argument types.
    user32, comctl32, shell32 = ctypes.WinDLL("user32"), ctypes.WinDLL("comctl32"), ctypes.WinDLL("shell32")
    result_t = ctypes.c_ssize_t
    proc_t = ctypes.WINFUNCTYPE(result_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                wintypes.LPARAM, ctypes.c_size_t, ctypes.c_size_t)

    class MonitorInfo(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT), ("work", wintypes.RECT),
                    ("flags", wintypes.DWORD)]

    class AppBar(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("hwnd", wintypes.HWND), ("message", wintypes.UINT),
                    ("edge", wintypes.UINT), ("rect", wintypes.RECT), ("lparam", wintypes.LPARAM)]

    class WindowPos(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("after", wintypes.HWND), ("x", ctypes.c_int), ("y", ctypes.c_int),
                    ("cx", ctypes.c_int), ("cy", ctypes.c_int), ("flags", wintypes.UINT)]

    comctl32.DefSubclassProc.restype = result_t
    comctl32.DefSubclassProc.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    comctl32.SetWindowSubclass.restype = wintypes.BOOL
    comctl32.SetWindowSubclass.argtypes = [wintypes.HWND, proc_t, ctypes.c_size_t, ctypes.c_size_t]
    comctl32.RemoveWindowSubclass.argtypes = [wintypes.HWND, proc_t, ctypes.c_size_t]
    user32.IsZoomed.argtypes = [wintypes.HWND]
    user32.GetDpiForWindow.argtypes = [wintypes.HWND]
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.MonitorFromWindow.restype = wintypes.HANDLE
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
    shell32.SHAppBarMessage.restype = ctypes.c_size_t
    shell32.SHAppBarMessage.argtypes = [wintypes.DWORD, ctypes.POINTER(AppBar)]

    def frame_height(hwnd) -> int:
        dpi = user32.GetDpiForWindow(hwnd) or 96
        return (user32.GetSystemMetricsForDpi(_SM_CYSIZEFRAME, dpi)
                + user32.GetSystemMetricsForDpi(_SM_CXPADDEDBORDER, dpi))

    def leave_hidden_taskbar(hwnd, rect) -> None:
        """A page that covers the whole screen counts as full screen, and a
        taskbar set to hide itself would never come back: stop short of its edge."""
        info = MonitorInfo()
        info.size = ctypes.sizeof(MonitorInfo)
        if not user32.GetMonitorInfoW(user32.MonitorFromWindow(hwnd, 2), ctypes.byref(info)):
            return
        for edge, side, step in ((0, "left", 1), (1, "top", 1), (2, "right", -1), (3, "bottom", -1)):
            bar = AppBar()
            bar.size, bar.edge, bar.rect = ctypes.sizeof(AppBar), edge, info.monitor
            if shell32.SHAppBarMessage(_ABM_GETAUTOHIDEBAREX, ctypes.byref(bar)):
                setattr(rect, side, getattr(rect, side) + step * _HIDDEN_TASKBAR_GAP)

    # Back from the taskbar or from maximized, WinForms sizes the window once
    # more from its page as if it had a title bar: a bar's height taller each
    # time. That one change keeps the size the system brought it back at.
    back = {"away": False, "size": None}

    def proc(hwnd, message, wparam, lparam, _subclass, _data):
        if message == _WM_SIZE:
            if wparam in (_SIZE_MINIMIZED, _SIZE_MAXIMIZED):
                back["away"] = True
            elif back["away"]:
                back["away"] = False
                if wparam == _SIZE_RESTORED:
                    rect = wintypes.RECT()
                    user32.GetWindowRect(hwnd, ctypes.byref(rect))
                    back["size"] = (rect.right - rect.left, rect.bottom - rect.top)
        elif message == _WM_WINDOWPOSCHANGING and back["size"]:
            pos = ctypes.cast(ctypes.c_void_p(lparam), ctypes.POINTER(WindowPos))[0]
            (wide, high), back["size"] = back["size"], None
            if not pos.flags & _SWP_NOSIZE and pos.cx == wide and pos.cy > high:
                pos.cy = high
        if message == _WM_NCCALCSIZE and wparam:
            # The system works out the sides and the bottom; the top stays where
            # the window begins, so there is no title bar. A maximized window
            # reaches past the screen by its frame, and the top comes back in.
            rect = ctypes.cast(ctypes.c_void_p(lparam), ctypes.POINTER(wintypes.RECT))
            top = rect[0].top
            result = comctl32.DefSubclassProc(hwnd, message, wparam, lparam)
            if result == 0:
                with contextlib.suppress(Exception):
                    zoomed = bool(user32.IsZoomed(hwnd))
                    rect[0].top = top + (frame_height(hwnd) if zoomed else 0)
                    if zoomed:
                        leave_hidden_taskbar(hwnd, rect[0])
            return result
        if message == _WM_NCDESTROY:
            comctl32.RemoveWindowSubclass(hwnd, callback, 1)
        return comctl32.DefSubclassProc(hwnd, message, wparam, lparam)

    callback = proc_t(proc)
    done = {"ok": False}

    def install() -> None:
        hwnd = form.Handle.ToInt64()
        if comctl32.SetWindowSubclass(hwnd, callback, 1, 0):
            user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, _FRAME_CHANGED)
            done["ok"] = True

    def undo() -> None:
        """Give the window its title bar back."""
        def remove() -> None:
            hwnd = form.Handle.ToInt64()
            comctl32.RemoveWindowSubclass(hwnd, callback, 1)
            user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, _FRAME_CHANGED)
        form.Invoke(Func[Type](remove))

    # Called from the window's own thread before it shows, so no title bar is ever drawn.
    install()
    return (callback, undo) if done["ok"] else None


def _watch_moves(hwnd: int, moved: Callable[[], None]):
    """Call `moved` on the window's own thread each time it has moved, changed
    size, shown or hidden: in the same instant, not on a timer that trails it.
    Called on that thread; returns what must stay referenced while the window lives."""
    import ctypes
    from ctypes import wintypes

    comctl32 = ctypes.WinDLL("comctl32")
    result_t = ctypes.c_ssize_t
    proc_t = ctypes.WINFUNCTYPE(result_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                wintypes.LPARAM, ctypes.c_size_t, ctypes.c_size_t)
    comctl32.DefSubclassProc.restype = result_t
    comctl32.DefSubclassProc.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    comctl32.SetWindowSubclass.argtypes = [wintypes.HWND, proc_t, ctypes.c_size_t, ctypes.c_size_t]
    comctl32.RemoveWindowSubclass.argtypes = [wintypes.HWND, proc_t, ctypes.c_size_t]

    def proc(hwnd, message, wparam, lparam, _subclass, _data):
        # The window is where it is going first, then what goes with it follows.
        result = comctl32.DefSubclassProc(hwnd, message, wparam, lparam)
        if message == _WM_WINDOWPOSCHANGED:
            moved()
        elif message == _WM_NCDESTROY:
            comctl32.RemoveWindowSubclass(hwnd, callback, 2)
        return result

    callback = proc_t(proc)
    # 2: the title bar's own handler is 1.
    comctl32.SetWindowSubclass(hwnd, callback, 2, 0)
    return callback


def _user32():
    """user32 with the argument types the pet's calls need: a library of our
    own, as pywebview calls the shared one with other types."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32")
    hwnd = wintypes.HWND
    user32.GetWindowRect.argtypes = user32.GetClientRect.argtypes = [hwnd, ctypes.POINTER(wintypes.RECT)]
    user32.ClientToScreen.argtypes = [hwnd, ctypes.POINTER(wintypes.POINT)]
    user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.restype = ctypes.c_short
    user32.IsWindowVisible.argtypes = user32.IsIconic.argtypes = [hwnd]
    user32.ShowWindow.argtypes = [hwnd, ctypes.c_int]
    user32.SetWindowPos.argtypes = [hwnd, hwnd, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    wintypes.UINT]
    user32.GetWindowLongW.argtypes = [hwnd, ctypes.c_int]
    user32.SetWindowLongW.argtypes = [hwnd, ctypes.c_int, wintypes.LONG]
    user32.SetWindowLongPtrW.argtypes = [hwnd, ctypes.c_int, ctypes.c_ssize_t]
    user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetForegroundWindow.argtypes = [hwnd]
    user32.SetWindowRgn.argtypes = [hwnd, wintypes.HANDLE, wintypes.BOOL]
    return user32


@contextlib.contextmanager
def _interrupt(stop: Callable[[], None]) -> Iterator[None]:
    """Ctrl+C calls `stop` at once. The main thread sits in the window's own
    loop, where a Python signal handler would wait for it to come back."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    reader, writer = socket.socketpair()
    writer.setblocking(False)

    def wait() -> None:
        with contextlib.suppress(OSError):
            if reader.recv(1):
                stop()

    handler = signal.signal(signal.SIGINT, lambda *_: None)
    wakeup = signal.set_wakeup_fd(writer.fileno(), warn_on_full_buffer=False)
    threading.Thread(target=wait, name="personagent-interrupt", daemon=True).start()
    try:
        yield
    finally:
        signal.set_wakeup_fd(wakeup)
        signal.signal(signal.SIGINT, handler)
        writer.close()
        reader.close()


class _PetApi:
    """What the pet's page may ask of its window."""

    def __init__(self, owner: "AppWindow"):
        self._owner = owner

    def open(self) -> None:
        self._owner.show()

    def menu(self) -> None:
        self._owner._pet_menu()

    def walk(self, dx: float, ms: float) -> None:
        """A walk of `ms` milliseconds, `dx` CSS px a step; back when it ends."""
        self._owner._pet_walk(dx, ms)

    def rest(self) -> None:
        """Stop walking now: pressed, or a card is coming."""
        self._owner._walking = False

    def drag(self, x: float, y: float) -> None:
        """The pet's window follows the cursor until the button is let go,
        held where it was pressed: (x, y) CSS px inside it."""
        self._owner._pet_drag(x, y)

    def drop(self) -> None:
        self._owner._dragging = False

    def pose(self) -> str:
        """standing; leaving the ground, peeking over the app window, or returning."""
        return self._owner._pose

    def figure(self) -> str:
        return self._owner.figure()

    def measured(self, head: float, outline: list) -> None:
        """How tall the strip of this figure that peeks over the window is, and
        where the figure is drawn in its 160 by 190 box, room for its moves
        included: [left, top, right, bottom]. CSS px."""
        self._owner._pet_measured(head, outline)

    def card(self, width: float, height: float, box: list | None = None) -> str:
        return self._owner._pet_card(width, height, box)

    def open_at(self, target: str) -> None:
        self._owner.open_at(target)


class AppWindow:
    """One window on `url`. `confirm` returns the question to ask before the
    window closes, or "" to close without asking. While `background` says so,
    closing hides the window behind a notification-area icon instead, where
    the system has one for us (Windows); `words` names that icon's menu.

    With `pet` (Windows), personagent starts as the character alone on the
    desktop: the window stays hidden until the pet is double-clicked, and
    closing it hides it again. The pet's menu quits, and chooses the figure
    among `figures` ([(key, label)]) through `choose`; `figure` says which it
    is. While the window shows, the pet peeks over its top edge and goes
    wherever the window goes."""

    def __init__(self, url: str, *, storage: Path, confirm: Callable[[], str] = lambda: "",
                 background: Callable[[], bool] = lambda: False,
                 words: Callable[[], dict] = lambda: {}, start_hidden: bool = False,
                 pet: bool = False, figure: Callable[[], str] = lambda: "",
                 figures: Callable[[], list[tuple[str, str]]] = lambda: [],
                 choose: Callable[[str], object] = lambda key: None):
        self.url = url
        self.storage = storage
        self.confirm = confirm
        self.background = background
        self.words = words
        self.start_hidden = start_hidden
        self.pet = pet and sys.platform == "win32"
        self.figure = figure
        self.figures = figures
        self.choose = choose
        self._pet = None
        self._pet_strip = None
        self._pet_hwnd = self._main_hwnd = 0
        self._pet_scale = 1.0
        self._user32 = None
        # standing on the ground; leaving it, peeking over the app window's top
        # edge, or returning to the ground. The pet's page is told each change.
        self._pose = "standing"
        # The pet's window is held on the app window's edge: owned by it and moved with it.
        self._attached = False
        # Where the pet's window stood on the ground: its left and its bottom.
        self._ground = (0, 0)
        # How tall the peeking pet's window is, CSS px; the page measures each figure.
        self._head = PEEK_HEAD
        # Where the figure is drawn in its box, room for its moves included, and
        # where the card is: the window takes the pointer over these alone.
        self._outline = (0, 0, *PET_SIZE)
        self._card_box = (0, 0, 0, 0)
        # One way at a time: to the window or back to the ground.
        self._turn = threading.Lock()
        self._dragging = False
        self._walking = False
        # The app window's move handler; .NET holds no reference.
        self._watch = None
        # Which side of the figure a card is open on: "left", "right", or "" for none.
        self._card = ""
        # Where the pet asked the window's page to go, until the page takes it.
        self._goto = ""
        # Out of sight while a game or something full screen is in front (quiet.py).
        # The tray brings it back, and then it stays until quiet starts again.
        self._hushed = False
        self._by_hand = False
        self._hush = threading.Lock()
        # Menu handlers stay referenced here, or .NET would lose them.
        self._open_click = lambda sender, event: self.show()
        self._pet_click = lambda sender, event: self._show_pet()
        self._quit_click = lambda sender, event: self.close()
        self._figure_click = lambda sender, event: (self.choose(str(sender.Tag)), self.refigure())
        self.opened = False
        # Why no window opened, for the log.
        self.error = ""
        self.hidden = False
        self._window = None
        self._leaving = False
        self._tray = None
        self._told = False
        # A window started for the background is created minimized.
        self._minimized = start_hidden
        #: The window has no title bar of its own: the page draws the bar and its buttons.
        self.frameless = False
        self.maximized = False
        # The frameless window's message handler and how to undo it; .NET holds no reference.
        self._frame = None
        self._frame_seen = threading.Event()
        # Only the page inside this window knows it: a browser tab on the same
        # address neither draws the window's bar nor presses its buttons.
        self.frame_key = secrets.token_urlsafe(16)

    @property
    def can_hide(self) -> bool:
        """Closing can leave personagent running behind an icon."""
        return self._tray is not None

    def show(self) -> bool:
        """Bring the window back in front; False when there is none. With the
        pet, the window comes up where the pet was and the pet peeks over it."""
        if not self.opened or self._leaving:
            return False
        if self._pet is not None:
            if self._attached:
                self._on_ui(self._window.native.Activate)
            else:
                threading.Thread(target=self._go_in, name="personagent-pet", daemon=True).start()
            return True
        try:
            # Only out of the taskbar: restoring a maximized window would shrink it.
            if self._minimized:
                self._window.restore()
            if self.hidden:
                self._page_seen(True)
            self._window.show()
            if self.hidden:
                self.hidden = False
                if self._tray is not None:
                    self._on_ui(lambda: setattr(self._tray, "Visible", False))
        except Exception:
            return False
        return True

    def hide(self) -> bool:
        """Leave the window for the notification area; False when it cannot."""
        if self._tray is None or not self.opened or self._leaving:
            return False
        words = {"still": "", **self.words()}

        def away() -> None:
            self._tray.Visible = True
            if not self._told and words["still"]:
                self._told = True
                self._tray.ShowBalloonTip(5000, TITLE, words["still"], self._tray_info)

        try:
            self._page_seen(False)
            self._window.hide()
            self.hidden = True
            self._on_ui(away)
        except Exception:
            return False
        return True

    def open_at(self, target: str) -> bool:
        """Show the window with its page asked to go to `target` ("feed/<id>", "feed" or "chat")."""
        self._goto = str(target or "")
        shown = self.show()
        # A window already in front learns it from this, one coming up from showing.
        self._frame_changed()
        return shown

    # What the pages are told as it happens, so they need not keep asking (pet.js, app.js).

    def _tell(self, view, script: str) -> None:
        """Run `script` in a window's page, on a thread of its own: whoever
        tells it, the page's server among them, never waits for the page."""
        threading.Thread(target=lambda: view.evaluate_js(script), name="personagent-tell", daemon=True).start()

    def _page_seen(self, seen: bool) -> None:
        """The app window's WebView told it shows or is hidden in the
        notification area, before the window itself goes (as in _put_away):
        its page then knows it is hidden (document.hidden) and stops asking."""
        view = self._window.native.browser.webview
        self._on_ui(lambda: setattr(view, "Visible", seen))

    def _frame_changed(self) -> None:
        if self.opened:
            self._tell(self._window, "window.paFrame && paFrame()")

    def pet_look(self) -> None:
        """A line or something found is waiting for the pet: it looks now."""
        if self.opened and self._pet is not None and not self._hushed:
            self._tell(self._pet, "petLook()")

    def refigure(self) -> None:
        """The figure may have changed: the pet and the app window read it again.
        A hushed pet reads it when it wakes."""
        if self.opened and self._pet is not None and not self._hushed:
            self._tell(self._pet, "petFigure()")
        self._frame_changed()

    def chats_changed(self) -> None:
        """A chat changed (a reply, a remark, something shared or delivered):
        the app window's page looks now, unless it is hidden."""
        if self.opened and not self.hidden:
            self._tell(self._window, "window.paChats && paChats()")

    def take_goto(self) -> str:
        """Where the page was asked to go, once."""
        target, self._goto = self._goto, ""
        return target

    def close(self) -> None:
        self._leaving = True
        for window in (self._pet, self._window):
            if window is not None:
                with contextlib.suppress(Exception):
                    window.destroy()

    @property
    def pet_url(self) -> str:
        address = urlsplit(self.url)
        return urlunsplit((address.scheme, address.netloc, "/pet", "", address.fragment))

    def _shown(self) -> bool:
        return bool(self._user32.IsWindowVisible(self._main_hwnd) and not self._user32.IsIconic(self._main_hwnd))

    def _set_pose(self, pose: str) -> None:
        """Tell the pet's page; it ducks, peeks, sinks or pops up for it (pet.js)."""
        self._pose = pose
        self._pet.evaluate_js(f"petPose({json.dumps(pose)})")

    def _go_in(self) -> None:
        """The pet ducks out of sight, the window rises into its place, and the
        pet's head comes up over the window's top edge."""
        if not self._turn.acquire(blocking=False):
            return
        try:
            if self._attached or self._leaving:
                return
            self._set_pose("leaving")
            self._on_pet(self._leave_ground)
            time.sleep(DUCK_S)
            if self._user32.IsIconic(self._main_hwnd):
                # Back from the taskbar as it was, maximized or not.
                self._user32.ShowWindow(self._main_hwnd, _SW_RESTORE)
            if self.hidden:
                self._page_seen(True)
            if self._shown():
                self._window.show()
            else:
                self._rise()
            self.hidden = False
            self._on_ui(self._attach)
            self._set_pose("peek")
        finally:
            self._turn.release()

    def _go_out(self, how: str) -> None:
        """The pet's head sinks behind the edge, the window goes ("hide" or
        "minimize"; "gone" when it went by itself), and the pet pops back up on
        the ground where it stood."""
        with self._turn:
            if how == "gone" and not self._attached:
                return
            out = self._attached
            if out and how != "gone":
                self._set_pose("returning")
                time.sleep(DUCK_S)
            # Let go first: the window going is no longer the pet's to follow.
            self._attached = False
            if how == "hide":
                self._fade_out()
                self.hidden = True
            elif how == "minimize":
                self._window.minimize()
            if out:
                self._set_pose("returning")
                self._on_pet(self._land)
                self._set_pose("standing")

    def _moved(self) -> None:
        """On the app window's thread, each time it moved, changed size, showed or hid."""
        if self._leaving:
            return
        shown = self._shown()
        if self._attached and shown:
            self._hold()
        elif (self._attached or (shown and self._pose == "standing")) and not self._turn.locked():
            # Minimized or shown again from the taskbar, not by the pet or the page.
            work = (lambda: self._go_out("gone")) if self._attached else self._go_in
            threading.Thread(target=work, name="personagent-pet", daemon=True).start()

    def _rise(self) -> None:
        """The window comes up into its place from a little below, fading in."""
        from System.Drawing import Point

        form = self._window.native
        place = {}

        def begin() -> None:
            # A maximized window has nowhere to rise from: it only fades in.
            lift = 0 if self.maximized else round(RISE_PX * form._scale)
            place["at"], place["lift"] = (form.Left, form.Top), lift
            form.Opacity = 0
            form.Location = Point(form.Left, form.Top + lift)

        def step(share: float) -> None:
            (left, top), lift = place["at"], place["lift"]
            form.Location = Point(left, top + round(lift * (1 - share)))
            form.Opacity = share

        self._on_ui(begin)
        self._window.show()
        for i in range(1, RISE_STEPS + 1):
            self._on_ui(lambda share=1 - (1 - i / RISE_STEPS) ** 3: step(share))
            time.sleep(RISE_STEP_S)

    def _fade_out(self) -> None:
        form = self._window.native
        for i in range(FADE_STEPS - 1, -1, -1):
            self._on_ui(lambda share=i / FADE_STEPS: setattr(form, "Opacity", share))
            time.sleep(FADE_STEP_S)
        self._page_seen(False)
        self._window.hide()
        self._on_ui(lambda: setattr(form, "Opacity", 1.0))

    def _restyle(self) -> None:
        """No focus and no taskbar button for the pet's window: WinForms marks
        it as one that belongs on the taskbar, and an owner or a change of
        order must not bring the button back."""
        user32, pet = self._user32, self._pet_hwnd
        style = user32.GetWindowLongW(pet, _GWL_EXSTYLE)
        user32.SetWindowLongW(pet, _GWL_EXSTYLE, (style | _WS_EX_NOACTIVATE | _WS_EX_TOOLWINDOW) & ~_WS_EX_APPWINDOW)

    def _leave_ground(self) -> None:
        """On the pet's thread: put any card away and keep where it stood."""
        self._fit_card(0, 0)
        form = self._pet.native
        self._ground = (form.Left, form.Bottom)

    def _peek_spot(self) -> tuple[int, int, int, int]:
        """Where the peeking pet's window goes: its bottom on the app window's
        top edge, towards the right. Where there is no room above (maximized,
        or at the top of the screen) it stays there and runs off the screen."""
        from ctypes import byref, wintypes

        user32, main, form = self._user32, self._main_hwnd, self._window.native
        origin, page, outer = wintypes.POINT(0, 0), wintypes.RECT(), wintypes.RECT()
        user32.ClientToScreen(main, byref(origin))
        user32.GetClientRect(main, byref(page))
        # A window with its own title bar begins above its page.
        user32.GetWindowRect(main, byref(outer))
        edge = origin.y if self.frameless else outer.top
        wide, high = round(PET_SIZE[0] * self._pet_scale), round(self._head * self._pet_scale)
        left = max(origin.x, origin.x + page.right - wide - round(PEEK_INSET * form._scale))
        return left, edge - high, wide, high

    def _hold(self, front: bool = False) -> None:
        """On the app window's thread: the pet's window to its spot on the edge,
        and with `front` just above the app window in the order."""
        left, top, wide, high = self._peek_spot()
        self._user32.SetWindowPos(self._pet_hwnd, None, left, top, wide, high,
                                  _NO_FOCUS if front else _KEEP_ORDER)

    def _attach(self) -> None:
        """On the app window's thread: the pet's window is handed to the app
        window. Owned by it, it stays just above it and goes behind other apps
        with it, no longer on top of everything."""
        user32, pet = self._user32, self._pet_hwnd
        # Changed while hidden: changed while it shows, the window's see-through
        # parts come out white, and stay so until it is shown again. The pet is
        # out of sight below its window's bottom meanwhile (pet.js).
        user32.ShowWindow(pet, _SW_HIDE)
        user32.SetWindowPos(pet, _HWND_NOTOPMOST, 0, 0, 0, 0, _ORDER_ONLY)
        user32.SetWindowLongPtrW(pet, _GWLP_HWNDPARENT, self._main_hwnd)
        self._restyle()
        self._attached = True
        self._hold(front=True)
        self._shape()
        if not self._hushed:
            user32.ShowWindow(pet, _SW_SHOWNOACTIVATE)

    def _land(self) -> None:
        """On the pet's thread: back on the ground where it stood, on top of everything."""
        user32, pet, scale = self._user32, self._pet_hwnd, self._pet_scale
        # As in _attach.
        user32.ShowWindow(pet, _SW_HIDE)
        user32.SetWindowLongPtrW(pet, _GWLP_HWNDPARENT, 0)
        user32.SetWindowPos(pet, _HWND_TOPMOST, 0, 0, 0, 0, _ORDER_ONLY)
        self._restyle()
        wide, high = int(PET_SIZE[0] * scale), int(PET_SIZE[1] * scale)
        left, bottom = self._ground
        user32.SetWindowPos(pet, None, left, bottom - high, wide, high, _KEEP_ORDER)
        self._shape()
        if not self._hushed:
            user32.ShowWindow(pet, _SW_SHOWNOACTIVATE)

    def _pet_measured(self, head: float, outline: list) -> None:
        self._head, self._outline = max(1, round(head)), tuple(outline)
        self._on_pet(self._reshape)

    def _reshape(self) -> None:
        """Another figure: its window cut to it again. Shown anew after, as a
        new figure leaves the see-through parts white too (see _attach)."""
        if not self._pet_hwnd:
            # The page measured it before the window was placed, which cuts it then.
            return
        self._user32.ShowWindow(self._pet_hwnd, _SW_HIDE)
        if self._attached:
            self._hold()
        self._shape()
        if not self._hushed:
            self._user32.ShowWindow(self._pet_hwnd, _SW_SHOWNOACTIVATE)

    def _quiet_changed(self, state: dict) -> None:
        """quiet.py, on its own loop: a game or something full screen came to the front, or went."""
        if state["quiet"]:
            self._by_hand = False
        threading.Thread(target=self._hush_pet if state["quiet"] else self._wake_pet,
                         name="personagent-quiet", daemon=True).start()
        # The app window's page, open behind the game, asks nothing meanwhile either (app.js).
        if self.opened:
            self._tell(self._window, f"window.paQuiet && paQuiet({json.dumps(state['quiet'])})")

    def _show_pet(self) -> None:
        """The tray's "Show the pet": the person's choice holds until quiet starts again."""
        self._by_hand = True
        threading.Thread(target=self._wake_pet, name="personagent-quiet", daemon=True).start()

    def _hush_pet(self) -> None:
        """The pet ducks out of sight and its window hides, out of alt-tab and
        the taskbar, its page stilled; the tray icon can bring it back.
        Both this and _wake_pet go by quiet as it is when they run, not by
        the event that started them, so a quick on-off ends shown."""
        with self._hush:
            if self._hushed or self._leaving or self._by_hand or not quiet.active():
                return
            self._pet.evaluate_js("petQuiet(true)")
            time.sleep(DUCK_S)
            self._on_pet(self._put_away)
            if self._tray is not None:
                self._on_ui(lambda: setattr(self._tray, "Visible", True))

    def _wake_pet(self) -> None:
        """Back where it was, on the ground or over the app window: its window
        shows with the figure still out of sight, and the figure comes up."""
        with self._hush:
            if not self._hushed or self._leaving or (quiet.active() and not self._by_hand):
                return
            self._on_pet(self._bring_back)
            self._pet.evaluate_js("petQuiet(false)")
            if self._tray is not None:
                self._on_ui(lambda: setattr(self._tray, "Visible", False))

    def _put_away(self) -> None:
        """On the pet's thread, which is the app window's too: _attach, _land,
        _reshape and _fit_card show the pet's window unless it is hushed.
        The WebView is hidden first: hidden after its window, it would never
        learn it is out of sight, and only a WebView that knows suspends.
        Then it keeps little memory and stops its page."""
        self._hushed = True
        view = self._pet.native.browser.webview
        view.Visible = False
        self._user32.ShowWindow(self._pet_hwnd, _SW_HIDE)
        # An older WebView2 runtime has neither.
        with contextlib.suppress(Exception):
            from Microsoft.Web.WebView2.Core import CoreWebView2MemoryUsageTargetLevel
            view.CoreWebView2.MemoryUsageTargetLevel = CoreWebView2MemoryUsageTargetLevel.Low
            view.CoreWebView2.TrySuspendAsync()

    def _bring_back(self) -> None:
        """On the pet's thread: the window first, then the WebView, which wakes
        its page by showing (see _put_away). Nothing white shows between: the
        window alone is see-through, and the page last drew the figure ducked."""
        self._hushed = False
        view = self._pet.native.browser.webview
        with contextlib.suppress(Exception):
            from Microsoft.Web.WebView2.Core import CoreWebView2MemoryUsageTargetLevel
            view.CoreWebView2.MemoryUsageTargetLevel = CoreWebView2MemoryUsageTargetLevel.Normal
        self._user32.ShowWindow(self._pet_hwnd, _SW_SHOWNOACTIVATE)
        view.Visible = True

    def _shape(self) -> None:
        """On the pet's thread: the pet's window shows anything, and takes the
        pointer, only over the figure and the card; everywhere else a click
        goes through to whatever is behind. A window region does it: the
        system goes by it alone, whatever the page draws."""
        import ctypes
        from ctypes import byref, wintypes

        user32, pet, scale = self._user32, self._pet_hwnd, self._pet_scale
        box = wintypes.RECT()
        user32.GetWindowRect(pet, byref(box))
        wide, high = box.right - box.left, box.bottom - box.top
        x0, y0, x1, y1 = (round(v * scale) for v in self._outline)
        # Each part: left, top, right, bottom, and how round its corners are.
        if self._attached:
            # The strip over the window's edge: as wide as the figure, all of its height.
            parts = [(x0, 0, x1, high, 0)]
        else:
            # The figure keeps the window's bottom corner (pet.css).
            fx = wide - round(PET_SIZE[0] * scale) if self._card == "left" else 0
            fy = high - round(PET_SIZE[1] * scale)
            parts = [(fx + x0, fy + y0, fx + x1, fy + y1, 0)]
            if self._card:
                cx, cy, cw, ch = (round(v * scale) for v in self._card_box)
                if self._card == "right":
                    cx = wide - cx - cw
                # Round as the card is: the see-through corners outside it come
                # out white where they touch the window's side.
                parts.append((cx, cy, cx + cw, cy + ch, round(2 * CARD_RADIUS * scale)))
        gdi32 = ctypes.WinDLL("gdi32")
        gdi32.CreateRectRgn.restype = gdi32.CreateRoundRectRgn.restype = wintypes.HANDLE
        gdi32.CombineRgn.argtypes = [wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE, ctypes.c_int]
        gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
        region = gdi32.CreateRectRgn(0, 0, 0, 0)
        for *part, corner in parts:
            more = gdi32.CreateRoundRectRgn(*part, corner, corner) if corner else gdi32.CreateRectRgn(*part)
            gdi32.CombineRgn(region, region, more, _RGN_OR)
            gdi32.DeleteObject(more)
        # The system owns the region from here on.
        user32.SetWindowRgn(pet, region, True)

    def _pet_drag(self, x: float, y: float) -> None:
        """Move the pet's window with the cursor, the point (x, y) CSS px of it
        under the cursor, until the primary button is up or the page says it
        was let go. Read from the cursor itself, so the window keeps up however
        fast the hand moves."""
        from ctypes import byref, wintypes

        user32, pet, scale = self._user32, self._pet_hwnd, self._pet_scale
        if self._pose != "standing":
            return
        button = _VK_RBUTTON if user32.GetSystemMetrics(_SM_SWAPBUTTON) else _VK_LBUTTON
        held, at = (round(x * scale), round(y * scale)), wintypes.POINT()
        self._dragging = True
        while self._dragging and user32.GetAsyncKeyState(button) & 0x8000 and self._pose == "standing":
            user32.GetCursorPos(byref(at))
            user32.SetWindowPos(pet, None, at.x - held[0], at.y - held[1], 0, 0, _MOVE_ONLY)
            time.sleep(DRAG_STEP_S)
        self._dragging = False

    def _on_pet(self, action: Callable[[], None]) -> None:
        from System import Func, Type

        def run() -> None:
            action()

        self._pet.native.Invoke(Func[Type](run))

    def _place_pet(self) -> None:
        """Cut the pet's window down to the figure and stand it on the taskbar,
        near the right edge."""
        import ctypes
        from ctypes import byref, wintypes

        from System.Drawing import Color, Size
        from System.Windows.Forms import Screen

        form = self._pet.native

        def place() -> None:
            scale = form._scale
            form.Hide()
            form.MinimumSize = Size(1, 1)
            form.Size = Size(int(PET_SIZE[0] * scale), int(PET_SIZE[1] * scale))
            # pywebview leaves the form's own grey behind a transparent page. With
            # the window's glass over all of it, black there is see-through and
            # the page is drawn over the desktop as it is. A colour key would do
            # that too, but the system takes clicks by the window's own pixels
            # then, which WebView2 stops drawing into once the window is resized.
            form.BackColor = Color.Black
            self._pet_hwnd, self._pet_scale = form.Handle.ToInt64(), scale
            dwmapi = ctypes.WinDLL("dwmapi")
            dwmapi.DwmExtendFrameIntoClientArea.argtypes = [wintypes.HWND, ctypes.c_void_p]
            dwmapi.DwmExtendFrameIntoClientArea(self._pet_hwnd, byref((ctypes.c_int * 4)(-1, -1, -1, -1)))
            self._restyle()
            area = Screen.FromControl(form).WorkingArea
            form.Left = area.Right - form.Width - int(PET_MARGIN * scale)
            form.Top = area.Bottom - form.Height
            self._shape()
            form.Show()

        self._on_pet(place)

    def _watch_window(self) -> None:
        """On the app window's thread: follow its every move from now on."""
        self._main_hwnd = self._window.native.Handle.ToInt64()
        self._watch = _watch_moves(self._main_hwnd, self._moved)

    def _pet_walk(self, dx: float, ms: float) -> None:
        """The pet walks sideways, `dx` CSS px every WALK_STEP_S for `ms`
        milliseconds, and turns round where the screen ends (the page is told,
        to face the other way). It stops when pressed or a card comes (rest),
        or when it leaves the ground or is hushed. One call from the page per walk."""
        from System.Windows.Forms import Screen

        form = self._pet.native
        walk = {"dx": 0, "turned": False}

        def begin() -> None:
            area = Screen.FromControl(form).WorkingArea
            walk.update(dx=round(dx * form._scale), low=area.Left, high=area.Right - form.Width)

        def step() -> None:
            # On the pet's thread, so a card's resize never lands between a step's read and its move.
            if not self._walking or self._pose != "standing" or self._hushed:
                self._walking = False
                return
            left = min(max(form.Left + walk["dx"], walk["low"]), walk["high"])
            if left == form.Left:
                walk["dx"], walk["turned"] = -walk["dx"], True
            form.Left = left

        self._on_pet(begin)
        self._walking = True
        end = time.monotonic() + ms / 1000
        while self._walking and time.monotonic() < end:
            self._on_pet(step)
            if walk["turned"]:
                walk["turned"] = False
                self._pet.evaluate_js(f"petTurn({json.dumps(walk['dx'] < 0)})")
            time.sleep(WALK_STEP_S)
        self._walking = False

    def _fit_card(self, width: float, height: float) -> None:
        """On the pet's thread: grow its window to `width` by `height` CSS px
        for a card beside the figure, or with 0 shrink it back to the figure.
        The figure stays where it is on screen: the window grows away from it,
        up and to the left, or to the right where the screen ends on the left."""
        from System.Windows.Forms import Screen

        form = self._pet.native
        scale = form._scale
        wide, high = int(PET_SIZE[0] * scale), int(PET_SIZE[1] * scale)
        left = form.Right - wide if self._card == "left" else form.Left
        bottom = form.Bottom
        grow = bool(width and height and self._pose == "standing")
        if not grow and not self._card:
            return
        # Resized while it shows, its see-through parts can come out white (see _attach).
        self._user32.ShowWindow(self._pet_hwnd, _SW_HIDE)
        if grow:
            width, height = max(wide, int(width * scale)), max(high, int(height * scale))
            self._card = "left" if left + wide - width >= Screen.FromControl(form).WorkingArea.Left else "right"
            form.SetBounds(left + wide - width if self._card == "left" else left, bottom - height, width, height)
        else:
            self._card = ""
            form.SetBounds(left, bottom - high, wide, high)
        self._shape()
        if not self._hushed:
            self._user32.ShowWindow(self._pet_hwnd, _SW_SHOWNOACTIVATE)

    def _pet_card(self, width: float, height: float, box: list | None = None) -> str:
        """Room for a card beside the figure (0 to take it away), and which side
        of the figure it is on: "left", "right", or "" when there is none.
        `box` is where the card is in the grown window, CSS px, as it is on
        the left of the figure: [x, y, width, height]."""
        if box:
            self._card_box = tuple(box)
        # A walk under way stops first: its steps would move the window the card resizes.
        self._walking = False
        self._on_pet(lambda: self._fit_card(width, height))
        return self._card

    def _pet_menu(self) -> None:
        import ctypes

        from System.Windows.Forms import ContextMenuStrip, Cursor, ToolStripMenuItem, ToolStripSeparator

        words = {"open": "Open personagent", "quit": "Quit", **self.words()}
        figures, current = self.figures(), self.figure()
        form = self._pet.native

        def item(label: str, handler) -> ToolStripMenuItem:
            entry = ToolStripMenuItem(label)
            entry.Click += handler
            return entry

        def show() -> None:
            # Made anew each time: the tick moves with the figure chosen.
            if self._pet_strip is not None:
                self._pet_strip.Dispose()
            menu = ContextMenuStrip()
            menu.Items.Add(item(words["open"], self._open_click))
            menu.Items.Add(ToolStripSeparator())
            for key, label in figures:
                entry = item(label, self._figure_click)
                entry.Tag, entry.Checked = key, key == current
                menu.Items.Add(entry)
            menu.Items.Add(ToolStripSeparator())
            menu.Items.Add(item(words["quit"], self._quit_click))
            self._pet_strip = menu
            # A menu with no foreground window behind it stays open when clicked away from.
            ctypes.windll.user32.SetForegroundWindow(form.Handle.ToInt64())
            menu.Show(Cursor.Position)

        self._on_pet(show)

    def _on_ui(self, action: Callable[[], None]) -> None:
        from System import Func, Type

        def run() -> None:
            action()

        self._window.native.Invoke(Func[Type](run))

    def _make_tray(self) -> None:
        """The icon a hidden window is reached through. Its handlers stay
        referenced here, or .NET would lose them."""
        from System.Drawing import Icon
        from System.Windows.Forms import ContextMenuStrip, NotifyIcon, ToolStripMenuItem, ToolTipIcon

        words = {"open": "Open personagent", "pet": "Show the pet", "quit": "Quit", **self.words()}
        self._tray_info = ToolTipIcon.Info
        # With the pet the icon shows only while it is hushed, and can bring it back.
        entries = ((words["open"], self._open_click), *(((words["pet"], self._pet_click),) if self.pet else ()),
                   (words["quit"], self._quit_click))

        def make() -> None:
            tray = NotifyIcon()
            tray.Icon = Icon(str(icon()))
            tray.Text = TITLE
            menu = ContextMenuStrip()
            for label, handler in entries:
                item = ToolStripMenuItem(label)
                item.Click += handler
                menu.Items.Add(item)
            tray.ContextMenuStrip = menu
            tray.DoubleClick += self._open_click
            tray.Visible = False
            self._tray = tray

        self._on_ui(make)

    def _closing(self):
        if self._leaving:
            return None
        if self._pet is not None:
            # The pet is still there: the window only goes away until asked for
            # again, after the pet's head has gone down behind its edge.
            threading.Thread(target=self._go_out, args=("hide",), name="personagent-pet", daemon=True).start()
            return False
        if self._tray is not None and self.background():
            self.hide()
            return False
        question = self.confirm()
        if question and not self._window.create_confirmation_dialog(TITLE, question):
            return False
        self._leaving = True
        return None

    def _sized(self, minimized: bool, maximized: bool | None = None) -> Callable[[], None]:
        def note() -> None:
            self._minimized = minimized
            if maximized is not None:
                self.maximized = maximized
                # Its page draws the bar for it (app.js).
                self._frame_changed()
        return note

    def control(self, action: str) -> bool:
        """What the page's own title bar asks for: one of ACTIONS. False when
        there is no window to do it to."""
        if not self.opened or self._leaving or action not in ACTIONS:
            return False
        try:
            if action == "minimize" and self._attached:
                # The pet's head goes down behind the edge first.
                threading.Thread(target=self._go_out, args=("minimize",), name="personagent-pet",
                                 daemon=True).start()
            elif action == "minimize":
                self._window.minimize()
            elif action == "maximize":
                self._window.maximize()
            elif action == "restore":
                self._window.restore()
            else:
                # As the system's close button: it may hide the window or ask first,
                # so the page is not kept waiting for the answer.
                threading.Thread(target=self._window.destroy, name="personagent-close", daemon=True).start()
        except Exception:
            return False
        return True

    def _before_show(self) -> None:
        with contextlib.suppress(Exception):
            self._frame = _strip_title_bar(self._window)
            self.frameless = self._frame is not None

    @property
    def page_url(self) -> str:
        """The address this window loads: `url` and the key its page shows for the bar."""
        return f"{self.url}{'&' if '#' in self.url else '#'}frame={self.frame_key}"

    def is_own_page(self, key: str) -> bool:
        return hmac.compare_digest(str(key or ""), self.frame_key)

    def frame_seen(self) -> None:
        """The page asked how the window stands, so it draws the bar and the buttons."""
        self._frame_seen.set()

    def _framed_again(self) -> None:
        """The window gets its own title bar back."""
        if self.frameless:
            self.frameless = False
            with contextlib.suppress(Exception):
                self._frame[1]()

    def _unless_seen(self) -> None:
        # A page that never came up draws no buttons: nobody is left with a
        # window that cannot be closed.
        if not self._frame_seen.wait(PAGE_WITHIN) and not self._leaving:
            self._framed_again()

    def run(self) -> bool:
        """Show the window and block until it closes. False when none opened."""
        try:
            import webview
        except Exception as error:
            self.error = repr(error)
            return False
        windows = sys.platform == "win32"
        if windows:
            import ctypes
            with contextlib.suppress(Exception):
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)

        address = urlsplit(self.url)
        origin = f"{address.scheme}://{address.netloc}"

        def ready() -> None:
            if not self._window.events.shown.wait(SHOWN_WITHIN):
                self.error = "the window did not appear"
                self.close()
            elif self._leaving:
                # Asked to close before there was a window to close.
                self.close()
            # Without WebView2, Windows offers an engine too old for the page.
            elif windows and webview.renderer != "edgechromium":
                self.error = "the WebView2 runtime is missing"
                self.close()
            else:
                if windows:
                    regions = False
                    with contextlib.suppress(Exception):
                        if self._window.events.loaded.wait(SHOWN_WITHIN):
                            regions = _text_menus(self._window)
                    if not regions:
                        # The page could not be the bar the window is moved by.
                        self._framed_again()
                    with contextlib.suppress(Exception):
                        self._make_tray()
                    _own_pages(self._window, origin)
                    self._window.load_url(self.page_url)
                    if self.frameless:
                        threading.Thread(target=self._unless_seen, name="personagent-frame",
                                         daemon=True).start()
                self.opened = True
                if self._pet is not None:
                    self.hidden = True
                    self._pet.events.shown.wait(SHOWN_WITHIN)
                    self._user32 = _user32()
                    self._place_pet()
                    self._on_ui(self._watch_window)
                    self._pet.events.loaded.wait(SHOWN_WITHIN)
                    _own_pages(self._pet, origin)
                    # Out of sight during games and fullscreen, from now on and
                    # at once if one is in front already.
                    self._pet.events.loaded.wait(SHOWN_WITHIN)
                    quiet.listen(self._quiet_changed)
                    self._quiet_changed(quiet.state())
                elif self.start_hidden:
                    self.hide()

        # A file:// page could read any file beside it, ~/personagent/.env among them.
        webview.settings["ALLOW_FILE_URLS"] = False
        try:
            # WebView2 takes its menu setting from the next load on, so Windows
            # starts on an empty page and `ready` loads the real one after it.
            self._window = webview.create_window(
                TITLE, None if windows else self.page_url, width=SIZE[0], height=SIZE[1],
                min_size=MIN_SIZE, text_select=True, zoomable=True,
                # Started for the background: no window flashes up before it hides.
                minimized=self.start_hidden and windows, hidden=self.pet)
            if self.pet:
                import ctypes
                screen = ctypes.windll.user32.GetSystemMetrics
                self._pet = webview.create_window(
                    TITLE, self.pet_url, width=PET_SIZE[0], height=PET_SIZE[1],
                    x=screen(0) - PET_SIZE[0] - PET_MARGIN, y=screen(1) - PET_SIZE[1] - 60,
                    resizable=False, frameless=True, shadow=False, on_top=True, transparent=True,
                    # The page turns selection off itself: pywebview would do it with a
                    # style element, which the page's content policy refuses.
                    text_select=True,
                    # pywebview's own drag moves the window from any press anywhere on
                    # the page, the card's buttons too. The figure alone drags it (pet.js).
                    easy_drag=False)
                # By exact name only: pywebview walks a dotted name from a js_api
                # object with getattr, private names too, out to this whole window.
                api = _PetApi(self)
                self._pet.expose(*(getattr(api, name) for name in dir(api) if not name.startswith("_")))
                # Closed on its own (Alt+F4): personagent goes with it.
                self._pet.events.closed += lambda: None if self._leaving else self.close()
            events = self._window.events
            events.closing += self._closing
            events.minimized += self._sized(True)
            events.restored += self._sized(False, False)
            events.maximized += self._sized(False, True)
            if windows:
                events.before_show += self._before_show
            with _interrupt(self.close):
                # Private: nothing the page stores outlives the window.
                webview.start(ready, gui=_toolkit(), private_mode=True,
                              storage_path=str(self.storage), icon=str(icon()))
        except Exception as error:
            self.error = repr(error)
            return False
        finally:
            if not self.opened:
                # No window after all: the browser that takes over draws no window bar.
                self.frameless = False
            if self._tray is not None:
                with contextlib.suppress(Exception):
                    self._tray.Visible = False
                    self._tray.Dispose()
        return self.opened
