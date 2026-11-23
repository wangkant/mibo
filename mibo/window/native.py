"""Win32 calls the app window and the pet make through ctypes: the frameless title bar, a window's moves and
monitor scale heard as they happen, monitors, and the process's own standing. Each function imports ctypes'
Windows parts when called, so the package still loads on macOS and Linux."""
from __future__ import annotations

import contextlib
from collections.abc import Callable
from types import SimpleNamespace

from . import winforms

# Windows files taskbar buttons under this, not under Python.
APP_ID = "wangkant.mibo"
# winuser.h: the extended styles of a window that takes no focus and has no
# taskbar button, and of one that has a taskbar button.
GWL_EXSTYLE, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW, WS_EX_APPWINDOW = -20, 0x08000000, 0x00000080, 0x00040000
# The owner of a window that is not a child.
GWLP_HWNDPARENT = -8
# SetWindowPos: keep focus; move only, keeping size, order and focus; keep
# order and focus; keep place, size and focus; and where in the order.
NO_FOCUS = 0x0010
MOVE_ONLY = 0x0001 | 0x0004 | NO_FOCUS
KEEP_ORDER = 0x0004 | NO_FOCUS
ORDER_ONLY = 0x0001 | 0x0002 | NO_FOCUS
HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
RGN_OR = 2
SW_HIDE, SW_SHOWMAXIMIZED, SW_SHOWNOACTIVATE, SW_SHOWMINNOACTIVE, SW_RESTORE = 0, 3, 4, 7, 9
WPF_RESTORETOMAXIMIZED = 2
# Which mouse button is the primary one.
_SM_SWAPBUTTON, _VK_LBUTTON, _VK_RBUTTON = 23, 0x01, 0x02
# A window's style, and the frame full screen takes off it; SetWindowPos for it: the frame worked out again.
GWL_STYLE, WS_CAPTION, WS_THICKFRAME = -16, 0x00C00000, 0x00040000
FULL_POS = 0x0020 | 0x0200
# SetWindowPos: keep place, size and order, and work the frame out again.
FRAME_CHANGED = 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020
# DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2, and the message a window gets on a monitor of another scale.
_PER_MONITOR_V2, _WM_DPICHANGED = -4, 0x02E0
# Window messages and metrics the frameless window handles (winuser.h).
_WM_WINDOWPOSCHANGED, _WM_NCDESTROY, _WM_NCCALCSIZE, _WM_WINDOWPOSCHANGING = 0x0047, 0x0082, 0x0083, 0x0046
_SWP_NOSIZE = 0x0001
_WM_SIZE, _SIZE_RESTORED, _SIZE_MINIMIZED, _SIZE_MAXIMIZED = 0x0005, 0, 1, 2
_SM_CYSIZEFRAME, _SM_CXPADDEDBORDER = 33, 92
# shellapi.h: is there a taskbar that hides itself at this edge of this screen,
# and how far a maximized page stays from it.
_ABM_GETAUTOHIDEBAREX = 0x0000000B
_HIDDEN_TASKBAR_GAP = 2
# The ids of the window subclasses: the title bar's, the moves', the scale's.
_FRAME_ID, _MOVES_ID, _SCALE_ID = 1, 2, 3


def own_process() -> None:
    """This process as Windows should take it: sharp on every monitor, and the app's own entry on the taskbar."""
    import ctypes
    # Per-monitor aware (v2) before any window is made. The first call wins, so pywebview's
    # SetProcessDPIAware later changes nothing; the packaged app's manifest says the same.
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(_PER_MONITOR_V2))
    with contextlib.suppress(Exception):
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)


def _comctl32():
    """comctl32 with the argument types a window subclass needs, and the type of its handler: a library of our own,
    as pywebview calls the shared one with other types."""
    import ctypes
    from ctypes import wintypes

    comctl32 = ctypes.WinDLL("comctl32")
    result_t = ctypes.c_ssize_t
    proc_t = ctypes.WINFUNCTYPE(result_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                wintypes.LPARAM, ctypes.c_size_t, ctypes.c_size_t)
    comctl32.DefSubclassProc.restype = result_t
    comctl32.DefSubclassProc.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    comctl32.SetWindowSubclass.restype = wintypes.BOOL
    comctl32.SetWindowSubclass.argtypes = [wintypes.HWND, proc_t, ctypes.c_size_t, ctypes.c_size_t]
    comctl32.RemoveWindowSubclass.argtypes = [wintypes.HWND, proc_t, ctypes.c_size_t]
    return comctl32, proc_t


