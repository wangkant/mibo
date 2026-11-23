"""What the person sees while the character works in another program, and how
they stop it: a coloured border round the window being operated, a small strip
by it saying that the character is working there and asking them not to use
it, with Stop and "I'll take over", Esc or Ctrl+Alt+M from anywhere to stop,
and a pause the moment the person clicks, scrolls or types in that window
themselves, or keeps using the computer while an action waits for them to
leave it alone. A paused run waits for their Continue, then goes on from a
fresh look.

Plain Win32 through ctypes, on a thread of its own with its own message loop
(the low-level keyboard and mouse watches need one). The border and the strip
never take the focus and the border lets clicks through. Input this layer sends
carries win32.MARK, so only the person's own keys and clicks count.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import threading
import time

from . import win32

user32, kernel32, gdi32, shcore = win32.user32, win32.kernel32, win32.gdi32, win32.shcore

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, w.HWND, ctypes.c_uint, w.WPARAM, w.LPARAM)
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, w.WPARAM, w.LPARAM)

user32.DefWindowProcW.argtypes = [w.HWND, ctypes.c_uint, w.WPARAM, w.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, w.HINSTANCE, w.DWORD]
user32.SetWindowsHookExW.restype = w.HHOOK
user32.CallNextHookEx.argtypes = [w.HHOOK, ctypes.c_int, w.WPARAM, w.LPARAM]
user32.CallNextHookEx.restype = LRESULT
user32.UnhookWindowsHookEx.argtypes = [w.HHOOK]
user32.SetLayeredWindowAttributes.argtypes = [w.HWND, w.COLORREF, ctypes.c_ubyte, w.DWORD]
user32.SetWindowTextW.argtypes = [w.HWND, w.LPCWSTR]
user32.SendMessageW.argtypes = [w.HWND, ctypes.c_uint, w.WPARAM, w.LPARAM]
user32.SendMessageW.restype = LRESULT
user32.ShowWindow.argtypes = [w.HWND, ctypes.c_int]
user32.BeginPaint.argtypes = [w.HWND, ctypes.c_void_p]
user32.BeginPaint.restype = w.HDC
user32.EndPaint.argtypes = [w.HWND, ctypes.c_void_p]
user32.FillRect.argtypes = [w.HDC, ctypes.POINTER(w.RECT), w.HBRUSH]
user32.GetClientRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
user32.SetTimer.argtypes = [w.HWND, ctypes.c_size_t, ctypes.c_uint, ctypes.c_void_p]
user32.InvalidateRect.argtypes = [w.HWND, ctypes.c_void_p, w.BOOL]
user32.GetMessageW.argtypes = [ctypes.POINTER(w.MSG), w.HWND, ctypes.c_uint, ctypes.c_uint]
user32.TranslateMessage.argtypes = [ctypes.POINTER(w.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(w.MSG)]
user32.PostThreadMessageW.argtypes = [w.DWORD, ctypes.c_uint, w.WPARAM, w.LPARAM]
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.LoadCursorW.argtypes = [w.HINSTANCE, ctypes.c_void_p]
user32.LoadCursorW.restype = ctypes.c_void_p
gdi32.CreateSolidBrush.argtypes = [w.COLORREF]
gdi32.CreateSolidBrush.restype = w.HBRUSH
gdi32.CreateFontW.argtypes = [ctypes.c_int] * 5 + [w.DWORD] * 8 + [w.LPCWSTR]
gdi32.CreateFontW.restype = w.HFONT
gdi32.SetBkColor.argtypes = [w.HDC, w.COLORREF]
gdi32.SetTextColor.argtypes = [w.HDC, w.COLORREF]
kernel32.GetModuleHandleW.argtypes = [w.LPCWSTR]
kernel32.GetModuleHandleW.restype = w.HMODULE
kernel32.GetCurrentThreadId.restype = w.DWORD

TEXT = {
    "zh": {"stop": "停止 (Esc)", "take": "接管", "go": "继续", "working": "正在操作此窗口，请暂勿使用",
           "paused": "已暂停：你正在使用此窗口", "busy": "已暂停：你正在使用电脑"},
    "en": {"stop": "Stop (Esc)", "take": "I'll take over", "go": "Continue",
           "working": "Working in this window, please don't use it", "paused": "Paused: you are using this window",
           "busy": "Paused: you are using the computer"},
}
# Why a run waits for Continue when the person kept using the computer, not this window.
BUSY = "the person kept using the computer"
KEY_COLOR = 0x00FF00FF  # magenta, drawn as see-through in the border window
ACCENT = 0x00404040     # dark grey, the app's plain greys (COLORREF is 0x00BBGGRR)
STRIP_BACK = 0x00FFFFFF
EDGE = 4
WM_SAY, WM_BYE = 0x0400 + 1, 0x0400 + 2
STOP_ID, TAKE_ID, GO_ID = 101, 102, 103
LLKHF_INJECTED, LLMHF_INJECTED = 0x10, 0x01
MODIFIERS = {0x10, 0x11, 0x12, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0x5B, 0x5C, 0x14, 0x90}


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", w.DWORD), ("scanCode", w.DWORD), ("flags", w.DWORD), ("time", w.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", w.POINT), ("mouseData", w.DWORD), ("flags", w.DWORD), ("time", w.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("style", ctypes.c_uint), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int), ("hInstance", w.HINSTANCE),
                ("hIcon", w.HICON), ("hCursor", w.HANDLE), ("hbrBackground", w.HBRUSH),
                ("lpszMenuName", w.LPCWSTR), ("lpszClassName", w.LPCWSTR), ("hIconSm", w.HICON)]


class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [("hdc", w.HDC), ("fErase", w.BOOL), ("rcPaint", w.RECT), ("fRestore", w.BOOL),
                ("fIncUpdate", w.BOOL), ("rgbReserved", ctypes.c_byte * 32)]


user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]


class Strip:
    """The border and the strip on `hwnd` while the character works there. `windows()` gives the program's
    windows that belong with the target (their rectangles are where the person's clicks pause it).
    `halted` is "" while it may go on, else "stopped", "handover" or "paused" (until Continue)."""

    def __init__(self, hwnd: int, program: str, *, who: str = "Mibo", lang: str = "zh",
                 windows=None):
        self.hwnd = hwnd
        self.program = program
        self.who = who
        self.t = TEXT["zh" if lang.startswith("zh") else "en"]
        self.windows = windows or (lambda: [hwnd])
        self.halted = ""
        self.why = ""
        self.doing = ""
        # Until this moment an action of the character's own is running in the window.
        self.own_until = 0.0
        self.areas: list[tuple[int, int, int, int]] = []
        self.handles: set[int] = {hwnd}
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._run, name="desk-strip", daemon=True)
        self.thread_id = 0
        self._keep: list = []
        self.border = self.strip = self.label = 0
        # The strip's own rectangle, where the person's clicks are on the strip and not the window; its brush.
        self.strip_rect = (0, 0, 0, 0)
        self._back = 0
        self.thread.start()
        self.ready.wait(5)

    # --- from the working thread

    def say(self, doing: str) -> None:
        """What the character is doing now, a few words."""
        self.doing = doing
        if self.label:
            user32.PostMessageW(self.strip, WM_SAY, 0, 0)

    def stop(self, why: str = "stopped", detail: str = "") -> None:
        """Halt the run: "stopped" and "handover" end it, also a paused one; "paused" waits for Continue."""
        if not self.halted or (self.halted == "paused" and why != "paused"):
            self.halted, self.why = why, detail
            if self.label:
                user32.PostMessageW(self.strip, WM_SAY, 0, 0)

    def busy(self) -> None:
        """The person kept using the computer while an action waited for real input: the strip asks them."""
        self.stop("paused", BUSY)

    def close(self) -> None:
        if self.thread_id:
            user32.PostThreadMessageW(self.thread_id, WM_BYE, 0, 0)
        self.thread.join(3)

    # --- the strip's own thread

    def _run(self) -> None:
        win32.dpi_aware()
        self.thread_id = kernel32.GetCurrentThreadId()
        inst = kernel32.GetModuleHandleW(None)
        border_proc, strip_proc = WNDPROC(self._border_proc), WNDPROC(self._strip_proc)
        keys, mouse = HOOKPROC(self._on_key), HOOKPROC(self._on_mouse)
        self._keep += [border_proc, strip_proc, keys, mouse]
        for name, proc, back in (("MiboDeskBorder", border_proc, gdi32.CreateSolidBrush(KEY_COLOR)),
                                 ("MiboDeskStrip", strip_proc, gdi32.CreateSolidBrush(STRIP_BACK))):
            cls = WNDCLASSEXW(cbSize=ctypes.sizeof(WNDCLASSEXW), lpfnWndProc=proc, hInstance=inst,
                              hCursor=user32.LoadCursorW(None, ctypes.c_void_p(32512)), hbrBackground=back,
                              lpszClassName=f"{name}{self.thread_id}")
            user32.RegisterClassExW(ctypes.byref(cls))
        # WS_EX_LAYERED | TRANSPARENT | TOPMOST | TOOLWINDOW | NOACTIVATE; WS_POPUP.
        self.border = user32.CreateWindowExW(0x80000 | 0x20 | 0x8 | 0x80 | 0x08000000,
                                             f"MiboDeskBorder{self.thread_id}", "", 0x80000000,
                                             0, 0, 10, 10, None, None, inst, None)
        user32.SetLayeredWindowAttributes(self.border, KEY_COLOR, 255, 1)
        self.strip = user32.CreateWindowExW(0x8 | 0x80 | 0x08000000, f"MiboDeskStrip{self.thread_id}",
                                            "Mibo", 0x80000000 | 0x00800000, 0, 0, 10, 10, None, None, inst, None)
        # The scale and the font of the monitor the target is on, from _follow on.
        self.scale, self.font = 0.0, None
        self.label = user32.CreateWindowExW(0, "STATIC", "", 0x50000000 | 0x0100 | 0x4000, 0, 0, 10, 10,
                                            self.strip, None, inst, None)
        stop = user32.CreateWindowExW(0, "BUTTON", self.t["stop"], 0x50000000, 0, 0, 10, 10, self.strip,
                                      ctypes.c_void_p(STOP_ID), inst, None)
        take = user32.CreateWindowExW(0, "BUTTON", self.t["take"], 0x50000000, 0, 0, 10, 10, self.strip,
                                      ctypes.c_void_p(TAKE_ID), inst, None)
        # Shown only while paused.
        self.go = user32.CreateWindowExW(0, "BUTTON", self.t["go"], 0x40000000, 0, 0, 10, 10, self.strip,
                                         ctypes.c_void_p(GO_ID), inst, None)
        self.buttons = (self.go, stop, take)
        hooks = [user32.SetWindowsHookExW(13, keys, inst, 0), user32.SetWindowsHookExW(14, mouse, inst, 0)]
        self._follow()
        self._say()
        user32.SetTimer(self.strip, 1, 150, None)
        self.ready.set()
        msg = w.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_BYE:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        for hook in hooks:
            user32.UnhookWindowsHookEx(hook)
        user32.DestroyWindow(self.strip)
        user32.DestroyWindow(self.border)
        self.label = 0

    def _say(self) -> None:
        paused = self.halted == "paused"
        if paused:
            text = f"{self.who} · {self.program}　{self.t['busy' if self.why == BUSY else 'paused']}"
        else:
            text = f"{self.who} · {self.program}　{self.t['working']}　{self.doing}"
        user32.SetWindowTextW(self.label, text)
        user32.ShowWindow(self.go, 5 if paused else 0)
        self._follow()

    def _follow(self) -> None:
        """Keep the border round the target and the strip just above it (below it at the top of a screen)."""
        if not win32.alive(self.hwnd):
            self.stop("stopped", "the window closed")
            user32.ShowWindow(self.border, 0)
            user32.ShowWindow(self.strip, 0)
            return
        # Read here, not in the watches: a low-level hook must answer at once.
        self.handles = set(self.windows())
        self.areas = [win32.rect(h) for h in self.handles if win32.alive(h)]
        if not win32.shown(self.hwnd):
            user32.ShowWindow(self.border, 0)
            user32.ShowWindow(self.strip, 0)
            return
        self._rescale()
        left, top, right, bottom = win32.rect(self.hwnd)
        e = int(EDGE * self.scale)
        flags = 0x0010 | 0x0040  # SWP_NOACTIVATE | SWP_SHOWWINDOW
        user32.SetWindowPos(self.border, w.HWND(-1), left - e, top - e, right - left + 2 * e,
                            bottom - top + 2 * e, flags)
        high, wide = int(34 * self.scale), max(int(600 * self.scale), min(right - left, int(760 * self.scale)))
        y = top - e - high if top - e - high > -32000 and self._on_screen(left, top - e - high) else bottom + e
        user32.SetWindowPos(self.strip, w.HWND(-1), left, y, wide, high, flags)
        pad, bw = int(6 * self.scale), int(92 * self.scale)
        shown = self.buttons if self.halted == "paused" else self.buttons[1:]
        user32.SetWindowPos(self.label, None, pad, pad, wide - len(shown) * (bw + pad) - 2 * pad, high - 2 * pad, 0x0014)
        for i, button in enumerate(shown):
            user32.SetWindowPos(button, None, wide - (len(shown) - i) * (bw + pad), pad // 2, bw, high - pad, 0x0014)
        self.strip_rect = win32.rect(self.strip)

    def _rescale(self) -> None:
        """The border, the strip and its words at the scale of the monitor the target is on."""
        dpi = w.UINT()
        # MONITOR_DEFAULTTONEAREST; MDT_EFFECTIVE_DPI.
        shcore.GetDpiForMonitor(user32.MonitorFromWindow(self.hwnd, 2), 0, ctypes.byref(dpi), ctypes.byref(dpi))
        if dpi.value / 96 == self.scale:
            return
        self.scale = dpi.value / 96
        font = gdi32.CreateFontW(-int(13 * self.scale), 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 5, 0, "Microsoft YaHei UI")
        for h in (self.label, *self.buttons):
            user32.SendMessageW(h, 0x0030, font, 1)  # WM_SETFONT
        if self.font:
            gdi32.DeleteObject(self.font)
        self.font = font
        # The edge is drawn this much thicker or thinner all round.
        user32.InvalidateRect(self.border, None, True)

    @staticmethod
    def _on_screen(x: int, y: int) -> bool:
        return any(m["left"] <= x < m["right"] and m["top"] <= y < m["bottom"] for m in win32.monitors())

    def _border_proc(self, hwnd, msg, wparam, lparam):
        if msg == 0x000F:  # WM_PAINT
            ps = PAINTSTRUCT()
            dc = user32.BeginPaint(hwnd, ctypes.byref(ps))
            r = w.RECT()
            user32.GetClientRect(hwnd, ctypes.byref(r))
            key, accent = gdi32.CreateSolidBrush(KEY_COLOR), gdi32.CreateSolidBrush(ACCENT)
            user32.FillRect(dc, ctypes.byref(r), key)
            e = int(EDGE * self.scale)
            for side in (w.RECT(0, 0, r.right, e), w.RECT(0, r.bottom - e, r.right, r.bottom),
                         w.RECT(0, 0, e, r.bottom), w.RECT(r.right - e, 0, r.right, r.bottom)):
                user32.FillRect(dc, ctypes.byref(side), accent)
            gdi32.DeleteObject(key)
            gdi32.DeleteObject(accent)
            user32.EndPaint(hwnd, ctypes.byref(ps))
            return 0
        if msg == 0x0084:  # WM_NCHITTEST: HTTRANSPARENT
            return -1
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _strip_proc(self, hwnd, msg, wparam, lparam):
        if msg == 0x0021:  # WM_MOUSEACTIVATE: MA_NOACTIVATE
            return 3
        if msg == 0x0111:  # WM_COMMAND
            if wparam & 0xFFFF == STOP_ID:
                self.stop("stopped", "the person pressed Stop")
            elif wparam & 0xFFFF == TAKE_ID:
                self.stop("handover", "the person took over")
            elif wparam & 0xFFFF == GO_ID and self.halted == "paused":
                self.halted, self.why = "", ""
                self._say()
            return 0
        if msg == 0x0113:  # WM_TIMER
            self._follow()
            return 0
        if msg == WM_SAY:
            self._say()
            return 0
        if msg == 0x0138:  # WM_CTLCOLORSTATIC
            gdi32.SetBkColor(wparam, STRIP_BACK)
            gdi32.SetTextColor(wparam, 0x00202020)
            if not self._back:
                self._back = gdi32.CreateSolidBrush(STRIP_BACK)
            return self._back
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _inside(self, x: int, y: int) -> bool:
        return any(left <= x < right and top <= y < bottom for left, top, right, bottom in self.areas)

    def _on_key(self, code, wparam, lparam):
        if code == 0 and wparam in (0x0100, 0x0104):
            k = KBDLLHOOKSTRUCT.from_address(lparam)
            if k.dwExtraInfo != win32.MARK:
                ctrl = user32.GetAsyncKeyState(0x11) & 0x8000
                alt = user32.GetAsyncKeyState(0x12) & 0x8000
                # The stop keys always stop. Any other key some program injected while the character's own
                # action runs is that action's doing (a classic menu opens by simulated keys), not the
                # person's hand, and does not pause.
                own = k.flags & 0x10 and time.monotonic() < self.own_until
                if k.vkCode == 0x1B:
                    self.stop("stopped", "the person pressed Esc")
                elif k.vkCode == 0x4D and ctrl and alt:
                    self.stop("stopped", "the person pressed Ctrl+Alt+M")
                elif not own and k.vkCode not in MODIFIERS and win32.top_of(win32.foreground()) in self.handles:
                    self.stop("paused", "the person typed in the window")
        return user32.CallNextHookEx(None, code, wparam, lparam)

    def _on_mouse(self, code, wparam, lparam):
        if code == 0 and wparam in (0x0201, 0x0204, 0x0207, 0x020A, 0x020E):
            m = MSLLHOOKSTRUCT.from_address(lparam)
            if m.dwExtraInfo != win32.MARK and self._inside(m.pt.x, m.pt.y) and not (
                    m.flags & 0x01 and time.monotonic() < self.own_until):
                left, top, right, bottom = self.strip_rect
                if not (left <= m.pt.x < right and top <= m.pt.y < bottom):
                    self.stop("paused", "the person used the mouse in the window")
        return user32.CallNextHookEx(None, code, wparam, lparam)
