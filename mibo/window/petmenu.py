"""The pet's right-click menu on Windows, drawn in the app's own neutral look."""
from __future__ import annotations

import ctypes
import sys
from typing import TYPE_CHECKING

from .. import petshot

if TYPE_CHECKING:
    from . import AppWindow

# The menu's colours in a light and a dark system theme (back, ink, hover, rule,
# edge), and how round its hover and its corners are (px).
MENU_COLORS = {"light": ("#ffffff", "#1f2328", "#eef1f5", "#e6e9ee", "#d9dde3"),
               "dark": ("#2b2d31", "#eceef1", "#3a3d43", "#3d4046", "#46494f")}
MENU_ROUND = 5
_menu_class = None


def _round_corners(hwnd: int) -> None:
    """Windows 11's small round corners and its own thin edge for a menu; nothing on Windows 10."""
    dwmapi = ctypes.WinDLL("dwmapi")
    # DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUNDSMALL.
    dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), 33, ctypes.byref(ctypes.c_int(3)), 4)


def _look_class():
    """The renderer's .NET class: pythonnet makes one of it, once per process."""
    global _menu_class
    if _menu_class is not None:
        return _menu_class
    import clr
    from System.Drawing import Pen, Rectangle, SolidBrush
    from System.Drawing.Drawing2D import GraphicsPath, SmoothingMode
    from System.Windows.Forms import (
        ToolStripArrowRenderEventArgs,
        ToolStripItemImageRenderEventArgs,
        ToolStripItemRenderEventArgs,
        ToolStripProfessionalRenderer,
        ToolStripRenderEventArgs,
        ToolStripSeparatorRenderEventArgs,
    )

    # pythonnet overrides a protected method only when told its .NET signature.
    def override(kind):
        return clr.clrmethod(None, [kind])

    class MenuLook(ToolStripProfessionalRenderer):
        __namespace__ = "Mibo.Pet"

        def __init__(self):
            pass

        @override(ToolStripRenderEventArgs)
        def OnRenderToolStripBackground(self, e):
            e.Graphics.Clear(self.back)

        @override(ToolStripRenderEventArgs)
        def OnRenderToolStripBorder(self, e):
            # Windows 11 draws its own edge round the rounded window.
            if not self.rounded:
                pen = Pen(self.edge)
                e.Graphics.DrawRectangle(pen, 0, 0, e.ToolStrip.Width - 1, e.ToolStrip.Height - 1)
                pen.Dispose()

        @override(ToolStripRenderEventArgs)
        def OnRenderImageMargin(self, e):
            pass

        @override(ToolStripItemRenderEventArgs)
        def OnRenderMenuItemBackground(self, e):
            if not (e.Item.Selected and e.Item.Enabled):
                return
            inset = round(2 * self.scale)
            box = Rectangle(inset, 0, e.Item.Width - 2 * inset, e.Item.Height)
            path, d = GraphicsPath(), round(MENU_ROUND * 2 * self.scale)
            path.AddArc(box.X, box.Y, d, d, 180, 90)
            path.AddArc(box.Right - d, box.Y, d, d, 270, 90)
            path.AddArc(box.Right - d, box.Bottom - d, d, d, 0, 90)
            path.AddArc(box.X, box.Bottom - d, d, d, 90, 90)
            path.CloseFigure()
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias
            brush = SolidBrush(self.hover)
            e.Graphics.FillPath(brush, path)
            brush.Dispose()
            path.Dispose()

        @override(ToolStripSeparatorRenderEventArgs)
        def OnRenderSeparator(self, e):
            pen = Pen(self.rule)
            middle, side = e.Item.Height // 2, round(10 * self.scale)
            e.Graphics.DrawLine(pen, side, middle, e.Item.Width - side, middle)
            pen.Dispose()

        @override(ToolStripArrowRenderEventArgs)
        def OnRenderArrow(self, e):
            # A small chevron for the submenu, in the text's colour.
            k = self.scale
            box, pen = e.ArrowRectangle, Pen(self.ink, 1.6 * k)
            x, y = box.X + box.Width / 2 - 2 * k, box.Y + box.Height / 2
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias
            e.Graphics.DrawLine(pen, float(x), y - 3 * k, x + 3 * k, float(y))
            e.Graphics.DrawLine(pen, x + 3 * k, float(y), float(x), y + 3 * k)
            pen.Dispose()

        @override(ToolStripItemImageRenderEventArgs)
        def OnRenderItemCheck(self, e):
            k = self.scale
            box, pen = e.ImageRectangle, Pen(self.ink, 1.6 * k)
            x, y = box.X + box.Width / 2, box.Y + box.Height / 2
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias
            e.Graphics.DrawLine(pen, x - 4 * k, float(y), x - k, y + 3 * k)
            e.Graphics.DrawLine(pen, x - k, y + 3 * k, x + 5 * k, y - 3 * k)
            pen.Dispose()

    _menu_class = MenuLook
    return _menu_class


