"""Where the pane's WebView lies in the app window (browser.Pane): over the space the app page keeps under the
pane's bar, cut away under whatever of the app page lies over it, over the whole window for a video in full screen.
While the pane is in front the window is as wide as a site and the chat beside it want, where the screen allows
(`_room`); the size the person gave the window while a site was in front is kept."""
from __future__ import annotations

import ctypes

# The share of its screen's width the window grows to by itself when a page comes to the front, and the shape
# (width over height) it then takes: a window widened for a page is made taller with it.
ROOM_SHARE = 0.75
ROOM_SHAPE = 1.6


class PlacedPane:
    """The part of browser.Pane that places its WebView and sizes the window for it; `place` and `room` come from
    any thread, the rest runs on the form's."""

    def place(self, box: list, scale: float, cuts: list) -> None:
        self.ui(lambda: self._place(box, scale, cuts))

    def room(self, wide: float, scale: float) -> None:
        self.ui(lambda: self._room(wide, scale))

    def rescale(self, factor: float) -> None:
        """On the form's thread: the window came onto a monitor of another scale (`factor` times the
        last). The page's CSS px stay as they were, so it may not say where the pane is again."""
        if self._box is not None:
            self._place(self._css, self._scale * factor, self._cuts)

    def _place(self, box: list, scale: float, cuts: list) -> None:
        """The page's pane moved or changed size, or part of the app page came over it (`cuts`: [x, y, wide, high]
        in CSS px inside it): the WebView follows, made the first time."""
        from System.Drawing import Rectangle
        if self._tab is None:
            return
        # The app page fills the form; its CSS px times its device pixel ratio make form px.
        origin = self.form.browser.webview.Location
        x, y, wide, high = (round(v * scale) for v in box)
        self._box = Rectangle(origin.X + x, origin.Y + y, max(wide, 1), max(high, 1))
        if cuts != self._cuts:
            self._cuts_before = [*self._cuts_before[-3:], (ctypes.windll.kernel32.GetTickCount(), self._cuts)]
        self._css, self._scale, self._cuts = box, scale, cuts
        if self._view is None:
            # An empty tab (Ctrl+T, the private button) waits for an address.
            if not self._tab.pending:
                return
            self._make(self._tab)
        elif not self._full:
            self._view.Bounds = self._box
        self._cut()
        self._zoom()

    def _cut(self) -> None:
        """Under the chat laid over the page, or the bar's suggestions, the WebView is cut away, not made smaller:
        the site keeps its width and its layout, and the app page shows where it is cut. Whole again in full
        screen and with nothing over it."""
        from System.Drawing import Rectangle, Region
        if self._cuts and not self._full:
            region = Region(Rectangle(0, 0, self._box.Width, self._box.Height))
            for cut in self._cuts:
                region.Exclude(Rectangle(*(round(v * self._scale) for v in cut)))
            self._view.Region = region
        else:
            self._view.Region = None

    def _room(self, wide: float, scale: float) -> None:
        """The pane came to the front and its page asks for a window `wide` of its CSS px wide (the sidebar, a site
        at the width a desktop layout wants, the chat beside it); with 0 the pane left the front. The window grows
        to that once, taller too so it keeps a page's shape, within its monitor's work area, and never gets smaller;
        the size the person gave it while a site was in front (KEPT) is used instead of the page's. When the pane
        leaves the front the window takes back the size it had for the chat. Not while maximized or in full screen."""
        from System.Drawing import Point, Rectangle, Size
        from System.Windows.Forms import FormWindowState, Screen
        form, unit = self.form, self.form._scale
        if form.WindowState != FormWindowState.Normal or self._full:
            return
        if not wide:
            roomed, self._roomed = self._roomed, None
            if roomed is not None:
                left, top, was_wide, was_high = roomed["before"]
                # Where it stood, unless the person moved it since.
                at = Point(left, top) if form.Location.Equals(roomed["at"]) else form.Location
                form.Bounds = Rectangle(at, Size(round(was_wide * unit), round(was_high * unit)))
            return
        if self._roomed is not None:
            return
        area = Screen.FromControl(form).WorkingArea
        kept = self._kept["size"] or [(form.Width - form.ClientSize.Width + wide * scale) / unit, 0]
        # By itself it takes at most ROOM_SHARE of the screen's width; a size the person gave it may be the whole of it.
        most = area.Width if self._kept["size"] else max(form.Width, round(area.Width * ROOM_SHARE))
        width = min(max(form.Width, round(kept[0] * unit)), most)
        # Widened by itself it is made as tall as a page's shape asks, within the screen.
        high = kept[1] * unit if self._kept["size"] else width / ROOM_SHAPE
        size = Size(width, min(max(form.Height, round(high)), area.Height))
        # It grows to the right and down; a window that stood on its screen is moved back only as far as keeps it there.
        left = min(form.Left, max(area.Left, area.Right - size.Width)) if form.Right <= area.Right else form.Left
        top = min(form.Top, max(area.Top, area.Bottom - size.Height)) if form.Bottom <= area.Bottom else form.Top
        self._roomed = {"before": (form.Left, form.Top, form.Width / unit, form.Height / unit), "at": Point(left, top),
                        "size": [round(size.Width / unit), round(size.Height / unit)]}
        form.Bounds = Rectangle(Point(left, top), size)

    def _resize_end(self, sender, args) -> None:
        """The person let go of the window's edge with a site in front: that size is the one sites get from now on."""
        from System.Windows.Forms import FormWindowState
        form, roomed = self.form, self._roomed
        if roomed is None or form.WindowState != FormWindowState.Normal:
            return
        size = [round(form.Width / form._scale), round(form.Height / form._scale)]
        if max(abs(size[0] - roomed["size"][0]), abs(size[1] - roomed["size"][1])) > 2:
            roomed["size"] = self._kept["size"] = size
            self._keep()

    def _full_screen(self, sender, args) -> None:
        """A video's full screen is the whole monitor's: the window covers it (`full`, then `cover`)."""
        self.full(sender, bool(sender.ContainsFullScreenElement))

    def shows(self, core) -> bool:
        return self._core is not None and core is not None and self._core.Equals(core)

    def cover(self, mine: bool | None) -> None:
        """The window went full screen: for the pane's own video (True) its WebView covers the whole
        window; for the page's player (False) it steps out of the way. None: back where the page keeps it."""
        if self._view is None:
            return
        self._full = mine is True
        if mine:
            self._view.Bounds = self.form.ClientRectangle
            self._view.BringToFront()
        else:
            self._view.Visible = mine is None and not self._quieted and not self._hidden
            if self._box is not None:
                self._view.Bounds = self._box
        self._cut()
        # A video full screen is at 1; back in the pane, its own zoom again.
        self._zoom()
