"""The pet's compact chat: the app's own page (app.js, chat.js) in a small frameless window beside the
figure, open on the main conversation and laid out small by compact.js, so it is the real chat and every
change to the chat shows there too. A window of its own rather than the pet's: the app page refuses to be
framed, and the pet's window takes no focus, which a box to type in needs.

One click on the figure brings it out on the side with room; Esc, a click anywhere else or another click
on the figure puts it away. Hidden, never closed, it keeps its scroll place and an unsent draft."""
from __future__ import annotations

import ctypes
import json
import threading
import time
from ctypes import wintypes
from urllib.parse import urlsplit, urlunsplit

# Its size in CSS px, and the gap between it and the figure.
SIZE = (380, 520)
GAP = 6
# Coming out and going: frames of its fade, and how far it slides from the figure as it comes (CSS px).
STEPS = 8
STEP_S = 0.016
SLIDE = 12
LOAD_S = 20
# Made this long after the pet came up, so the start is not slower for it.
WARM_S = 6
_GWL_EXSTYLE, _WS_EX_TOOLWINDOW, _WS_EX_APPWINDOW = -20, 0x80, 0x40000
_SWP_NOACTIVATE = 0x0010
# SPI_GETCLIENTAREAANIMATION: off is what the page reads as reduced motion.
_SPI_GETCLIENTAREAANIMATION = 0x1042


def _motion() -> bool:
    on = wintypes.BOOL(True)
    ctypes.windll.user32.SystemParametersInfoW(_SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(on), 0)
    return bool(on.value)


class _Api:
    """What the compact page may ask of its window."""

    def __init__(self, chat: "Compact"):
        self._chat = chat

    def away(self) -> None:
        self._chat.away()

    def full(self, place: dict) -> None:
        """The whole app window at the same place: {seq, bottom, draft} or {goto}."""
        self._chat.full(place if isinstance(place, dict) else {})