def _frame_libs() -> SimpleNamespace:
    """user32, shell32 and comctl32 with the argument types the frameless window's calls need, and the
    structures they take."""
    import ctypes
    from ctypes import wintypes

    class MonitorInfo(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT), ("work", wintypes.RECT),
                    ("flags", wintypes.DWORD)]

    class AppBar(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("hwnd", wintypes.HWND), ("message", wintypes.UINT),
                    ("edge", wintypes.UINT), ("rect", wintypes.RECT), ("lparam", wintypes.LPARAM)]

    class WindowPos(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("after", wintypes.HWND), ("x", ctypes.c_int), ("y", ctypes.c_int),
                    ("cx", ctypes.c_int), ("cy", ctypes.c_int), ("flags", wintypes.UINT)]

    # Libraries of our own: pywebview calls the shared ones with other argument types.
    user32, shell32 = ctypes.WinDLL("user32"), ctypes.WinDLL("shell32")
    comctl32, proc_t = _comctl32()
    user32.IsZoomed.argtypes = [wintypes.HWND]
    user32.GetDpiForWindow.argtypes = [wintypes.HWND]
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.MonitorFromWindow.restype = wintypes.HANDLE
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
    shell32.SHAppBarMessage.restype = ctypes.c_size_t
    shell32.SHAppBarMessage.argtypes = [wintypes.DWORD, ctypes.POINTER(AppBar)]
    return SimpleNamespace(user32=user32, shell32=shell32, comctl32=comctl32, proc_t=proc_t,
                           MonitorInfo=MonitorInfo, AppBar=AppBar, WindowPos=WindowPos)


def _frame_height(lib: SimpleNamespace, hwnd) -> int:
    dpi = lib.user32.GetDpiForWindow(hwnd) or 96
    return (lib.user32.GetSystemMetricsForDpi(_SM_CYSIZEFRAME, dpi)
            + lib.user32.GetSystemMetricsForDpi(_SM_CXPADDEDBORDER, dpi))


def _leave_hidden_taskbar(lib: SimpleNamespace, hwnd, rect) -> None:
    """A page that covers the whole screen counts as full screen, and a
    taskbar set to hide itself would never come back: stop short of its edge."""
    import ctypes

    info = lib.MonitorInfo()
    info.size = ctypes.sizeof(lib.MonitorInfo)
    if not lib.user32.GetMonitorInfoW(lib.user32.MonitorFromWindow(hwnd, 2), ctypes.byref(info)):
        return
    for edge, side, step in ((0, "left", 1), (1, "top", 1), (2, "right", -1), (3, "bottom", -1)):
        bar = lib.AppBar()
        bar.size, bar.edge, bar.rect = ctypes.sizeof(lib.AppBar), edge, info.monitor
        if lib.shell32.SHAppBarMessage(_ABM_GETAUTOHIDEBAREX, ctypes.byref(bar)):
            setattr(rect, side, getattr(rect, side) + step * _HIDDEN_TASKBAR_GAP)


def strip_title_bar(window):
    """Take the title bar off a Windows window and leave everything else the
    system gives one: the resize borders at the sides and the bottom, the
    shadow, snapping and the taskbar entry. The page draws its own bar.

    Returns what must stay referenced while the window lives and how to give the
    title bar back, or None when the title bar is still there."""
    import ctypes
    from ctypes import wintypes

    form = window.native
    lib = _frame_libs()
    user32, comctl32 = lib.user32, lib.comctl32
    # Back from the taskbar or from maximized, WinForms sizes the window once
    # more from its page as if it had a title bar: a bar's height taller each
    # time (and, on a monitor scaled unlike the main one, with that one's frame,
    # narrower too). That one change keeps the size the system brought it back at.
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
            pos = ctypes.cast(ctypes.c_void_p(lparam), ctypes.POINTER(lib.WindowPos))[0]
            (wide, high), back["size"] = back["size"], None
            if not pos.flags & _SWP_NOSIZE and (pos.cx, pos.cy) != (wide, high):
                pos.cx, pos.cy = wide, high
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
                    rect[0].top = top + (_frame_height(lib, hwnd) if zoomed else 0)
                    if zoomed:
                        _leave_hidden_taskbar(lib, hwnd, rect[0])
            return result
        if message == _WM_NCDESTROY:
            comctl32.RemoveWindowSubclass(hwnd, callback, _FRAME_ID)
        return comctl32.DefSubclassProc(hwnd, message, wparam, lparam)

    callback = lib.proc_t(proc)

    def undo() -> None:
        """Give the window its title bar back."""
        def remove() -> None:
            hwnd = form.Handle.ToInt64()
            comctl32.RemoveWindowSubclass(hwnd, callback, _FRAME_ID)
            user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, FRAME_CHANGED)
        winforms.on_thread(form, remove)

    # Called from the window's own thread before it shows, so no title bar is ever drawn.
    hwnd = form.Handle.ToInt64()
    if not comctl32.SetWindowSubclass(hwnd, callback, _FRAME_ID, 0):
        return None
    user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, FRAME_CHANGED)
    return callback, undo


