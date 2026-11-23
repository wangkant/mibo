"""A video full screen in the app window on Windows, from the page itself or from the browser pane: the window
covers its whole monitor with only that WebView in it, then stands again as it was. AppWindow takes these
methods from `FullScreen`."""
from __future__ import annotations

from .. import quiet
from .native import (
    FRAME_CHANGED,
    FULL_POS,
    GWL_STYLE,
    SW_HIDE,
    SW_RESTORE,
    SW_SHOWMAXIMIZED,
    SW_SHOWMINNOACTIVE,
    WPF_RESTORETOMAXIMIZED,
    WS_CAPTION,
    WS_THICKFRAME,
)

EXIT_JS = "document.fullscreenElement && document.exitFullscreen()"


def _libs():
    """user32 and dwmapi with the argument types full screen's calls need, and WINDOWPLACEMENT."""
    import ctypes
    from ctypes import wintypes

    class Placement(ctypes.Structure):
        _fields_ = [("length", wintypes.UINT), ("flags", wintypes.UINT), ("show", wintypes.UINT),
                    ("min", wintypes.POINT), ("max", wintypes.POINT), ("normal", wintypes.RECT)]

    user32 = ctypes.WinDLL("user32")
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, wintypes.UINT]
    # The placement kept from going full screen is of an earlier call's Placement: passed by address.
    user32.GetWindowPlacement.argtypes = user32.SetWindowPlacement.argtypes = [wintypes.HWND, ctypes.c_void_p]
    user32.IsZoomed.argtypes = user32.IsIconic.argtypes = user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    return user32, ctypes.WinDLL("dwmapi"), Placement


def _corners(dwmapi, hwnd: int, preference: int) -> None:
    """DWMWA_WINDOW_CORNER_PREFERENCE: 1 square, as full screen is; 0 as the system chooses."""
    import ctypes
    dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), 33, ctypes.byref(ctypes.c_int(preference)), 4)


class FullScreen:
    """`_full` is the video full screen in the window: the WebView showing it and how the window stood before."""

    def _watch_full_screen(self) -> None:
        core = self._window.native.browser.webview.CoreWebView2
        self._page_full = lambda sender, args: self._full_screen(sender, bool(sender.ContainsFullScreenElement))
        core.ContainsFullScreenElementChanged += self._page_full
        # Hidden, put in the notification area or minimised, the video leaves full screen with it.
        form = self._window.native
        self._away_full = lambda sender, args: self._leave_full()
        form.VisibleChanged += self._away_full
        form.Resize += self._away_full
        form.browser.webview.VisibleChanged += self._away_full

    def _leave_full(self, anyway: bool = False) -> None:
        from System.Windows.Forms import FormWindowState
        form = self._window.native
        if self._full is None or (form.Visible and form.browser.webview.Visible
                                  and form.WindowState != FormWindowState.Minimized and not anyway):
            return
        core = self._full["core"]
        self._full_screen(core, False)
        core.ExecuteScriptAsync(EXIT_JS)

    def _full_screen(self, core, on: bool) -> None:
        """A video in the page or in the pane (`core`, its CoreWebView2) went full screen, or left it: the
        window covers its whole monitor, taskbar too, with no frame and only that WebView in it; then it
        stands again as it was, maximised or not. On the form's thread."""
        if on == (self._full is not None):
            return
        hwnd = self._window.native.Handle.ToInt64()
        if on:
            self._enter_full(core, hwnd)
        else:
            self._exit_full(hwnd)

    def _enter_full(self, core, hwnd: int) -> None:
        import ctypes

        from System.Windows.Forms import Screen

        user32, dwmapi, Placement = _libs()
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            # Nothing comes to the front by itself: a window out of sight gives full screen back at once.
            core.ExecuteScriptAsync(EXIT_JS)
            return
        # Where it stood, maximised or not, as the system keeps it.
        placement = Placement()
        placement.length = ctypes.sizeof(Placement)
        user32.GetWindowPlacement(hwnd, ctypes.addressof(placement))
        if user32.IsZoomed(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
        # Read once restored: a maximised window's style says so, and would maximise it again.
        self._full = {"placement": placement, "style": user32.GetWindowLongPtrW(hwnd, GWL_STYLE), "core": core}
        screen = Screen.FromControl(self._window.native).Bounds
        user32.SetWindowLongPtrW(hwnd, GWL_STYLE, self._full["style"] & ~(WS_CAPTION | WS_THICKFRAME))
        _corners(dwmapi, hwnd, 1)
        user32.SetWindowPos(hwnd, None, screen.X, screen.Y, screen.Width, screen.Height, FULL_POS)
        if self._browser is not None:
            self._browser.cover(self._browser.shows(core))
        # In front, it is a video full screen to quiet as well: the pet keeps still meanwhile.
        quiet.own_full_screen(True)

    def _exit_full(self, hwnd: int) -> None:
        import ctypes

        user32, dwmapi, _ = _libs()
        full, self._full = self._full, None
        user32.SetWindowLongPtrW(hwnd, GWL_STYLE, full["style"])
        _corners(dwmapi, hwnd, 0)
        user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, FRAME_CHANGED)
        placement = full["placement"]
        # Left by going away: it stays away, to come back where it stood.
        if user32.IsIconic(hwnd) or not user32.IsWindowVisible(hwnd):
            if placement.show == SW_SHOWMAXIMIZED:
                placement.flags |= WPF_RESTORETOMAXIMIZED
            placement.show = SW_SHOWMINNOACTIVE if user32.IsIconic(hwnd) else SW_HIDE
        user32.SetWindowPlacement(hwnd, ctypes.addressof(placement))
        if user32.IsIconic(hwnd):
            # WinForms brings a minimised window back at the size it kept itself: told it here.
            from System.Drawing import Rectangle
            normal = placement.normal
            self._window.native.Bounds = Rectangle(normal.left, normal.top, normal.right - normal.left,
                                                   normal.bottom - normal.top)
        if self._browser is not None:
            self._browser.cover(None)
        quiet.own_full_screen(False)