class Compact:
    def __init__(self, owner):
        self.owner = owner
        self.window = None
        self.hwnd = 0
        self.out = False
        self._lock = threading.Lock()
        # .NET holds no reference to its handler.
        self._lost = None

    def do(self, how: str, payload=None) -> None:
        if how == "show":
            self.show()
        elif how == "take":
            # Something to go with a message (pet.js petbox): the chat comes out with it.
            self.show()
            self._page(f"window.paCompact && paCompact.take({json.dumps(payload or {})})")
        elif how == "away":
            self.away()

    def _page(self, script: str) -> None:
        if self.window is not None:
            self.window.evaluate_js(script)

    def _make(self) -> None:
        import webview

        from . import window as w

        owner = self.owner
        address = urlsplit(owner.url)
        api = _Api(self)
        # As the app window: an empty page first, as WebView2 takes its menu setting from the next load on.
        win = webview.create_window(w.TITLE, html="<!doctype html><title></title>", width=SIZE[0], height=SIZE[1],
                                    hidden=True, frameless=True, on_top=True, resizable=False, easy_drag=False,
                                    text_select=True, shadow=True)
        # Known at once, so that quitting closes it too (AppWindow.close); quit before that, it goes here.
        self.window = win
        if owner._leaving:
            win.destroy()
            return
        win.expose(api.away, api.full)
        win.events.loaded.wait(LOAD_S)
        w._text_menus(win)
        w._own_pages(win, f"{address.scheme}://{address.netloc}", owner.open_link)
        win.events.loaded.clear()
        win.load_url(urlunsplit((address.scheme, address.netloc, "/compact", "", address.fragment)))
        win.events.loaded.wait(LOAD_S)
        form = win.native
        user32 = owner._user32

        def dress() -> None:
            self.hwnd = form.Handle.ToInt64()
            # A panel: no taskbar button and not in Alt+Tab.
            style = user32.GetWindowLongW(self.hwnd, _GWL_EXSTYLE)
            user32.SetWindowLongW(self.hwnd, _GWL_EXSTYLE, (style | _WS_EX_TOOLWINDOW) & ~_WS_EX_APPWINDOW)
            # DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND: Windows 11's rounded corners; nothing on Windows 10.
            ctypes.WinDLL("dwmapi").DwmSetWindowAttribute(ctypes.c_void_p(self.hwnd), 33,
                                                          ctypes.byref(ctypes.c_int(2)), 4)
            self._lost = lambda sender, args: threading.Thread(target=self._left, name="mibo-compact",
                                                               daemon=True).start()
            form.Deactivate += self._lost

        owner._on_pet(dress)

    def _spot(self) -> tuple[int, int, int, int, int]:
        """On the pet's thread: beside the figure, on the side with room, its bottom on the figure's feet,
        all of it on the pet's monitor's work area, at that monitor's scale. Left, top, width, height,
        and which way it slid in from (1 from the left, -1 from the right)."""
        from System.Windows.Forms import Screen

        from . import window as w

        owner = self.owner
        box, scale = wintypes.RECT(), owner._pet_scale
        owner._user32.GetWindowRect(owner._pet_hwnd, ctypes.byref(box))
        x0, _, x1, y1 = (round(v * scale) for v in owner._outline)
        fx = box.right - box.left - round(w.PET_SIZE[0] * scale) if owner._card == "left" else 0
        fy = box.bottom - box.top - round(w.PET_FIGURE[1] * scale)
        left, right, feet = box.left + fx + x0, box.left + fx + x1, box.top + fy + y1
        wide, high, gap = round(SIZE[0] * scale), round(SIZE[1] * scale), round(GAP * scale)
        area = Screen.FromHandle(owner._pet.native.Handle).WorkingArea
        if right + gap + wide <= area.Right:
            x, side = right + gap, 1
        elif left - gap - wide >= area.Left:
            x, side = left - gap - wide, -1
        else:
            x, side = min(max(right + gap, area.Left), area.Right - wide), 1
        y = min(max(feet - high, area.Top), area.Bottom - high)
        return x, y, wide, high, side

    def show(self) -> None:
        owner = self.owner
        if owner._pet is None or owner._attached or owner._hushed:
            return
        with self._lock:
            if self.window is None:
                self._make()
            if self.out:
                return
            self.out = True
            form, user32 = self.window.native, owner._user32
            moving = _motion()
            spot = {}

            def place() -> None:
                x, y, wide, high, side = self._spot()
                slide = round(SLIDE * owner._pet_scale) * side if moving else 0
                spot.update(x=x, y=y, slide=slide)
                form.Opacity = 0 if moving else 1
                # Twice: moved onto a monitor of another scale, Windows may size it for the old one first.
                for _ in range(2):
                    user32.SetWindowPos(self.hwnd, wintypes.HWND(-1), x - slide, y, wide, high, _SWP_NOACTIVATE)
                form.Show()
                form.Activate()
                user32.SetForegroundWindow(self.hwnd)
                form.browser.webview.Focus()

            owner._on_pet(place)
            self._page("window.paCompact && paCompact.shown()")
            owner._tell(owner._pet, "window.petChat && petChat(true)")
            if moving:
                for i in range(1, STEPS + 1):
                    share = 1 - (1 - i / STEPS) ** 3
                    owner._on_pet(lambda share=share: (
                        setattr(form, "Opacity", share),
                        user32.SetWindowPos(self.hwnd, None, spot["x"] - round(spot["slide"] * (1 - share)),
                                            spot["y"], 0, 0, 0x0001 | 0x0004 | _SWP_NOACTIVATE)))
                    time.sleep(STEP_S)

    def _left(self) -> None:
        """Out of the front: put away, unless what came in front is its own, as "+"'s file picker is."""
        time.sleep(0.05)
        user32 = ctypes.WinDLL("user32")
        user32.GetForegroundWindow.restype = user32.GetAncestor.restype = wintypes.HWND
        user32.GetAncestor.argtypes = [wintypes.HWND, ctypes.c_uint]
        front = user32.GetForegroundWindow()
        # GA_ROOTOWNER: the window a dialog belongs to.
        if front and user32.GetAncestor(front, 3) == self.hwnd:
            return
        self.away()

    def away(self, fade: bool = True) -> None:
        # One at a time with show(): a click on the figure can put it away twice (the focus lost, then the click).
        with self._lock:
            if not self.out:
                return
            self.out = False
            form = self.window.native
            if fade and _motion():
                for i in range(STEPS - 2, -1, -2):
                    self.owner._on_pet(lambda share=i / STEPS: setattr(form, "Opacity", share))
                    time.sleep(STEP_S)
            self.owner._on_pet(form.Hide)
            self.owner._tell(self.owner._pet, "window.petChat && petChat(false)")

    def full(self, place: dict) -> None:
        """The whole window, on the same place in the conversation and with the draft, or on `goto`."""
        self.away(fade=False)
        owner = self.owner
        goto = str(place.get("goto") or "chat")
        owner.open_at(goto if goto in ("chat", "settings") else "chat")
        if goto == "chat":
            keep = {"seq": int(place.get("seq") or 0), "bottom": bool(place.get("bottom")),
                    "draft": str(place.get("draft") or "")[:8000]}
            owner._tell(owner._window, f"window.paCompact && paCompact.arrive({json.dumps(keep)})")


def warm(owner) -> None:
    """Made out of sight a while after the start: made on the first click, it would take seconds to come."""
    def make() -> None:
        chat = of(owner)
        with chat._lock:
            if chat.window is None and not owner._leaving:
                chat._make()

    timer = threading.Timer(WARM_S, make)
    timer.daemon = True
    timer.start()


def of(owner) -> Compact:
    """The app window's compact chat, made the first time it is asked for."""
    chat = getattr(owner, "_compact", None)
    if chat is None:
        chat = owner._compact = Compact(owner)
    return chat
