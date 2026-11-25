"""The pet on Windows: a small window with nothing in it but the character, standing on the desktop or
peeking over the app window's top edge, out of sight while a game or something full screen is in front.
AppWindow takes these methods from `PetWindow`; how it walks, is dragged and grows for a card is in
petmoves.py, its menu in petmenu.py."""
from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable
from urllib.parse import urlsplit, urlunsplit

from .. import petchat, petoff, petshot, quiet
from . import native, petmenu, winforms
from .native import (
    GWL_EXSTYLE,
    GWLP_HWNDPARENT,
    HWND_NOTOPMOST,
    HWND_TOPMOST,
    KEEP_ORDER,
    NO_FOCUS,
    ORDER_ONLY,
    RGN_OR,
    SW_HIDE,
    SW_RESTORE,
    SW_SHOWNOACTIVATE,
    WS_EX_APPWINDOW,
    WS_EX_NOACTIVATE,
    WS_EX_TOOLWINDOW,
)

# The pet's window: the character drawn in the 200 by 214 at its bottom (PET_FIGURE);
# the 64 above hold its dial and the line of what it is doing (pet.js HEAD_ROOM),
# taking the pointer only while they show.
PET_SIZE = (200, 278)
PET_FIGURE = (200, 214)
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
# The pet's eyes follow the cursor this near its window (CSS px), looked for this often;
# and the person is back when the keyboard or mouse is used after this long without.
NEAR_PX = 240
NEAR_STEP_S = 0.12
AWAY_S = 300


class PetApi:
    """What the pet's page may ask of its window."""

    def __init__(self, owner: PetWindow):
        self._owner = owner

    def open(self) -> None:
        self._owner.show()

    def menu(self) -> None:
        petmenu.show(self._owner)

    def walk(self, dx: float, ms: float) -> None:
        """A walk of `ms` milliseconds, `dx` CSS px every 30 ms; back when it ends."""
        self._owner._pet_walk(dx, ms)

    def place(self, x: float, start: float) -> None:
        """The page walks it: its window's left edge to `x` CSS px on the screen,
        moved when the page draws the feet that stand still as it goes; `start`
        is where it was as this walk began."""
        self._owner._pet_place(x, start)

    def rest(self) -> None:
        """Stop walking now: pressed, or a card is coming."""
        self._owner._walking = False

    def drag(self, x: float, y: float) -> None:
        """The pet's window follows the cursor until the button is let go,
        held where it was pressed: (x, y) CSS px inside it."""
        self._owner._pet_drag(x, y)

    def drop(self) -> None:
        self._owner._dragging = False

    def words(self) -> dict:
        """The labels of the small actions beside the pet: the same as its menu's."""
        return self._owner.words()

    def room(self, on: bool) -> None:
        """While it moves, its window takes the pointer round all of it, so a
        move is never cut; at rest only round the figure."""
        self._owner._pet_room(on)

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

    def spots(self, boxes: list, bare: bool = False) -> None:
        """What else takes the pointer round the figure: [x, y, width, height, corner] CSS px
        of the pet's 200 by 278 cell; `bare` while the figure itself takes none (tucked)."""
        self._owner._pet_spots(boxes, bare)

    def chat(self, how: str, payload: dict | None = None) -> None:
        """Its compact chat beside it (petchat.py): "show", "away", or "take" with what to attach."""
        petchat.of(self._owner).do(how, payload)

    def tuck(self) -> str:
        """Let go near a side of the screen with no other screen beyond: flush against it,
        and which side, "left" or "right"; else ""."""
        return self._owner._pet_tuck()

    def browse(self, address: str) -> None:
        """Its dial's "Open the browser": the app window, `address` in its browser."""
        if urlsplit(address).scheme in ("http", "https"):
            self._owner._pet_browse(address)


