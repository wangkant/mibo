"""The pet moving on the ground on Windows: dragged, walking, tucked against a side of the screen, grown for a
card beside the figure, and kept whole from monitor to monitor. AppWindow takes these methods from `PetMoves`."""
from __future__ import annotations

import json
import threading
import time

from . import native
from .native import MOVE_ONLY, SW_HIDE, SW_SHOWNOACTIVATE
from .pet import PET_SIZE

# A pet let go this near a side of the screen, its middle in CSS px, tucks in there.
TUCK_PX = 70
# How often a dragged pet catches up with the cursor, and a walking one takes a step.
DRAG_STEP_S = 0.008
WALK_STEP_S = 0.03


class PetMoves:
    """How the pet's window moves while it stands on the ground."""

    def _pet_drag(self, x: float, y: float) -> None:
        """Move the pet's window with the cursor, the point (x, y) CSS px of it
        under the cursor, until the primary button is up or the page says it
        was let go. Read from the cursor itself, so the window keeps up however
        fast the hand moves."""
        from ctypes import byref, wintypes

        user32, pet = self._user32, self._pet_hwnd
        if self._pose != "standing":
            return
        button = native.primary_button(user32)
        at, box = wintypes.POINT(), wintypes.RECT()

        def spot(scale: float, wide: float, high: float) -> tuple[int, int, int, int]:
            """The window at `scale`, the pressed point under the cursor."""
            left, top = at.x - round(x * scale), at.y - round(y * scale)
            return left, top, left + round(wide * scale), top + round(high * scale)

        self._dragging = True
        while self._dragging and user32.GetAsyncKeyState(button) & 0x8000 and self._pose == "standing":
            user32.GetCursorPos(byref(at))
            user32.GetWindowRect(pet, byref(box))
            # Its size in CSS px; the scale is the monitor's it is on now (_pet_rescaled).
            scale = self._pet_scale
            wide, high = (box.right - box.left) / scale, (box.bottom - box.top) / scale
            goes = spot(scale, wide, high)
            other = native.monitor(user32, goes)[1]
            if other != scale:
                # Onto a monitor of another scale, where it is drawn at that one; unless at that
                # size most of it would be back on this one: then it waits at this monitor's edge.
                there = spot(other, wide, high)
                goes = (there if native.monitor(user32, there)[1] == other
                        else native.onto(user32, goes, native.monitor(user32, pet)[0]))
            user32.SetWindowPos(pet, None, goes[0], goes[1], 0, 0, MOVE_ONLY)
            time.sleep(DRAG_STEP_S)
        self._dragging = False

    def _pet_walk(self, dx: float, ms: float) -> None:
        """The pet walks sideways at `dx` CSS px every WALK_STEP_S for `ms`
        milliseconds: where it is goes by the clock, a device pixel at a time,
        so its speed holds however long a move takes. It turns round where the
        screen ends (the page is told, to face the other way). It stops when
        pressed or a card comes (rest), or when it leaves the ground or is
        hushed. One call from the page per walk."""
        from System.Windows.Forms import Screen

        form = self._pet.native
        walk = {"turned": False}
        begun = time.monotonic()

        def begin() -> None:
            area = Screen.FromControl(form).WorkingArea
            walk.update(speed=dx * form._scale / WALK_STEP_S, x=float(form.Left), at=time.monotonic(),
                        low=area.Left, high=area.Right - form.Width)

        def step() -> None:
            # On the pet's thread, so a card's resize never lands between a step's read and its move.
            if not self._walking or self._pose != "standing" or self._hushed:
                self._walking = False
                return
            now = time.monotonic()
            x = walk["x"] + walk["speed"] * (now - walk["at"])
            walk["at"] = now
            if not walk["low"] <= x <= walk["high"]:
                x = min(max(x, walk["low"]), walk["high"])
                walk["speed"], walk["turned"] = -walk["speed"], True
            walk["x"] = x
            if round(x) != form.Left:
                form.Left = round(x)

        self._on_pet(begin)
        self._walking = True
        end = begun + ms / 1000
        while self._walking and time.monotonic() < end:
            self._on_pet(step)
            if walk["turned"]:
                walk["turned"] = False
                self._pet.evaluate_js(f"petTurn({json.dumps(walk['speed'] < 0)})")
            time.sleep(DRAG_STEP_S)
        self._walking = False

    def _pet_place(self, x: float, start: float) -> None:
        """Its window's left edge to `x` CSS px, within the screen, while it stands; `start`
        is where the page saw it as this walk began. The walk goes on from where the window
        was then: the page's screen px are whole ones, and on a scaled monitor its origin in
        them is not its device px over the scale."""
        from System.Windows.Forms import Screen

        form = self._pet.native

        def move() -> None:
            if self._pose != "standing" or self._hushed:
                return
            if self._walk_from[0] != start:
                self._walk_from = (start, form.Left)
            area = Screen.FromControl(form).WorkingArea
            # `x` is a whole device px in the page's px, `start` need not be: rounded apart, each
            # step moves the window by just the device px the page drew the feet for.
            scale = form._scale
            left = self._walk_from[1] + round(x * scale) - round(start * scale)
            form.Left = min(max(left, area.Left), area.Right - form.Width)

        self._on_pet(move)

    def _pet_tuck(self) -> str:
        from System.Drawing import Point
        from System.Windows.Forms import Screen

        form, side = self._pet.native, [""]

        def tuck() -> None:
            if self._pose != "standing" or self._card:
                return
            scale = self._pet_scale
            area = Screen.FromControl(form).WorkingArea
            middle, y = form.Left + round(PET_SIZE[0] / 2 * scale), form.Top + form.Height // 2
            for name, gap, beyond in (("left", middle - area.Left, area.Left - 2),
                                      ("right", area.Right - middle, area.Right + 1)):
                # Between two screens there is no side to tuck into.
                if gap < TUCK_PX * scale and not Screen.FromPoint(Point(beyond, y)).Bounds.Contains(Point(beyond, y)):
                    form.Left = area.Left if name == "left" else area.Right - form.Width
                    side[0] = name
                    return

        self._on_pet(tuck)
        return side[0]

    def _pet_browse(self, address: str) -> None:
        self.open_at("chat")
        if self._browser is not None:
            self._browser.open(address)

    # A card beside the figure.

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
        if grow and self._card and (form.Width, form.Height) == (max(wide, int(width * scale)),
                                                                  max(high, int(height * scale))):
            # Something else in a card as big: only where the window takes the pointer changes.
            self._shape()
            return
        # Resized while it shows, its see-through parts can come out white (see _attach).
        self._user32.ShowWindow(self._pet_hwnd, SW_HIDE)
        if grow:
            width, height = max(wide, int(width * scale)), max(high, int(height * scale))
            self._card = "left" if left + wide - width >= Screen.FromControl(form).WorkingArea.Left else "right"
            form.SetBounds(left + wide - width if self._card == "left" else left, bottom - height, width, height)
        else:
            self._card = ""
            form.SetBounds(left, bottom - high, wide, high)
        self._shape()
        if self._hushed:
            return
        if grow:
            # Shown at once, it would show the page as it was drawn in the smaller
            # window, the figure out of place and cut by the new shape, for a few frames.
            self._show_when_drawn(form.Width / scale)
        else:
            self._user32.ShowWindow(self._pet_hwnd, SW_SHOWNOACTIVATE)

    def _show_when_drawn(self, wide: float) -> None:
        threading.Thread(target=self._show_grown, args=(wide,), name="mibo-card", daemon=True).start()

    def _show_grown(self, wide: float) -> None:
        """Off the pet's thread: the grown window shows once its page is laid
        out that wide and has drawn a frame or two, or after half a second."""
        began = time.monotonic()
        while time.monotonic() - began < 0.5:
            if abs(float(self._pet.evaluate_js("innerWidth") or 0) - wide) <= 1:
                time.sleep(0.05)
                break
            time.sleep(0.016)
        self._on_pet(lambda: self._hushed or self._user32.ShowWindow(self._pet_hwnd, SW_SHOWNOACTIVATE))

    def _pet_rescaled(self, scale: float, suggested: tuple[int, int, int, int]) -> None:
        """On the pet's thread: on a monitor of another scale its window keeps its size in CSS px,
        on the app window's edge or standing where it stood (its bottom, and the side the figure
        keeps), and most of it on that monitor; cut to the figure again."""
        user32, pet, form = self._user32, self._pet_hwnd, self._pet.native
        old, self._pet_scale = self._pet_scale, scale
        if self._rescaling:
            # Peeking over an app window that lies across two monitors, the new size can put the
            # pet back on the last one: it stays so, until the app window moves again.
            return
        self._rescaling = True
        shown = user32.IsWindowVisible(pet)
        # Resized while it shows, its see-through parts can come out white (see _attach).
        user32.ShowWindow(pet, SW_HIDE)
        if self._attached:
            self._hold()
        else:
            if self._card:
                wide, high = round(form.Width / old * scale), round(form.Height / old * scale)
            else:
                wide, high = int(PET_SIZE[0] * scale), int(PET_SIZE[1] * scale)
            left = form.Right - wide if self._card == "left" else form.Left
            box = (left, form.Bottom - high, left + wide, form.Bottom)
            left, top = native.onto(user32, box, native.monitor(user32, pet)[0])
            form.SetBounds(left, top, wide, high)
        self._shape()
        self._rescaling = False
        if shown and not self._hushed:
            self._show_when_drawn(form.Width / scale)