def _look(scale: float):
    """A renderer that draws the menu flat, with a rounded hover, thin rules between groups, and the
    system's light or dark theme; `scale` device px per px, the monitor's where the menu shows."""
    import winreg

    from System.Drawing import ColorTranslator

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            light = bool(winreg.QueryValueEx(key, "AppsUseLightTheme")[0])
    except OSError:
        light = True
    look = _look_class()()
    look.back, look.ink, look.hover, look.rule, look.edge = (
        ColorTranslator.FromHtml(value) for value in MENU_COLORS["light" if light else "dark"])
    # Windows 11 (build 22000 on) rounds the menu itself (_round_corners).
    look.rounded = sys.getwindowsversion().build >= 22000
    look.scale = scale
    return look


def show(owner: AppWindow) -> None:
    """The pet's menu at the cursor, in groups: the app and its settings; a find now, or none for
    an hour; the characters; hiding the pet; quitting."""
    from System.Drawing import Font, FontStyle, Size, SystemFonts
    from System.Windows.Forms import ContextMenuStrip, Cursor, Padding, ToolStripMenuItem, ToolStripSeparator

    words = owner.words()
    figures, current = owner.figures(), owner.figure()
    snoozed = bool(owner._pet.evaluate_js("petSnoozed()"))
    form = owner._pet.native
    look = _look(form._scale)

    def px(*sizes: float):
        # A compact menu beside a small pet: rows about 28 px high at 100 %.
        return Padding(*(round(size * form._scale) for size in sizes))

    # WinForms on the .NET Framework sizes a font by the main monitor's scale, wherever the menu shows.
    points = 9 * form._scale * 96 / ctypes.windll.user32.GetDpiForSystem()

    def item(label: str, handler=None, tag: str = "") -> ToolStripMenuItem:
        entry = ToolStripMenuItem(label)
        entry.ForeColor, entry.Padding = look.ink, px(4, 4, 4, 4)
        if handler is not None:
            entry.Click += handler
        entry.Tag = tag
        return entry

    def characters(font) -> ToolStripMenuItem:
        """The submenu of figures, the one chosen ticked and bold."""
        people = item(words["characters"])
        people.DropDown.Renderer, people.DropDown.Padding = look, px(3, 4, 3, 4)
        people.DropDown.ShowImageMargin, people.DropDown.ShowCheckMargin = False, True
        for key, label in figures:
            entry = item(label, owner._figure_click, key)
            entry.Checked = key == current
            if entry.Checked:
                entry.Font = Font(font, FontStyle.Bold)
            people.DropDownItems.Add(entry)
        return people

    def make() -> None:
        # Made anew each time: the tick moves with the character chosen, the label with the snooze.
        if owner._pet_strip is not None:
            owner._pet_strip.Dispose()
        menu = ContextMenuStrip()
        menu.Renderer, menu.ShowImageMargin = look, False
        menu.Font = Font(SystemFonts.MenuFont.FontFamily, points)
        menu.Padding, menu.MinimumSize = px(3, 4, 3, 4), Size(round(148 * form._scale), 0)
        people = characters(menu.Font)
        groups = (
            (item(words["open"], owner._open_click), item(words["settings"], owner._settings_click)),
            (item(words["bring"], owner._bring_click),
             item(words["unsnooze"], owner._snooze_click, "off") if snoozed
             else item(words["snooze"], owner._snooze_click, "on")),
            (people, item(petshot.label(), owner._share_click), item(words["hide"], owner._tuck_click)),
            (item(words["quit"], owner._quit_click),),
        )
        for i, group in enumerate(groups):
            if i:
                menu.Items.Add(ToolStripSeparator())
            for entry in group:
                menu.Items.Add(entry)
        owner._pet_strip = menu
        for strip in (menu, people.DropDown):
            _round_corners(strip.Handle.ToInt64())
        # A menu with no foreground window behind it stays open when clicked away from.
        ctypes.windll.user32.SetForegroundWindow(form.Handle.ToInt64())
        menu.Show(Cursor.Position)

    owner._on_pet(make)