class PetWindow:
    """The pet's half of AppWindow: its state, its poses over the app window and on the ground, the shape
    that takes the pointer, and its hiding while quiet."""

    def _init_pet(self) -> None:
        self._pet = None
        self._pet_strip = None
        self._pet_hwnd = self._main_hwnd = 0
        # Device px per CSS px of the monitor the pet is on (native.watch_scale), and its handler,
        # which .NET holds no reference to; and the pet's walk: where it began, CSS px and device px.
        self._pet_scale = 1.0
        self._pet_scale_watch = None
        self._rescaling = False
        self._walk_from = (None, 0)
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
        # What else the page shows round the figure (its dial, the line above it, a tucked head):
        # [x, y, width, height, corner] CSS px of the window; with `_bare` the figure itself takes nothing.
        self._spots: list = []
        self._bare = False
        # The compact chat beside the pet (petchat.of), made the first time it is asked for.
        self._compact = None
        # One way at a time: to the window or back to the ground.
        self._turn = threading.Lock()
        self._dragging = False
        self._walking = False
        # The app window's move handler; .NET holds no reference.
        self._watch = None
        # Which side of the figure a card is open on: "left", "right", or "" for none.
        self._card = ""
        # Out of sight while a game or something full screen is in front (quiet.py).
        # The tray brings it back, and then it stays until quiet starts again.
        self._hushed = False
        self._by_hand = False
        # Hidden from its own menu: it stays so until the tray brings it back.
        self._tucked = False
        # Moving: its window takes the pointer round all of it (_pet_room).
        self._room = False
        self._hush = threading.Lock()
        # 显示桌宠 off (petoff.py): no figure, finds as a card alone at the screen's corner; the tray turns it on.
        self._pet_off = False
        # Menu handlers stay referenced here, or .NET would lose them.
        self._pet_click = lambda sender, event: petoff.turn(self, True) if self._pet_off else self._show_pet()
        self._figure_click = lambda sender, event: (self.choose(str(sender.Tag)), self.refigure())
        self._settings_click = lambda sender, event: self.open_at("settings")
        self._bring_click = lambda sender, event: self._tell(self._pet, "petBring()")
        self._snooze_click = lambda sender, event: self._tell(
            self._pet, "petSnooze(true)" if str(sender.Tag) == "on" else "petSnooze(false)")
        self._tuck_click = lambda sender, event: petoff.turn(self, False)
        self._share_click = lambda sender, event: petshot.save(self)

    @property
    def pet_url(self) -> str:
        address = urlsplit(self.url)
        return urlunsplit((address.scheme, address.netloc, "/pet", "", address.fragment))

    # What the pet's page is told as it happens (pet.js).

    def pet_look(self) -> None:
        """A line or something found is waiting for the pet: it looks now."""
        if self.opened and self._pet is not None and not self._hushed:
            self._tell(self._pet, "petLook()")

    def pet_busy(self, doing: str) -> None:
        """What the character is doing in a chat, for the pet to show:
        "thinking", "searching", "reading", or "" when the turn is over."""
        if self.opened and self._pet is not None and not self._hushed:
            self._tell(self._pet, f"window.petActivity && petActivity({json.dumps(doing)})")

    def refigure(self) -> None:
        """The figure may have changed: the pet and the app window read it again.
        A hushed pet reads it when it wakes."""
        if self.opened and self._pet is not None and not self._hushed:
            self._tell(self._pet, "petFigure()")
        self._frame_changed()

    # Made and started with the app window (AppWindow.run).

    def _make_pet(self, webview, title: str) -> None:
        """The pet's window, `title` its name, made beside the app window's before the toolkit starts."""
        import ctypes
        screen = ctypes.windll.user32.GetSystemMetrics
        self._pet = webview.create_window(
            title, self.pet_url, width=PET_SIZE[0], height=PET_SIZE[1],
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
        api = PetApi(self)
        self._pet.expose(*(getattr(api, name) for name in dir(api) if not name.startswith("_")))
        # Closed on its own (Alt+F4): mibo goes with it.
        self._pet.events.closed += lambda: None if self._leaving else self.close()

    def _start_pet(self, origin: str, within: float) -> None:
        """Once the app window is up: the pet stands on the taskbar and follows the app window from now on;
        `within` seconds for each of its window's events."""
        self.hidden = True
        # Hidden behind the pet from the start, the app window's page rests once it came up.
        self._away(True)
        self._pet.events.shown.wait(within)
        self._user32 = native.user32()
        self._place_pet()
        self._on_ui(self._watch_window)
        self._pet.events.loaded.wait(within)
        winforms.own_pages(self._pet, origin, self.open_link)
        # Files, links and words dropped on the pet reach its page (pet.js), which loads none of them.
        self._on_pet(lambda: setattr(self._pet.native.browser.webview, "AllowExternalDrop", True))
        # Out of sight during games and fullscreen, from now on and at once if one is in front already.
        self._pet.events.loaded.wait(within)
        quiet.listen(self._quiet_changed)
        self._quiet_changed(quiet.state())
        threading.Thread(target=self._watch_cursor, name="mibo-near", daemon=True).start()
        if not petoff.shown(self):
            petoff.apply(self, False)
        petchat.warm(self)

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
            self._pet_scale_watch = native.watch_scale(self._pet_hwnd, self._pet_rescaled)
            area = Screen.FromControl(form).WorkingArea
            form.Left = area.Right - form.Width - int(PET_MARGIN * scale)
            form.Top = area.Bottom - form.Height
            self._shape()
            form.Show()

        self._on_pet(place)

    def _watch_window(self) -> None:
        """On the app window's thread: follow its every move from now on."""
        self._main_hwnd = self._window.native.Handle.ToInt64()
        self._watch = native.watch_moves(self._main_hwnd, self._moved)

    def _on_pet(self, action: Callable[[], object]) -> None:
        winforms.on_thread(self._pet.native, action)

    # Over the app window and back on the ground.

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
            self._away(False)
            if self._user32.IsIconic(self._main_hwnd):
                # Back from the taskbar as it was, maximized or not.
                self._user32.ShowWindow(self._main_hwnd, SW_RESTORE)
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
            threading.Thread(target=work, name="mibo-pet", daemon=True).start()

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
        self._away(True)
        self._window.hide()
        self._on_ui(lambda: setattr(form, "Opacity", 1.0))

    def _restyle(self) -> None:
        """No focus and no taskbar button for the pet's window: WinForms marks
        it as one that belongs on the taskbar, and an owner or a change of
        order must not bring the button back."""
        user32, pet = self._user32, self._pet_hwnd
        style = user32.GetWindowLongW(pet, GWL_EXSTYLE)
        user32.SetWindowLongW(pet, GWL_EXSTYLE, (style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW)

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
        self._user32.SetWindowPos(self._pet_hwnd, None, left, top, wide, high, NO_FOCUS if front else KEEP_ORDER)

    def _attach(self) -> None:
        """On the app window's thread: the pet's window is handed to the app
        window. Owned by it, it stays just above it and goes behind other apps
        with it, no longer on top of everything."""
        user32, pet = self._user32, self._pet_hwnd
        # Changed while hidden: changed while it shows, the window's see-through
        # parts come out white, and stay so until it is shown again. The pet is
        # out of sight below its window's bottom meanwhile (pet.js).
        user32.ShowWindow(pet, SW_HIDE)
        user32.SetWindowPos(pet, HWND_NOTOPMOST, 0, 0, 0, 0, ORDER_ONLY)
        user32.SetWindowLongPtrW(pet, GWLP_HWNDPARENT, self._main_hwnd)
        self._restyle()
        self._attached = True
        self._hold(front=True)
        self._shape()
        if not self._hushed:
            user32.ShowWindow(pet, SW_SHOWNOACTIVATE)

    def _land(self) -> None:
        """On the pet's thread: back on the ground where it stood, on top of everything."""
        user32, pet, scale = self._user32, self._pet_hwnd, self._pet_scale
        # As in _attach.
        user32.ShowWindow(pet, SW_HIDE)
        user32.SetWindowLongPtrW(pet, GWLP_HWNDPARENT, 0)
        user32.SetWindowPos(pet, HWND_TOPMOST, 0, 0, 0, 0, ORDER_ONLY)
        self._restyle()
        wide, high = int(PET_SIZE[0] * scale), int(PET_SIZE[1] * scale)
        left, bottom = self._ground
        user32.SetWindowPos(pet, None, left, bottom - high, wide, high, KEEP_ORDER)
        self._shape()
        if not self._hushed:
            user32.ShowWindow(pet, SW_SHOWNOACTIVATE)

    # Where its window takes the pointer.

    def _pet_room(self, on: bool) -> None:
        self._room = on
        if self._pet_hwnd and not self._attached:
            self._on_pet(self._shape)

    def _pet_measured(self, head: float, outline: list) -> None:
        self._head, self._outline = max(1, round(head)), tuple(outline)
        self._on_pet(self._reshape)

    def _pet_spots(self, boxes: list, bare: bool) -> None:
        self._spots, self._bare = [tuple(box) for box in boxes], bool(bare)
        if self._pet_hwnd and not self._attached:
            self._on_pet(self._shape)

    def _reshape(self) -> None:
        """Another figure: its window cut to it again. Shown anew after, as a
        new figure leaves the see-through parts white too (see _attach)."""
        if not self._pet_hwnd:
            # The page measured it before the window was placed, which cuts it then.
            return
        self._user32.ShowWindow(self._pet_hwnd, SW_HIDE)
        if self._attached:
            self._hold()
        self._shape()
        if not self._hushed:
            self._user32.ShowWindow(self._pet_hwnd, SW_SHOWNOACTIVATE)

    def _parts(self, wide: int, high: int) -> list[tuple[int, int, int, int, int]]:
        """What of the pet's window `wide` by `high` device px takes the pointer: each part's left, top,
        right, bottom, and how round its corners are."""
        scale = self._pet_scale
        x0, y0, x1, y1 = (round(v * scale) for v in self._outline)
        if self._attached:
            # The strip over the window's edge: as wide as the figure, all of its height.
            return [] if self._bare else [(x0, 0, x1, high, 0)]
        # The figure keeps the window's bottom corner (pet.css).
        fx = wide - round(PET_SIZE[0] * scale) if self._card == "left" else 0
        fy = high - round(PET_FIGURE[1] * scale)
        parts = [] if self._bare and not self._room else [
            (fx, fy, fx + round(PET_SIZE[0] * scale), high, 0) if self._room
            else (fx + x0, fy + y0, fx + x1, fy + y1, 0)]
        parts += [(fx + round(x * scale), high - round((PET_SIZE[1] - y) * scale),
                   fx + round((x + w) * scale), high - round((PET_SIZE[1] - y - h) * scale), round(2 * r * scale))
                  for x, y, w, h, r in self._spots]
        if self._card:
            cx, cy, cw, ch = (round(v * scale) for v in self._card_box)
            if self._card == "right":
                cx = wide - cx - cw
            # Round as the card is: the see-through corners outside it come
            # out white where they touch the window's side.
            # A pixel more all round: the card's drawn edge is soft, and a region's is not.
            parts.append((cx - 1, cy - 1, cx + cw + 1, cy + ch + 1, round(2 * CARD_RADIUS * scale) + 2))
        return parts

    def _shape(self) -> None:
        """On the pet's thread: the pet's window shows anything, and takes the
        pointer, only over the figure and the card; everywhere else a click
        goes through to whatever is behind. A window region does it: the
        system goes by it alone, whatever the page draws."""
        import ctypes
        from ctypes import byref, wintypes

        box = wintypes.RECT()
        self._user32.GetWindowRect(self._pet_hwnd, byref(box))
        gdi32 = ctypes.WinDLL("gdi32")
        gdi32.CreateRectRgn.restype = gdi32.CreateRoundRectRgn.restype = wintypes.HANDLE
        gdi32.CombineRgn.argtypes = [wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE, ctypes.c_int]
        gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
        region = gdi32.CreateRectRgn(0, 0, 0, 0)
        for *part, corner in self._parts(box.right - box.left, box.bottom - box.top):
            more = gdi32.CreateRoundRectRgn(*part, corner, corner) if corner else gdi32.CreateRectRgn(*part)
            gdi32.CombineRgn(region, region, more, RGN_OR)
            gdi32.DeleteObject(more)
        # The system owns the region from here on.
        self._user32.SetWindowRgn(self._pet_hwnd, region, True)

    # Out of sight while quiet.

    def _quiet_changed(self, state: dict) -> None:
        """quiet.py, on its own loop: a game or something full screen came to the front, or went."""
        if state["quiet"]:
            self._by_hand = False
        threading.Thread(target=self._hush_pet if state["quiet"] else self._wake_pet,
                         name="mibo-quiet", daemon=True).start()
        # The app window's page, open behind the game, asks nothing meanwhile either (app.js).
        if self.opened:
            self._tell(self._window, f"window.paQuiet && paQuiet({json.dumps(state['quiet'])})")
        # Not the pane while a video of the window's own is full screen and in front: that is what
        # made it quiet. Quiet for something else (a game come to the front) ends that full screen.
        own = state["quiet"] and self._full is not None and quiet.front().get("pid") == os.getpid()
        if state["quiet"] and self._full is not None and not own:
            self._on_ui(lambda: self._leave_full(True))
        if self._browser is not None and not own:
            self._browser.quiet(state["quiet"])

    def _show_pet(self) -> None:
        """The tray's "Show the pet": the person's choice holds until quiet starts again."""
        self._tucked = False
        self._by_hand = True
        threading.Thread(target=self._wake_pet, name="mibo-quiet", daemon=True).start()

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

    def _wake_pet(self) -> None:
        """Back where it was, on the ground or over the app window: its window
        shows with the figure still out of sight, and the figure comes up."""
        with self._hush:
            if not self._hushed or self._leaving or self._tucked or (quiet.active() and not self._by_hand):
                return
            self._on_pet(self._bring_back)
            self._pet.evaluate_js("petQuiet(false)")

    def _put_away(self) -> None:
        """On the pet's thread, which is the app window's too: _attach, _land,
        _reshape and _fit_card show the pet's window unless it is hushed.
        Its page rests before the window hides (winforms.rest)."""
        self._hushed = True
        winforms.rest(self._pet.native.browser.webview)
        self._user32.ShowWindow(self._pet_hwnd, SW_HIDE)

    def _bring_back(self) -> None:
        """On the pet's thread: the window first, then the WebView, which wakes
        its page (winforms.wake). Nothing white shows between: the window alone
        is see-through, and the page last drew the figure ducked."""
        self._hushed = False
        self._user32.ShowWindow(self._pet_hwnd, SW_SHOWNOACTIVATE)
        winforms.wake(self._pet.native.browser.webview)

    def _watch_cursor(self) -> None:
        """Tell the pet where the cursor is while it is near (its eyes follow
        it), and when the person is back after a while away. Two cheap reads
        a few times a second; the page is told only when something changed."""
        import ctypes
        from ctypes import byref, wintypes

        class LastInput(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

        user32, kernel32 = self._user32, ctypes.windll.kernel32
        kernel32.GetTickCount.restype = wintypes.DWORD
        last = LastInput(ctypes.sizeof(LastInput), 0)
        told, away = None, False
        while self.opened:
            time.sleep(NEAR_STEP_S)
            if self._hushed or not self._pet_hwnd:
                continue
            if user32.GetLastInputInfo(byref(last)):
                idle = (kernel32.GetTickCount() - last.dwTime) / 1000
                if idle > AWAY_S:
                    away = True
                elif away and idle < 1:
                    away = False
                    self._tell(self._pet, "window.petBack && petBack()")
            near = self._cursor_near()
            if near != told and (near is None or told is None or near[2] != told[2]
                                 or max(abs(near[0] - told[0]), abs(near[1] - told[1])) > 3):
                told = near
                self._tell(self._pet, f"window.petCursor && petCursor({json.dumps(near)})")

    def _cursor_near(self) -> tuple[int, int, bool] | None:
        """Where the cursor is in the standing pet's window, CSS px, and whether the button is held;
        None while it is not near or the pet is not standing still."""
        from ctypes import byref, wintypes

        if self._pose != "standing" or self._dragging or self._tucked:
            return None
        user32, at, box = self._user32, wintypes.POINT(), wintypes.RECT()
        user32.GetCursorPos(byref(at))
        user32.GetWindowRect(self._pet_hwnd, byref(box))
        middle = ((box.left + box.right) / 2, (box.top + box.bottom) / 2)
        scale = self._pet_scale
        if abs(at.x - middle[0]) >= NEAR_PX * scale or abs(at.y - middle[1]) >= NEAR_PX * scale:
            return None
        # With the button held: something may be carried to it (pet.js petdrop).
        held = user32.GetAsyncKeyState(native.primary_button(user32)) & 0x8000
        return round((at.x - box.left) / scale), round((at.y - box.top) / scale), bool(held)