def _subclass(hwnd: int, ident: int, heard: Callable[[int, int, int], None]):
    """Hand `heard(message, wparam, lparam)` each message the window gets, once the window has handled it.
    Called on the window's own thread; returns what must stay referenced while the window lives."""
    comctl32, proc_t = _comctl32()

    def proc(hwnd, message, wparam, lparam, _subclass, _data):
        result = comctl32.DefSubclassProc(hwnd, message, wparam, lparam)
        if message == _WM_NCDESTROY:
            comctl32.RemoveWindowSubclass(hwnd, callback, ident)
        else:
            heard(message, wparam, lparam)
        return result

    callback = proc_t(proc)
    comctl32.SetWindowSubclass(hwnd, callback, ident, 0)
    return callback


def watch_moves(hwnd: int, moved: Callable[[], None]):
    """Call `moved` on the window's own thread each time it has moved, changed
    size, shown or hidden: in the same instant, not on a timer that trails it.
    Called on that thread; returns what must stay referenced while the window lives."""
    def heard(message: int, wparam: int, lparam: int) -> None:
        # The window is where it is going first, then what goes with it follows.
        if message == _WM_WINDOWPOSCHANGED:
            moved()

    return _subclass(hwnd, _MOVES_ID, heard)


def watch_scale(hwnd: int, changed: Callable[[float, tuple[int, int, int, int]], None]):
    """Call `changed(scale, suggested)` on the window's own thread when it comes onto a monitor
    of another scale, or its monitor's scale changes: its new device px per CSS px, and the
    (left, top, right, bottom) Windows suggests for the same size in CSS px. WinForms on the
    .NET Framework leaves the window as it was in device px; WebView2 draws at the new scale
    by itself. Called on that thread; returns what must stay referenced while the window lives."""
    import ctypes
    from ctypes import wintypes

    def heard(message: int, wparam: int, lparam: int) -> None:
        if message == _WM_DPICHANGED:
            box = ctypes.cast(ctypes.c_void_p(lparam), ctypes.POINTER(wintypes.RECT))[0]
            changed((wparam & 0xFFFF) / 96, (box.left, box.top, box.right, box.bottom))

    return _subclass(hwnd, _SCALE_ID, heard)


def user32():
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
    user32.MonitorFromRect.argtypes = [ctypes.POINTER(wintypes.RECT), wintypes.DWORD]
    user32.MonitorFromRect.restype = user32.MonitorFromWindow.restype = wintypes.HANDLE
    user32.MonitorFromWindow.argtypes = [hwnd, wintypes.DWORD]
    user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    return user32


def primary_button(user32) -> int:
    """The virtual key of the primary mouse button, swapped or not."""
    return _VK_RBUTTON if user32.GetSystemMetrics(_SM_SWAPBUTTON) else _VK_LBUTTON


def monitor(user32, box: tuple[int, int, int, int] | int) -> tuple[tuple[int, int, int, int], float]:
    """The monitor a window is on, by its handle, or would be on at `box` (left, top, right,
    bottom): the one most of it covers, as Windows chooses its scale. Its whole rectangle,
    and its device px per CSS px."""
    import ctypes
    from ctypes import wintypes

    class MonitorInfo(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT), ("work", wintypes.RECT),
                    ("flags", wintypes.DWORD)]

    # MONITOR_DEFAULTTONEAREST.
    handle = (user32.MonitorFromWindow(box, 2) if isinstance(box, int)
              else user32.MonitorFromRect(ctypes.byref(wintypes.RECT(*box)), 2))
    info, dpi = MonitorInfo(), wintypes.UINT()
    info.size = ctypes.sizeof(MonitorInfo)
    user32.GetMonitorInfoW(handle, ctypes.byref(info))
    # MDT_EFFECTIVE_DPI.
    ctypes.windll.shcore.GetDpiForMonitor(wintypes.HANDLE(handle), 0, ctypes.byref(dpi), ctypes.byref(dpi))
    m = info.monitor
    return (m.left, m.top, m.right, m.bottom), dpi.value / 96


def onto(user32, box: tuple[int, int, int, int], screen: tuple[int, int, int, int]) -> tuple[int, int]:
    """Where a window at `box` goes, moved as little as it takes, for most of it to be on the
    monitor `screen`: (left, top). Otherwise its new size would put it back on the last monitor,
    and the two scales would take turns."""
    left, top, right, bottom = box
    wide, high = right - left, bottom - top
    # Its middle on the monitor first; then, for a monitor it only partly lies beside, all of it.
    x = min(max(left + wide // 2, screen[0] + 2), screen[2] - 2) - wide // 2
    y = min(max(top + high // 2, screen[1] + 2), screen[3] - 2) - high // 2
    if monitor(user32, (x, y, x + wide, y + high))[0] != screen:
        x = min(max(x, screen[0]), screen[2] - wide)
        y = min(max(y, screen[1]), screen[3] - high)
    return x, y
