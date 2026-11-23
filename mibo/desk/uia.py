"""How the character sees one granted program's window and acts in it: Windows
UI Automation through pythonnet's System.Windows.Automation (pywebview already
loads pythonnet on Windows), printed in the lines pageops prints for a page:

    [id] role "name" = value states

`## ` lines are named groups and panes, other lines are text shown in the
window, `*` marks ids new since the last look, `[secret]` a password field,
whose value is never asked of the program. Only the target window, the windows
it owns (its dialogs, the common file dialog) and, for a program with a process
of its own, its menus and pop-ups are read: which window is the program's is
decided by its process, never by a title. Elements of another process inside
the window are skipped with what is under them.

Actions go through UI Automation patterns first (invoke, set value, toggle,
select, expand, scroll), text into an edit control through the control's own
messages; real input (keys, a click at a point) only where a control offers
none, where its pattern did not take (text climbs from the value to the focus
and keys, a click and keys, then a paste, each rung read back: `climb`; a
press whose action fails ends in a click), or where the action is input by
nature (a right-click menu through Shift+F10, a double click), only once the
person has left the keyboard and mouse alone,
and only after the target window is the one in front and the focused
control is checked. Before any action the element is read again: it must still
be the kind and name the look printed, or it is found again by them, or nothing
is pressed. After it the program is read again, and the line says what changed
as the program now shows it (a display, a field's text, a tick, a selection, a
window): what was done is the program's word, not the action's.

The line grammar, the drop rule for nameless groups and the RuntimeId handles
follow dsh's cua-windows AccessibilityText.cs and Accessibility.cs (MIT, see
NOTICE); the rest is ours.
"""
from __future__ import annotations

import base64
import io
import os
import re
import time
from collections.abc import Callable

from ..web.pageprint import STATE_MAX
from ..web.pagewords import SECRET_LABEL, clip, quote, well_formed
from ..web.pagewords import norm as _norm
from . import shape, win32

ASSEMBLY = ", Version=4.0.0.0, Culture=neutral, PublicKeyToken=31bf3856ad364e35"
# At most this many elements are read of one look; a value is cut at these lengths.
NODES_MAX = 2500
VALUE_MAX = 100
DOCUMENT_MAX = 4000
# Fewer controls than this and the picture carries a grid of numbered points to click.
FEW = 3
GRID = (8, 6)
# An action's result is waited for on the program's state: read again until something changed, this long at most.
SETTLE_S = 0.45
PRESS_S = 0.3
OPENS_S = 1.5
# Real input waits until the person has left the keyboard and mouse alone this long, and this long at most.
IDLE_S = 1.5
IDLE_MAX_S = 10.0
POLL_S = 0.03
# Lines of change one action reports, and how many shown texts are read again after each action.
CHANGES_MAX = 6
WATCHED_MAX = 40
# Parents whose children scrolled out of view are counted on a line of their own.
LISTS = {"list", "tree", "table", "grid", "menu"}
# A combo box's choices are printed with it, this many at most.
OPTIONS_MAX = 12
# A Chromium-drawn page asked for its tree is waited for this long at most.
WAKE_S = 2.5
# Nameless controls and pictures described in one look, and the smallest picture worth a line.
UNNAMED_MAX = 12
PICTURE_MIN = 16

ROLES = {
    "Button": "button", "SplitButton": "button", "Edit": "textbox", "Document": "document", "Hyperlink": "link",
    "CheckBox": "checkbox", "RadioButton": "radio", "ComboBox": "combobox", "List": "list", "ListItem": "listitem",
    "Menu": "menu", "MenuBar": "menubar", "MenuItem": "menuitem", "Tab": "tablist", "TabItem": "tab",
    "Tree": "tree", "TreeItem": "treeitem", "Slider": "slider", "Spinner": "spinbutton", "Text": "text",
    "Window": "window", "Pane": "pane", "Group": "group", "DataItem": "row", "DataGrid": "grid", "Table": "table",
    "Header": "header", "HeaderItem": "columnheader", "ToolBar": "toolbar", "StatusBar": "status",
    "TitleBar": "titlebar", "ScrollBar": "scrollbar", "Image": "img", "ProgressBar": "progressbar",
    "Calendar": "calendar", "Custom": "custom", "Thumb": "thumb", "ToolTip": "tooltip", "Separator": "separator",
    "SemanticZoom": "pane", "AppBar": "toolbar",
}
# Containers whose name is printed as a `## ` line when nothing can be done with them.
HEADED = {"window", "pane", "group", "toolbar", "menubar", "status", "tablist", "table", "grid", "custom"}
# Not printed, with what is under them: the window's own frame buttons and the scroll bars (scroll is an action).
SKIPPED = {"titlebar", "scrollbar", "thumb", "tooltip", "separator"}
CONTROLS = {"button", "textbox", "document", "link", "checkbox", "radio", "combobox", "listitem", "menuitem",
            "tab", "treeitem", "slider", "spinbutton", "row", "columnheader"}
# Top-level windows that are never part of a program even when its process owns them.
NOT_WINDOWS = {"tooltips_class32", "IME", "MSCTFIME UI", "SysShadow", "Shell_TrayWnd", "Shell_SecondaryTrayWnd",
               "Progman", "WorkerW"}
KEY_NAMES = set(win32.VK) - {"Ctrl", "Shift", "Alt", "Apps"}
BIDI = re.compile(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069]")


class Refused(Exception):
    """An action this layer will not do; its text goes back to the loop as is."""


class Missed(Exception):
    """One rung of a write or a focus that did not get to the field; the next rung is tried."""


def _why(e: Exception) -> str:
    """An exception's first line, as a step's line quotes it."""
    return (str(e).splitlines() or [type(e).__name__])[0][:120]


# The controls a write or a key may click into: a click on any other would press it.
FIELDS = {"textbox", "document", "combobox"}
# The rungs a write climbs, as its line names them.
BY_VALUE, BY_MESSAGES, BY_KEYS, BY_CLICK, BY_FOCUS_PASTE, BY_PASTE = (
    "its value", "the edit control's own messages", "focusing it and typing", "a click on it and typing",
    "focusing it and a paste", "a click on it and a paste")
HOW = {BY_VALUE: "", BY_MESSAGES: "", BY_KEYS: " (typed)", BY_CLICK: " (typed after a click on it)",
       BY_FOCUS_PASTE: " (through the clipboard, theirs put back)",
       BY_PASTE: " (pasted after a click on it, through the clipboard, theirs put back)"}
# A write into a field that offers no way to read its text back.
UNREAD = "the field gives no way to read its text back, so look before going on"


def plain_text(s: str) -> str:
    """A field's text as a person reads it: Chromium keeps a typed space as a no-break space."""
    return s.replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")


def same_text(a: str, b: str) -> bool:
    """Whether two texts of a field read the same, the line break a document ends in aside."""
    return plain_text(a).strip("\n") == plain_text(b).strip("\n")


def _before(tried: list[str]) -> str:
    """What a write's line adds about the rungs that did not take before the one that did."""
    return f"; before that, {clip(' and '.join(tried), 200)} did not take" if tried else ""


def _held_by(el) -> str | None:
    """What a live element holds now, or None when it offers no way to say."""
    A = automation()
    if el.GetCurrentPropertyValue(A.AutomationElement.IsTextPatternAvailableProperty):
        return str(el.GetCurrentPattern(A.TextPattern.Pattern).DocumentRange.GetText(-1))
    if el.GetCurrentPropertyValue(A.AutomationElement.IsValuePatternAvailableProperty):
        return str(el.GetCurrentPropertyValue(A.ValuePattern.ValueProperty) or "")
    return None


def climb(rungs: list[tuple[str, Callable[[], None]]], read: Callable[[], str] | None,
          landed: Callable[[str], bool], *, again: bool) -> tuple[str, str, list[str]]:
    """Write into a field by the first rung that takes, as computer-use and UI automation tools write into a
    Chromium text field: its value, then the focus and keys, then a real click and keys or a paste. After each
    rung the field is read back (until `landed`, SETTLE_S at most): that, not the rung, decides. Returns (the
    rung that took or "", what the field holds, the rungs that did not take with why). A rung that changed the
    field without landing ends the climb unless `again` (each rung writes the whole text over): a next rung
    would put the text in twice. With no `read` the field cannot be read back: the first rung that runs is
    taken, unproven."""
    was = read() if read else ""
    holds, tried = was, []
    for name, act in rungs:
        try:
            act()
        except Refused:
            raise
        except Exception as e:
            tried.append(f"{name} ({clip(_why(e), 90)})")
            continue
        if read is None:
            return name, "", tried
        end = time.monotonic() + SETTLE_S
        holds = read()
        while not landed(holds) and time.monotonic() < end:
            time.sleep(POLL_S)
            holds = read()
        if landed(holds):
            return name, holds, tried
        tried.append(name)
        if not again and holds != was:
            break
    return "", holds, tried


_A = None


def automation():
    """System.Windows.Automation, loaded once per process."""
    global _A
    if _A is None:
        import clr
        clr.AddReference("UIAutomationClient" + ASSEMBLY)
        clr.AddReference("UIAutomationTypes" + ASSEMBLY)
        import System.Windows.Automation as A
        _A = A
    return _A


def norm(s) -> str:
    """pagewords.norm, less the invisible direction marks Windows puts round dates."""
    return _norm(BIDI.sub("", "" if s is None else str(s)))


def element(hwnd: int):
    """The automation element of a window handle."""
    from System import IntPtr
    return automation().AutomationElement.FromHandle(IntPtr(hwnd))


def _cache():
    A = automation()
    c = A.CacheRequest()
    c.TreeScope = A.TreeScope.Subtree
    c.TreeFilter = A.Automation.ControlViewCondition
    E = A.AutomationElement
    for p in (E.RuntimeIdProperty, A.ScrollPattern.VerticallyScrollableProperty,
              A.ScrollPattern.VerticalViewSizeProperty, A.ScrollPattern.VerticalScrollPercentProperty,
              E.ControlTypeProperty, E.NameProperty, E.AutomationIdProperty, E.ClassNameProperty,
              E.HelpTextProperty, E.IsEnabledProperty, E.HasKeyboardFocusProperty, E.IsPasswordProperty,
              E.IsOffscreenProperty,
              E.BoundingRectangleProperty, E.ProcessIdProperty, E.IsKeyboardFocusableProperty,
              E.NativeWindowHandleProperty, E.IsInvokePatternAvailableProperty, E.IsValuePatternAvailableProperty,
              E.IsTogglePatternAvailableProperty, E.IsSelectionItemPatternAvailableProperty,
              E.IsExpandCollapsePatternAvailableProperty, E.IsScrollPatternAvailableProperty,
              E.IsRangeValuePatternAvailableProperty, E.IsTextPatternAvailableProperty,
              A.TogglePattern.ToggleStateProperty, A.ExpandCollapsePattern.ExpandCollapseStateProperty,
              A.SelectionItemPattern.IsSelectedProperty, A.ValuePattern.IsReadOnlyProperty,
              A.RangeValuePattern.ValueProperty):
        c.Add(p)
    return c


class Node:
    """What one look read of one element, and the live element to act on."""
    __slots__ = (
        "auto",
        "cells",
        "cls",
        "el",
        "enabled",
        "focused",
        "hwnd",
        "name",
        "parent",
        "patterns",
        "pid",
        "readonly",
        "rect",
        "role",
        "secret",
        "top",
        "where",
    )

    def __init__(self, **kw):
        self.where = ""
        for k, v in kw.items():
            setattr(self, k, v)

    def center(self) -> tuple[int, int]:
        x, y, wide, high = self.rect
        return int(x + wide / 2), int(y + high / 2)


def _get(el, prop):
    """A cached property, None where the element does not support it."""
    v = el.GetCachedPropertyValue(prop, True)
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    return None if automation().AutomationElement.NotSupported.Equals(v) else v


class View:
    """One granted program's target window: `look()` prints it, the actions act by the ids of the last look.
    `pid` is the program's process: its windows are its own; inside the target, what the processes it started
    draw counts too (a WebView2 page in the program). `shared` is true for a process that also draws other
    things (File Explorer is the taskbar and the desktop too), where only the target and the windows it owns
    are read. `halted()` says why to stop between the steps of one action ("" to go on); `never(hwnd)` why a
    window of the program is still not read."""

    def __init__(self, hwnd: int, pid: int, *, shared: bool = False,
                 halted: Callable[[], str] = lambda: "", never: Callable[[int], str] = lambda h: "",
                 busy: Callable[[], None] = lambda: None):
        win32.dpi_aware()
        self.hwnd = hwnd
        self.pid = pid
        self.pids = {pid} if shared else win32.descendants(pid)
        self.shared = shared
        self.halted = halted
        self.never = never
        self.busy = busy
        self.nodes: dict[int, Node] = {}
        self.handles: dict[str, int] = {}
        self.seen: set[int] = set()
        self.grid: dict[str, tuple[int, int]] = {}
        self.interactive = 0
        self.words: dict[int, list[str]] = {}
        self.forwarded = False
        self.serial = 0
        self.shown: dict[str, tuple] = {}
        # The last look's lines uncut, each id's own line and the lines under it, and what the print left out.
        self.lines: list[str] = []
        self.spans: dict[int, tuple[int, int]] = {}
        self.cut: list[tuple[int, int]] = []
        self.seen: tuple = ()
        self.named = 0
        self.drawn = 0.0
        self.snap: tuple[float, dict] | None = None
        self.own: set[int] | None = None
        # The menus `menu` opened, each with the control it was opened on, read with the window while they show.
        self.menus: dict[int, Node] = {}
        # Chromium page windows already asked for their tree, and whether the last look had one that gave nothing.
        self.woken: set[int] = set()
        self.asleep = False
        # The controls of the last look that have no name, described by where they are and how they look.
        self.unnamed: list[str] = []

    # --- which windows are the program's

    def windows(self) -> list[int]:
        """The target first, then the program's other shown windows that belong with it."""
        if not win32.alive(self.hwnd):
            return []
        out = [self.hwnd]
        for h in win32.top_windows():
            if h == self.hwnd or win32.pid_of(h) != self.pid or not win32.shown(h):
                continue
            if win32.class_of(h) in NOT_WINDOWS or self.never(h):
                continue
            owned = win32.root_owner(h) == self.hwnd or win32.owner_of(h) == self.hwnd
            if owned or (not self.shared and win32.class_of(h) == "#32768"):
                out.append(h)
            elif win32.owner_of(h) == 0 and win32.popup(h) and (
                    not self.shared or win32.thread_of(h) == win32.thread_of(self.hwnd)):
                # A pop-up of its own process with no owner and no title bar (a flyout, a drop-down list);
                # the program's other main windows are not read with this one. In a process that draws other
                # things too (File Explorer), only a pop-up made by the target window's own thread.
                out.append(h)
        for h in list(self.menus):
            if not win32.shown(h):
                self.menus.pop(h, None)
            elif h not in out:
                out.append(h)
        return out

    def ours(self, pid: int) -> bool:
        return pid in self.pids

    def moved(self) -> bool:
        """A window of the program came up since the last look (a dialog by itself) that the look did not read.
        One that went (a menu that closed) is not this: an action on what was in it finds its control gone."""
        return bool(set(self.windows()) - set(self.seen))

    def unfolded(self) -> bool:
        """Every window that came up since the last look is a menu or a pop-up without a title bar: what a
        press unfolds, not a dialog to be read first."""
        new = set(self.windows()) - set(self.seen)
        return bool(new) and all(win32.class_of(h) == "#32768" or win32.popup(h) for h in new)

    def wake(self, wins: list[int]) -> None:
        """A Chromium-drawn page (Electron, WebView2, CEF) builds its accessibility tree only once a client asks for
        it. Each page window not asked before is asked as assistive tools ask (the screen-reader probe, then its
        root's name read through UI Automation, which Chromium takes as a client using the page), and waited for
        until the page shows elements, WAKE_S at most. `asleep` is left true when one still shows none."""
        A = automation()
        pages = [h for top in wins for h in win32.chromium_pages(top) if h not in self.woken]
        walker = A.TreeWalker.ControlViewWalker

        def ready(h: int) -> bool:
            try:
                doc = walker.GetFirstChild(element(h))
                if doc is None:
                    return False
                # Reading a name is what Chromium counts as a client using the page.
                _ = doc.Current.Name
                return walker.GetFirstChild(doc) is not None
            except Exception:
                return False
        for h in pages:
            self.woken.add(h)
            win32.probe_page(h)
        waiting = [h for h in pages if not ready(h)]
        end = time.monotonic() + WAKE_S
        while waiting and time.monotonic() < end and not self.halted():
            time.sleep(0.1)
            waiting = [h for h in waiting if not ready(h)]
        self.asleep = bool(waiting)

    # --- looking

    def look(self, max: int = STATE_MAX) -> str:
        A = automation()
        cache = _cache()
        previous = set(self.nodes)
        self.nodes, self.grid, self.interactive, self.words, self.shown = {}, {}, 0, {}, {}
        self.spans, self.cut = {}, []
        self.serial += 1
        lines: list[str] = []
        count = 0
        wins = self.windows()
        if not wins:
            raise Refused("[gone] the window is closed")
        self.seen = tuple(wins)
        self.wake(wins)
        # How much of the target window the structure names: its small named controls, and its big nameless
        # areas (a canvas), as see/when.py counts them.
        frame = win32.rect(self.hwnd)
        area = (frame[2] - frame[0]) * (frame[3] - frame[1]) or 1
        small: list[tuple] = []
        blank: list[tuple] = []
        # The target window's texts with their boxes, and its nameless controls and pictures: (line, head, box, kind).
        texts: list[tuple[str, tuple]] = []
        nameless: list[tuple[int, str, tuple, str]] = []
        # The boxes of the web pages read by their controls: the surface Chromium draws them on is not a drawn area.
        pages: list[tuple] = []

        def more(el, role: str, name: str, children) -> None:
            """A list's rows that are scrolled out of view are not printed: say how many, and how to reach one."""
            if role not in LISTS:
                return
            hidden = sum(1 for c in children if _get(c, A.AutomationElement.IsOffscreenProperty))
            if hidden and hidden < len(children):
                lines.append(f"... {hidden} more in {quote(clip(name, 40)) if name else 'this ' + role} are scrolled "
                             f"out of view: select one with its name as \"option\", or scroll")
            elif _get(el, A.ScrollPattern.VerticallyScrollableProperty) and float(
                    _get(el, A.ScrollPattern.VerticalViewSizeProperty) or 100) < 99:
                at = float(_get(el, A.ScrollPattern.VerticalScrollPercentProperty) or 0)
                lines.append(f"... {quote(clip(name, 40)) if name else 'this ' + role} has more rows "
                             f"{'below' if at < 1 else 'above' if at > 99 else 'above and below'}: scroll to read them")

        def read(el, top: int, inside: str, parent: Node | None, where: str = "") -> None:
            """One element and what is under it; a big nameless one with nothing named inside is a drawn area."""
            printed, seen = len(lines), []
            walk(el, top, inside, parent, where, seen)
            if seen and top == self.hwnd:
                role, name, box = seen[0]
                if not name and role in ("pane", "custom", "document", "img", "group") and \
                        box[2] * box[3] >= 0.15 * area and not any(
                            '"' in line or not line.lstrip("*").startswith("[") for line in lines[printed:]):
                    blank.append(box)

        def walk(el, top: int, inside: str, parent: Node | None, where: str, seen: list) -> None:
            nonlocal count
            if count >= NODES_MAX:
                return
            count += 1
            ctype = _get(el, A.AutomationElement.ControlTypeProperty)
            kind = ctype.ProgrammaticName.split(".")[-1] if ctype is not None else "Custom"
            role = ROLES.get(kind, "custom")
            pid = int(_get(el, A.AutomationElement.ProcessIdProperty) or 0)
            # A packaged app's frame (ApplicationFrameHost) is not the program: only what its process draws.
            if role in SKIPPED or not self.ours(pid):
                return
            # Scrolled away, clipped by its window, or hidden.
            if _get(el, A.AutomationElement.IsOffscreenProperty) and role not in ("window", "menu"):
                return
            r = _get(el, A.AutomationElement.BoundingRectangleProperty)
            box = (int(r.X), int(r.Y), int(r.Width), int(r.Height)) if r is not None and not r.IsEmpty else (0, 0, 0, 0)
            name = norm(_get(el, A.AutomationElement.NameProperty))
            auto = str(_get(el, A.AutomationElement.AutomationIdProperty) or "")
            seen.append((role, name, box))
            if top == self.hwnd and role in CONTROLS and name and box[2] * box[3] < 0.15 * area:
                small.append(box)
            patterns = [p for p, prop in (
                ("invoke", A.AutomationElement.IsInvokePatternAvailableProperty),
                ("value", A.AutomationElement.IsValuePatternAvailableProperty),
                ("toggle", A.AutomationElement.IsTogglePatternAvailableProperty),
                ("select", A.AutomationElement.IsSelectionItemPatternAvailableProperty),
                ("expand", A.AutomationElement.IsExpandCollapsePatternAvailableProperty),
                ("scroll", A.AutomationElement.IsScrollPatternAvailableProperty),
                ("range", A.AutomationElement.IsRangeValuePatternAvailableProperty),
                ("text", A.AutomationElement.IsTextPatternAvailableProperty)) if _get(el, prop)]
            enabled = bool(_get(el, A.AutomationElement.IsEnabledProperty))
            focused = bool(_get(el, A.AutomationElement.HasKeyboardFocusProperty))
            focusable = bool(_get(el, A.AutomationElement.IsKeyboardFocusableProperty))
            secret = bool(_get(el, A.AutomationElement.IsPasswordProperty)) or (
                role in ("textbox", "custom") and bool(SECRET_LABEL.search(f"{name} {auto}")))
            node = Node(el=el, role=role, name=name, auto=auto, cls=str(_get(el, A.AutomationElement.ClassNameProperty)
                                                                       or ""),
                        pid=pid, enabled=enabled, focused=focused, secret=secret, rect=box,
                        hwnd=int(_get(el, A.AutomationElement.NativeWindowHandleProperty) or 0),
                        patterns=patterns, readonly=bool(_get(el, A.ValuePattern.IsReadOnlyProperty)),
                        top=top, parent=parent, cells=[], where=where)
            acts = [p for p in patterns if p != "text" or role in ("document", "textbox")]
            if role == "document" and _holds(el, CONTROLS - {"document"}):
                # A web page (Electron, WebView2, CEF, a browser) is a document full of controls: read as a group of
                # them, not as one text.
                if top == self.hwnd:
                    pages.append(box)
                if name and name.lower() not in inside:
                    lines.append(f"## {name}")
                    inside = f"{inside} {name.lower()}"
                    where = name
                for child in el.CachedChildren:
                    read(child, top, inside, parent, where)
                return
            if role in ("text", "status") and name and len(self.shown) < WATCHED_MAX:
                # A text the window shows (a display, a status line): read again after each action.
                self.shown[_rid(el)] = (el, name)
            if role == "text" and not acts:
                if name and top == self.hwnd:
                    texts.append((name, box))
                if name:
                    # A dialog's message, for the gate's reading of what its OK confirms.
                    self.words.setdefault(top, []).append(name)
                if name and name.lower() not in inside and (not lines or lines[-1] != name):
                    lines.append(name)
                return
            if not acts and not (role in CONTROLS and (focusable or name)):
                if role == "img" and not name and top == self.hwnd and min(box[2], box[3]) >= PICTURE_MIN:
                    # A picture with no name (an avatar, an icon): said where it is and how it looks.
                    lines.append("(picture)")
                    nameless.append((len(lines) - 1, "", box, "picture"))
                if name and role in HEADED and name.lower() not in inside:
                    lines.append(f"## {name}")
                    inside = f"{inside} {name.lower()}"
                    where = name
                for child in el.CachedChildren:
                    read(child, top, inside, parent, where)
                more(el, role, name, el.CachedChildren)
                return
            ident = self._handle(el)
            self.nodes[ident] = node
            self.interactive += 1
            value = "" if secret else self._value(node, kind)
            states = [s for s in self._states(el, node) if s]
            children = list(el.CachedChildren)
            if role in ("listitem", "row", "treeitem"):
                # A list view's columns (File Explorer's name, type, size, date) go on the item's own line.
                node.cells = [(norm(_get(c, A.AutomationElement.NameProperty)), self._cell(c))
                              for c in children if self._is_cell(c)]
                children = [c for c in children if not self._is_cell(c)]
            details = [v for n, v in node.cells if v and v != name]
            if value == name:
                value = ""
            if lines and lines[-1].lower() == name.lower():
                lines.pop()
            options = ""
            if role == "combobox":
                # Its choices, read from under it, so one can be selected by name without opening it.
                found = [norm(_get(item, A.AutomationElement.NameProperty)) for part in children
                         for item in [part, *part.CachedChildren]
                         if _get(item, A.AutomationElement.IsSelectionItemPatternAvailableProperty)]
                found = [o for o in found if o]
                if found:
                    options = " options: " + " | ".join(clip(o, 30) for o in found[:OPTIONS_MAX]) + (
                        f" | and {len(found) - OPTIONS_MAX} more" if len(found) > OPTIONS_MAX else "")
            # A tooltip or accessible description, when it says more than the name.
            tip = norm(_get(el, A.AutomationElement.HelpTextProperty))
            head = f"[{ident}] {role}"
            start = len(lines)
            lines.append(("*" if previous and ident not in previous else "") + head
                         + (" [secret]" if secret else "")
                         + (f' "{clip(name, 150)}"' if name else "")
                         + (f" = {quote(value)}" if value else "")
                         + (f" ({clip(', '.join(details), 150)})" if details else "")
                         + (f" tip {quote(clip(tip, 80))}" if tip and tip != name else "")
                         + (" " + " ".join(states) if states else "") + options
                         + (f" @{shape.place(box, frame).replace(' ', '-')}" if top == self.hwnd and box[2] else ""))
            self.spans[ident] = (start, len(lines))
            if not name and top == self.hwnd and box[2]:
                nameless.append((len(lines) - 1, head, box, "a picture" if _holds(el, {"img"}) else ""))
            if secret or role in ("document", "textbox"):
                return
            inside = f"{inside} {name.lower()} {value.lower()}"
            for child in children:
                read(child, top, inside, node, where)
            more(el, role, name, children)
            # Its own line and the lines under it, for a look at one part (surface.py's look, ref).
            self.spans[ident] = (start, len(lines))

        for i, h in enumerate(wins):
            if self.halted():
                break
            root = None
            for _again in range(3):
                # A window in the middle of drawing itself again can fail to answer: asked again before it is
                # taken to have nothing to read.
                try:
                    root = element(h).GetUpdatedCache(cache)
                    break
                except Exception:
                    time.sleep(0.25)
            if root is None:
                continue
            title = win32.title_of(h)
            if i:
                lines.append(f"--- window {quote(clip(title, 80))} ({(win32.class_of(h) == '#32768' and 'menu') or 'dialog'}) ---")
            for child in root.CachedChildren:
                read(child, h, title.lower(), None)
        self.named = len(small)
        self.unnamed = self._describe(lines, nameless, texts, frame)
        blank = [b for b in blank if not any(shape.overlap(b, page) >= 0.5 * b[2] * b[3] for page in pages)]
        free = [b[2] * b[3] - sum(c[2] * c[3] for c in small if c[0] >= b[0] and c[1] >= b[1]
                                  and c[0] + c[2] <= b[0] + b[2] and c[1] + c[3] <= b[1] + b[3]) for b in blank]
        self.drawn = round(min(sorted(free)[-1], area) / area, 3) if free else 0.0
        header = f"[state] {clip(win32.title_of(self.hwnd), 120)}"
        asked = ", even after its page was asked for it" if self.asleep else ""
        body = lines or [f"(nothing in the accessibility tree{asked}: the window draws itself)"]
        if count >= NODES_MAX:
            body.append(f"... stopped reading at {NODES_MAX} elements")

        def fit(src: list[str], budget: float) -> int:
            size = 0
            for i, line in enumerate(src):
                size += len(line) + 1
                if size > budget:
                    return i
            return len(src)
        # Uncut, for a look at a part of it (pageprint.view_of).
        self.lines = list(body)
        if fit(body, max) < len(body):
            head = fit(body, max * 0.8)
            tail = fit(body[::-1], max * 0.2)
            self.cut = [(head, len(body) - tail)]
            body = [*body[:head], f"... {len(body) - head - tail} lines cut here", *body[len(body) - tail:]]
        return well_formed(f"{header}\n" + "\n".join(body) + "\n[/state]")

    def _describe(self, lines: list[str], nameless: list[tuple], texts: list[tuple], frame: tuple) -> list[str]:
        """Each nameless control and picture of the target window said by its size, shape and colour (read off the
        window's own picture, which stays on this computer) and the text next to it; the controls' lines, for the
        loop to name what it has not tried."""
        if not nameless:
            return []
        image, origin = win32.capture(self.hwnd)
        out = []
        for at, head, box, kind in nameless[:UNNAMED_MAX]:
            near = shape.label(box, texts)
            said = (shape.looks(image, box, origin) + (f", {kind}" if kind and head else "")
                    + (f"; {near}" if near else ""))
            if head:
                lines[at] = lines[at].replace(head, f"{head} (no name: {said})", 1)
                out.append(lines[at].lstrip("*"))
            else:
                lines[at] = f"(picture, no name: {said}) @{shape.place(box, frame).replace(' ', '-')}"
        return out

    def _handle(self, el) -> int:
        """A small number for an element, the same across looks while the element lives (its RuntimeId)."""
        key = _rid(el)
        if key not in self.handles:
            self.handles[key] = len(self.handles) + 1
        return self.handles[key]

    @staticmethod
    def _is_cell(el) -> bool:
        A = automation()
        if str(_get(el, A.AutomationElement.ClassNameProperty) or "") == "UIProperty":
            return True
        ctype = _get(el, A.AutomationElement.ControlTypeProperty)
        return ctype is not None and ctype.ProgrammaticName in ("ControlType.Text", "ControlType.Image") and (
            el.CachedChildren.Count == 0)

    @staticmethod
    def _cell(el) -> str:
        A = automation()
        if _get(el, A.AutomationElement.IsValuePatternAvailableProperty):
            try:
                return norm(el.GetCurrentPropertyValue(A.ValuePattern.ValueProperty))
            except Exception:
                return ""
        ctype = _get(el, A.AutomationElement.ControlTypeProperty)
        return "" if ctype is not None and ctype.ProgrammaticName == "ControlType.Image" else norm(
            _get(el, A.AutomationElement.NameProperty))

    def _value(self, node: Node, kind: str) -> str:
        A = automation()
        el = node.el
        try:
            if "text" in node.patterns and node.role == "document":
                return clip(str(el.GetCurrentPattern(A.TextPattern.Pattern).DocumentRange.GetText(DOCUMENT_MAX)),
                            DOCUMENT_MAX)
            if "value" in node.patterns:
                v = str(el.GetCurrentPropertyValue(A.ValuePattern.ValueProperty) or "")
                if v or node.role != "combobox":
                    return clip(v, DOCUMENT_MAX if node.hwnd and win32.multiline(node.hwnd) else VALUE_MAX)
            if "range" in node.patterns:
                return f"{float(_get(el, A.RangeValuePattern.ValueProperty) or 0):g}"
            if node.role == "combobox":
                # A drop-down list holds no text of its own: what it shows is its selected item.
                picked = el.GetCurrentPattern(A.SelectionPattern.Pattern).Current.GetSelection()
                return clip(", ".join(norm(it.Current.Name) for it in picked), VALUE_MAX)
        except Exception:
            return ""
        return ""

    def _states(self, el, node: Node) -> list[str]:
        A = automation()
        toggle = _get(el, A.TogglePattern.ToggleStateProperty) if "toggle" in node.patterns else None
        expand = _get(el, A.ExpandCollapsePattern.ExpandCollapseStateProperty) if "expand" in node.patterns else None
        return [
            "" if toggle is None else {"On": "checked", "Off": "unchecked"}.get(str(toggle), "mixed"),
            "" if expand is None or str(expand) == "LeafNode" else "expanded" if str(expand) == "Expanded"
            else "collapsed",
            "selected" if "select" in node.patterns and _get(el, A.SelectionItemPattern.IsSelectedProperty) else "",
            "readonly" if "value" in node.patterns and node.readonly and node.role in ("textbox", "combobox") else "",
            "disabled" if not node.enabled else "",
            "focused" if node.focused else ""]

    def describe(self, ident) -> str:
        n = self.nodes.get(ident) if isinstance(ident, int) else None
        if n is None:
            return f"[{ident}]"
        return f"[{ident}] {n.role}" + (f' "{clip(n.name, 60)}"' if n.name else "")

    def node(self, ident) -> Node:
        n = self.nodes.get(ident)
        if n is None:
            raise Refused(f"[failed] [{ident}] is not in the latest look; look again")
        return n

    def live(self, ident) -> int:
        """The id to act on, once the element is read again: it must still be the kind and name the look
        printed. One that died or changed (a list drawn again, a button renamed) is looked for again by its
        kind, name and group; when exactly one control answers to them, that one is meant. Otherwise nothing
        is done."""
        n = self.node(ident)
        try:
            now = n.el.Current
            same = norm(now.Name) == n.name and ROLES.get(
                now.ControlType.ProgrammaticName.split(".")[-1], "custom") == n.role
            seen = norm(now.Name)
        except Exception:
            same, seen = False, None
        if same:
            return ident
        was = self.describe(ident)
        self.look()
        hits = [i for i, m in self.nodes.items() if m.role == n.role and m.name == n.name] if n.name else []
        if len(hits) > 1:
            hits = [i for i in hits if self.nodes[i].where == n.where]
        if len(hits) == 1:
            return hits[0]
        raise Refused(f"[stale] {was} is " + ("gone" if seen is None else f"now named {quote(clip(seen, 60))}")
                      + " since your look; nothing was done. The window is read again below")

    def text_of(self, ident: int) -> str:
        """A field's or document's whole text now, read again (never a secret field's)."""
        n = self.node(ident)
        if n.secret:
            raise Refused(f"[refused] {self.describe(ident)} is a password field: its value is never read")
        A = automation()
        if "text" in n.patterns:
            return str(n.el.GetCurrentPattern(A.TextPattern.Pattern).DocumentRange.GetText(-1))
        if "value" in n.patterns:
            return str(n.el.GetCurrentPropertyValue(A.ValuePattern.ValueProperty) or "")
        return n.name

    def texts(self, top: int) -> str:
        """The names in one window of the last look, for the gate's reading of a dialog."""
        return " ".join([n.name for n in self.nodes.values() if n.top == top] + self.words.get(top, []))

    # --- the picture, for a model that takes pictures when the tree gives almost nothing

    def picture(self, width: int = 1024) -> tuple[str, dict]:
        """The target window as a JPEG (base64) with each id of the last look marked at its centre, and, when
        the look had fewer than FEW controls, a grid of numbered points `g1`... the model can click."""
        from PIL import ImageDraw
        image, (left, top) = win32.capture(self.hwnd)
        draw = ImageDraw.Draw(image)
        marks: dict = {}
        for ident, n in self.nodes.items():
            if n.top != self.hwnd or not n.rect[2]:
                continue
            if n.secret:
                # A password field goes painted over.
                bx, by, bw, bh = n.rect
                draw.rectangle((bx - left, by - top, bx - left + bw, by - top + bh), fill=(128, 128, 128))
            x, y = n.center()
            marks[str(ident)] = (x, y)
            self._mark(draw, x - left, y - top, str(ident), (230, 60, 40))
        if self.interactive < FEW:
            cols, rows = GRID
            wide, high = image.size
            for r in range(rows):
                for c in range(cols):
                    key = f"g{r * cols + c + 1}"
                    x, y = int((c + 0.5) * wide / cols), int((r + 0.5) * high / rows)
                    self.grid[key] = (left + x, top + y)
                    marks[key] = self.grid[key]
                    self._mark(draw, x, y, key, (40, 110, 230))
        scale = min(1.0, width / max(image.size[0], 1))
        if scale < 1:
            image = image.resize((int(image.size[0] * scale), int(image.size[1] * scale)))
        buf = io.BytesIO()
        image.save(buf, "JPEG", quality=70)
        return base64.b64encode(buf.getvalue()).decode("ascii"), marks

    @staticmethod
    def _mark(draw, x: int, y: int, text: str, color) -> None:
        wide = 7 * len(text) + 6
        draw.rectangle((x - wide // 2, y - 8, x + wide // 2, y + 8), fill=color)
        draw.text((x - wide // 2 + 3, y - 7), text, fill=(255, 255, 255))

    # --- acting

    def snapshot(self) -> dict:
        """What the program shows now that an action can change and a person would read off it: its windows,
        the texts of the last look (a display, a status line), and what the fields of the last look hold
        (never a password field's). A few reads, not the whole tree."""
        shown = {}
        for key, (el, _name) in self.shown.items():
            try:
                shown[key] = norm(el.Current.Name)
            except Exception:
                shown[key] = None
        held = {}
        for ident, n in self.nodes.items():
            if not n.secret and (n.role == "combobox" or ({"value", "text"} & set(n.patterns) and n.role in (
                    "textbox", "document", "spinbutton", "slider"))):
                try:
                    held[ident] = self._plain(ident) if n.role != "combobox" else self._value(n, "")
                except Exception:
                    pass
        return {"windows": {h: win32.title_of(h) for h in self.windows()}, "shown": shown, "held": held,
                "tops": set(win32.top_windows())}

    def changes(self, before: dict, after: dict) -> list[str]:
        """What differs between two snapshots, in the look's own words."""
        if not after["windows"]:
            return ["the window closed"]
        said = []
        for h, title in after["windows"].items():
            if h not in before["windows"]:
                said.append(f"a window opened: {quote(clip(title, 60))}")
            elif title != before["windows"][h]:
                said.append(f"the title is now {quote(clip(title, 60))}")
        said += [f"a window closed: {quote(clip(t, 60))}" for h, t in before["windows"].items()
                 if h not in after["windows"]]
        new = [h for h in after["tops"] - before["tops"]
               if win32.shown(h) and win32.pid_of(h) not in self.pids and h not in after["windows"]]
        # The app's own strip and cards are not another program.
        own = win32.own_tree() if new else set()
        others = sorted({os.path.basename(win32.exe_of(win32.pid_of(h))) or "a protected program"
                         for h in new if win32.pid_of(h) not in own})
        said += [f"a window of another program appeared ({name}); it is not granted and was not read"
                 for name in others]
        told = []
        for key, now in after["shown"].items():
            was = before["shown"].get(key)
            if was is not None and now is not None and now != was:
                told.append(f"{quote(clip(was, 60))} now reads {quote(clip(now, 80))}")
        for ident, now in after["held"].items():
            if ident in before["held"] and now != before["held"][ident]:
                told.append(f"{self.describe(ident)} now holds {quote(clip(now, 120))}")
        if len(told) > CHANGES_MAX:
            told = [*told[:CHANGES_MAX], f"and {len(told) - CHANGES_MAX} more changes"]
        return said + told

    def _before(self) -> dict:
        """The snapshot an action starts from: the one the action just before left, when it is that fresh."""
        if self.snap is not None and time.monotonic() - self.snap[0] < 1.5:
            return self.snap[1]
        return self.snapshot()

    def _settled(self, before: dict, front: int, wait: float) -> tuple[dict, list[str]]:
        """Read the program again until something changed, `wait` seconds at most. A packaged app takes the
        front when one of its buttons is invoked: whatever the person had in front goes back there at once."""
        end = time.monotonic() + wait
        while True:
            self._give_back(front)
            after = self.snapshot()
            said = self.changes(before, after)
            if said or time.monotonic() >= end or self.halted():
                self._give_back(front)
                self.snap = (time.monotonic(), after)
                return after, said
            time.sleep(POLL_S)

    def _give_back(self, front: int) -> None:
        if not self.forwarded and front and win32.foreground() != front and \
                win32.top_of(win32.foreground()) in self.windows():
            win32.give_back(front)

    def _act(self, op: str, ident, body: Callable[[], str], wait: float = SETTLE_S) -> str:
        if self.halted():
            raise Refused(f"[{self.halted()}]")
        before = self._before()
        what = self.describe(ident) if ident is not None else ""
        front, self.forwarded = win32.foreground(), False
        # While this app's own window is the one in front, no other program may take the front for itself.
        if self.own is None:
            self.own = win32.own_tree()
        locked = bool(front) and win32.pid_of(front) in self.own and win32.lock_front(True)
        try:
            detail = body()
        except Refused:
            raise
        except Exception as e:
            return well_formed(f"[failed] {op} {what}: {str(e).splitlines()[0][:200]}")
        finally:
            if locked:
                win32.lock_front(False)
            self._give_back(front)
        _after, said = self._settled(before, front, wait)
        if op in ("set", "append", "type", "paste"):
            # The field written was read back in the action itself.
            said = [line for line in said if not line.startswith(f"{what} now holds")]
        return well_formed(f"[ok] {op} {what}{detail}" + (" -> " + "; ".join(said) if said else
                                                           "" if wait == 0 else " -> the window shows no change yet"))

    def forward(self) -> None:
        """The target window in front, for real input; refused when Windows puts anything else there."""
        self.forwarded = True
        win32.lock_front(False)
        self.idle()
        shown = self.windows()
        if win32.top_of(win32.foreground()) not in shown:
            # A modal dialog leaves the main window disabled, and a disabled window takes no focus: the dialog does.
            front = self.hwnd if win32.enabled(self.hwnd) else next((h for h in shown[1:] if win32.enabled(h)), self.hwnd)
            try:
                element(front).SetFocus()
            except Exception:
                # An Electron or other Chromium window takes no focus from UI Automation: brought in front by
                # Windows itself, as pywinauto's set_focus does.
                win32.give_back(front)
            time.sleep(0.15)
        front = win32.top_of(win32.foreground())
        if front not in self.windows():
            raise Refused("[refused] the window could not be brought in front; nothing was typed or clicked")

    def idle(self) -> None:
        """Real keys and clicks wait until the person has left the keyboard and mouse alone: taking the front under
        their hand would send their keys here and these keys there. After IDLE_MAX_S the strip asks them."""
        end = time.monotonic() + IDLE_MAX_S
        while win32.idle_s() < IDLE_S:
            if self.halted():
                raise Refused(f"[{self.halted()}]")
            if time.monotonic() >= end:
                self.busy()
                raise Refused(f"[paused] the person kept using the computer for {IDLE_MAX_S:g}s; nothing was typed or "
                              f"clicked")
            time.sleep(0.1)

    def _focused_ok(self, typing: bool) -> None:
        """Real keys go where the focus is: it must be in this program, and never in a password field."""
        A = automation()
        f = A.AutomationElement.FocusedElement
        if f is None or not (self.ours(f.Current.ProcessId) or f.Current.ProcessId == win32.pid_of(self.hwnd)):
            raise Refused("[refused] the keyboard focus is not in this program; nothing was typed. Name the field the "
                          "keys are for (its name or id with the action), so it is clicked into first")
        if f.Current.IsPassword or (typing and SECRET_LABEL.search(f"{f.Current.Name} {f.Current.AutomationId}")
                                    and f.Current.ControlType.ProgrammaticName.endswith("Edit")):
            raise Refused("[refused] the focus is in a password field: that is for the person to type")

    def invoke(self, ident) -> str:
        """The element's own action: invoke, else toggle, select, expand or collapse; a real click only for
        a control with none of those (and for a grid point of the picture)."""
        if isinstance(ident, str) and ident in self.grid:
            x, y = self.grid[ident]

            def at() -> str:
                self.forward()
                win32.click_at(x, y)
                return f" at {x},{y}"
            return self._act("click", ident, at)
        ident = self.live(ident)
        n = self.node(ident)
        A = automation()

        def press() -> str:
            if not n.enabled:
                raise Refused(f"[failed] {self.describe(ident)} is disabled")
            if "invoke" in n.patterns:
                n.el.GetCurrentPattern(A.InvokePattern.Pattern).Invoke()
                return " (pressed once)"
            if "toggle" in n.patterns:
                was = str(n.el.GetCurrentPropertyValue(A.TogglePattern.ToggleStateProperty))
                n.el.GetCurrentPattern(A.TogglePattern.Pattern).Toggle()
                end = time.monotonic() + SETTLE_S
                while str(n.el.GetCurrentPropertyValue(A.TogglePattern.ToggleStateProperty)) == was and \
                        time.monotonic() < end:
                    time.sleep(POLL_S)
                now = str(n.el.GetCurrentPropertyValue(A.TogglePattern.ToggleStateProperty))
                return f" (toggled), read back and it is {'checked' if now == 'On' else 'unchecked'}"
            if "select" in n.patterns:
                n.el.GetCurrentPattern(A.SelectionItemPattern.Pattern).Select()
                return " (selected)"
            if "expand" in n.patterns:
                return self._expand(n, None)
            return click() + " (no pattern)"

        def click() -> str:
            self.forward()
            x, y = self._point(n)
            win32.click_at(x, y)
            return f" (clicked at {x},{y})"

        def body() -> str:
            # The ladder of UI automation tools: the control's own action; once more with its window in front (a
            # menu, or a control that acts only there); then a real click at its clickable point.
            start = self.snapshot()
            try:
                return press()
            except Refused:
                raise
            except Exception as e:
                why = _why(e)
            if not self.forwarded:
                self.forward()
                try:
                    return press()
                except Refused:
                    raise
                except Exception as e:
                    why = _why(e)
            if self.changes(start, self.snapshot()):
                # The action went through though it answered with an error: a click now would press twice.
                return f" (pressed once; it answered {quote(clip(why, 80))}, and the window changed)"
            return click() + f", once its own action failed ({clip(why, 80)})"
        # A control that unfolds, or whose name ends in an ellipsis, opens a menu or a dialog: that is given
        # longer to show (the wait ends as soon as it does).
        opens = "expand" in n.patterns or n.name.rstrip().endswith(("...", "…"))
        line = self._act("press", ident, body, wait=OPENS_S if opens else PRESS_S)
        if "expand" in n.patterns and line.endswith("no change yet") and str(
                n.el.GetCurrentPropertyValue(A.ExpandCollapsePattern.ExpandCollapseStateProperty)) == "Collapsed":
            # Pressed, and what it should unfold did not show: unfolded by its own pattern.
            return self.expand(ident, True)
        return line

    def set_value(self, ident: int, text: str, append: bool = False) -> str:
        """Replace what a field holds with `text` (or, with `append`, add it after what it holds), up the ladder
        `climb` names: its value pattern or the edit control's own messages, then the focus and keys, then a real
        click and keys, then a click and a paste. The field is read back after each rung, and the line says what
        it holds. Never into a password field."""
        ident = self.live(ident)
        n = self.node(ident)
        if n.secret:
            raise Refused(f"[refused] {self.describe(ident)} is a password field: it is for the person to fill")
        A = automation()
        want = text.replace("\r\n", "\n")
        op = "append to" if append else "set"

        def body() -> str:
            if not append and len(self.text_of(ident)) > DOCUMENT_MAX:
                # The look showed only its beginning: writing that back would cut the rest off.
                raise Refused(f"[failed] {self.describe(ident)} holds more text than the look shows; setting it "
                              f"would lose the rest. Use append, or the program's own find and replace")
            was = self._unfilled(n, self._plain(ident)) if append else ""
            # Added to a document, text starts on a line of its own.
            apart = append and n.role == "document" and was and not was.endswith("\n") and not want.startswith("\n")
            whole = was + ("\n" if apart else "") + want if append else want
            add = whole[len(was):] if append else whole
            start = [win32.VK["Ctrl"], win32.VK["End"]] if append else [win32.VK["Ctrl"], ord("A")]

            def landed(holds: str) -> bool:
                return same_text(holds, whole)

            def by_value() -> None:
                if "value" in n.patterns and not n.readonly:
                    n.el.GetCurrentPattern(A.ValuePattern.Pattern).SetValue(
                        whole.replace("\n", "\r\n") if n.hwnd and win32.multiline(n.hwnd) else whole)
                else:
                    win32.edit_replace(n.hwnd, add, whole=not append, end=append)

            def by_keys(click: bool, paste: bool) -> Callable[[], None]:
                def act() -> None:
                    self._focus_on(n, click)
                    win32.chord(start)
                    if paste:
                        self._paste_keys(add, lambda: landed(self._plain(ident)))
                    else:
                        self._type(add)
                return act
            rungs = [(BY_KEYS, by_keys(False, False)), (BY_CLICK, by_keys(True, False)), (BY_PASTE, by_keys(True, True))]
            # A combo box's edit takes a set value without telling its program (a file dialog then saves under
            # the old name), so that one is typed.
            if not win32.in_combo(n.hwnd) and (("value" in n.patterns and not n.readonly) or (
                    n.hwnd and win32.edit_box(n.hwnd))):
                rungs.insert(0, (BY_VALUE, by_value))
            read = self._reader(n, ident)
            # Appended text typed twice would be there twice; a whole text written again only replaces itself.
            rung, holds, tried = climb(rungs, read, landed, again=not append)
            if not rung:
                raise self._missed(op, ident, holds, tried, len(tried) < len(rungs), read is not None)
            if read is None:
                return f" = {quote(clip(text, 60))}{HOW[rung]}; {UNREAD}"
            return f" = {quote(clip(text, 60))}{HOW[rung]}, read back and it holds exactly that" + (
                " after what it held" if append and was else "") + _before(tried)
        return self._act("append" if append else "set", ident, body, wait=0)

    def _plain(self, ident: int) -> str:
        return self.text_of(ident).replace("\r\n", "\n").replace("\r", "\n")

    def _reader(self, n: Node, ident: int) -> Callable[[], str] | None:
        """How a write reads its field back, or None when the field offers no way to read its text."""
        return (lambda: self._plain(ident)) if {"value", "text"} & set(n.patterns) else None

    @staticmethod
    def _unfilled(n: Node, holds: str) -> str:
        """What an empty field holds, as text written after it: nothing, where the field shows only its own name
        (Chromium reads an empty box as its placeholder, which is also its name)."""
        return "" if n.name and same_text(holds, n.name) else holds

    def _missed(self, op: str, ident: int, holds: str, tried: list[str], partly: bool, readable: bool) -> Refused:
        """Why a write took on no rung, with what to do next: never the same write again."""
        what = self.describe(ident)
        n = self.node(ident)
        if not readable:
            return Refused(f"[failed] {op} {what}: tried {'; then '.join(tried)}; none got to the field. Nothing was "
                           f"written: look again (another control may have to be pressed first), or ask_person and "
                           f"say what the window shows")
        shown = (f"only its own name {quote(clip(holds, 60))}, as an empty field shows its placeholder"
                 if n.name and same_text(holds, n.name) else quote(clip(holds, 200)))
        if partly:
            return Refused(f"[failed] {op} {what}: after {tried[-1]} it holds {shown}, which is not the text given; "
                           f"nothing more was put in, so nothing goes in twice. Set the field to the whole text to "
                           f"correct it")
        return Refused(f"[failed] {op} {what}: tried {'; then '.join(tried)}; after them it holds {shown}. Nothing "
                       f"was written, and set, type or paste again will not take either: look again (another control "
                       f"may have to be pressed first, such as a new chat or an edit button, or the text goes in "
                       f"another field), or ask_person and say what the window shows")

    def type(self, ident: int | None, text: str) -> str:
        """Type `text` at the caret of `ident`, up the ladder `climb` names: an edit control's own messages, then
        the focus and real keys, then a real click and keys, then a click and a paste; a line break goes as
        Shift+Enter. The field is read back after each rung. Without `ident`, real keys where the focus is. Never
        into a password field."""
        if ident is not None:
            ident = self.live(ident)
        n = self.node(ident) if ident is not None else None
        if n is not None and n.secret:
            raise Refused(f"[refused] {self.describe(ident)} is a password field: it is for the person to fill")
        if n is None:
            def at_focus() -> str:
                self.forward()
                self._focused_ok(True)
                self._type(text)
                return f" {quote(clip(text, 60))}"
            return self._act("type", None, at_focus)

        def by_keys(click: bool, paste: bool, landed: Callable[[str], bool]) -> Callable[[], None]:
            def act() -> None:
                self._focus_on(n, click)
                if paste:
                    self._paste_keys(text, lambda: landed(self._plain(ident)))
                else:
                    self._type(text)
            return act

        def body() -> str:
            read = self._reader(n, ident)
            landed = self._inserted(text, read() if read else "")
            rungs = [(BY_KEYS, by_keys(False, False, landed)), (BY_CLICK, by_keys(True, False, landed)),
                     (BY_PASTE, by_keys(True, True, landed))]
            if n.hwnd and win32.edit_box(n.hwnd) and not win32.in_combo(n.hwnd):
                rungs.insert(0, (BY_MESSAGES, lambda: win32.edit_replace(n.hwnd, text, whole=False)))
            rung, holds, tried = climb(rungs, read, landed, again=False)
            if not rung:
                raise self._missed("type into", ident, holds, tried, len(tried) < len(rungs), read is not None)
            if read is None:
                return f" {quote(clip(text, 60))}{HOW[rung]}; {UNREAD}"
            return f" {quote(clip(text, 60))}{HOW[rung]}, read back and it is there" + _before(tried)
        return self._act("type", ident, body, wait=0)

    @staticmethod
    def _inserted(text: str, was: str) -> Callable[[str], bool]:
        """Whether a field holds `text` once more than it did before (`was`): text put in at the caret."""
        want = plain_text(text)
        return lambda holds: plain_text(holds).count(want) > plain_text(was).count(want)

    def paste(self, ident: int | None, text: str) -> str:
        """Put `text` in at the caret of `ident` as Ctrl+V does, focused by UI Automation, else by a real click: the
        person's clipboard is kept, the text set there, Ctrl+V sent once the focus is checked, and their clipboard
        put back once the field shows the text. Without `ident`, where the focus is. Never into a password field."""
        if ident is not None:
            ident = self.live(ident)
        n = self.node(ident) if ident is not None else None
        if n is not None and n.secret:
            raise Refused(f"[refused] {self.describe(ident)} is a password field: it is for the person to fill")
        A = automation()
        want = plain_text(text)

        def at_focus() -> str:
            self.forward()
            self._focused_ok(True)
            field = A.AutomationElement.FocusedElement
            got: list[str | None] = [None]

            def landed() -> bool:
                got[0] = _held_by(field)
                return got[0] is not None and want in plain_text(got[0])
            self._paste_keys(text, landed)
            if got[0] is None:
                return f" {quote(clip(text, 60))} (through the clipboard, theirs put back)"
            if want not in plain_text(got[0]):
                raise Refused(f"[failed] paste into the focused field: after pasting, it holds "
                              f"{quote(clip(got[0], 200))}, which does not have the text given")
            return f" {quote(clip(text, 60))} (through the clipboard, theirs put back), read back and it is there"
        if n is None:
            return self._act("paste", None, at_focus)

        def by_paste(click: bool, landed: Callable[[str], bool]) -> Callable[[], None]:
            def act() -> None:
                self._focus_on(n, click)
                self._paste_keys(text, lambda: landed(self._plain(ident)))
            return act

        def body() -> str:
            read = self._reader(n, ident)
            landed = self._inserted(text, read() if read else "")
            rungs = [(BY_FOCUS_PASTE, by_paste(False, landed)), (BY_PASTE, by_paste(True, landed))]
            rung, holds, tried = climb(rungs, read, landed, again=False)
            if not rung:
                raise self._missed("paste into", ident, holds, tried, len(tried) < len(rungs), read is not None)
            if read is None:
                return f" {quote(clip(text, 60))}{HOW[rung]}; {UNREAD}"
            return f" {quote(clip(text, 60))}{HOW[rung]}, read back and it is there" + _before(tried)
        return self._act("paste", ident, body, wait=0)

    def _paste_keys(self, text: str, landed: Callable[[], bool]) -> None:
        """Ctrl+V with `text` on the clipboard, the person's own put back once `landed()` (the program reads the
        clipboard when it handles the keys), 2 * SETTLE_S at most."""
        theirs = win32.clipboard_save()
        try:
            win32.clipboard_put(win32.clipboard_text(text))
            win32.chord([win32.VK["Ctrl"], ord("V")])
            end = time.monotonic() + 2 * SETTLE_S
            while not landed() and time.monotonic() < end:
                time.sleep(POLL_S)
        finally:
            win32.clipboard_put(theirs)

    def _focus_on(self, n: Node, click: bool) -> None:
        """The keyboard focus put in `n` with its window in front: by UI Automation, or with `click` by a real
        click at its clickable point (a Chromium page's editable box takes no focus from UI Automation). Missed,
        with why, unless the focus is then in `n`; refused where a password field has it."""
        A = automation()
        if click and n.role not in FIELDS:
            # Clicked, any other control would be pressed, past the gate.
            raise Missed(f"it is a {n.role}, not a text field, so it is not clicked into")
        self.forward()
        if click:
            x, y = self._point(n)
            win32.click_at(x, y)
        else:
            try:
                n.el.SetFocus()
            except Exception as e:
                raise Missed(f"it takes no focus from UI Automation: {_why(e)}") from None
        end = time.monotonic() + SETTLE_S
        while not self._has_focus(n):
            if time.monotonic() >= end:
                f = A.AutomationElement.FocusedElement
                where = "nothing" if f is None else (
                    f"{ROLES.get(f.Current.ControlType.ProgrammaticName.split('.')[-1], 'custom')} "
                    f"{quote(clip(norm(f.Current.Name), 40))}")
                raise Missed(f"the focus went to {where}, not to it")
            time.sleep(POLL_S)
        self._focused_ok(True)

    def _has_focus(self, n: Node) -> bool:
        """Whether the keyboard focus is on `n` or inside it, or on the edit box `n` sits in (a Chromium editable
        host round the element the look printed)."""
        A = automation()
        f = A.AutomationElement.FocusedElement
        if f is None:
            return False
        walker = A.TreeWalker.RawViewWalker
        el = f
        for _up in range(8):
            if el is None:
                break
            if A.Automation.Compare(el, n.el):
                return True
            el = walker.GetParent(el)
        if not f.Current.ControlType.ProgrammaticName.endswith("Edit"):
            return False
        el = walker.GetParent(n.el)
        for _up in range(4):
            if el is None:
                return False
            if A.Automation.Compare(el, f):
                return True
            el = walker.GetParent(el)
        return False

    def _focus(self, n: Node) -> str:
        """The focus put in `n` for a key: by UI Automation, else by a real click on it. Returns how it went in."""
        missed = []
        for click in (False, True):
            try:
                self._focus_on(n, click)
                return " (after a click on it)" if click else ""
            except Missed as e:
                missed.append(str(e))
        raise Refused(f"[failed] the focus would not go into {n.role} {quote(clip(n.name, 60))}: "
                      f"{'; then, after a click on it, '.join(missed)}. Nothing was pressed or typed: look again (it "
                      f"may be covered, or open only after another control is pressed), or ask_person")

    def _type(self, text: str) -> None:
        """Real keystrokes in short runs; between runs, a stop or a focus that moved ends the typing."""
        A = automation()
        start = list(A.AutomationElement.FocusedElement.GetRuntimeId())
        for i in range(0, len(text), 40):
            why = self.halted()
            if why:
                raise Refused(f"[{why}] stopped while typing, after {i} characters")
            self._focused_ok(True)
            if list(A.AutomationElement.FocusedElement.GetRuntimeId()) != start:
                raise Refused(f"[failed] the focus moved while typing, after {i} characters; look again")
            win32.type_text(text[i:i + 40])

    def toggle(self, ident: int, on: bool | None = None) -> str:
        """Flip a tick box, or with `on` bring it to that state (nothing is pressed when it is there already);
        the state is read back."""
        ident = self.live(ident)
        n = self.node(ident)
        A = automation()

        def state() -> str:
            return str(n.el.GetCurrentPropertyValue(A.TogglePattern.ToggleStateProperty))

        def body() -> str:
            if "toggle" not in n.patterns:
                raise Refused(f"[failed] {self.describe(ident)} is not a tick box or a switch")
            want = None if on is None else "On" if on else "Off"
            if state() == want:
                return f" (it was already {'checked' if on else 'unchecked'}; nothing pressed)"
            was = state()
            n.el.GetCurrentPattern(A.TogglePattern.Pattern).Toggle()
            end = time.monotonic() + SETTLE_S
            while state() == was and time.monotonic() < end:
                time.sleep(POLL_S)
            if want is not None and state() != want:
                raise Refused(f"[failed] {self.describe(ident)} did not become {'checked' if on else 'unchecked'}")
            return f", read back and it is {'checked' if state() == 'On' else 'unchecked'}"
        return self._act("toggle", ident, body, wait=0)

    def select(self, ident: int, option: str = "") -> str:
        """Select an item; for a list or a combo box, the item named `option` under it (also one scrolled out
        of view). The selection is read back."""
        ident = self.live(ident)
        n = self.node(ident)
        A = automation()

        def picked(el) -> bool:
            end = time.monotonic() + SETTLE_S
            while time.monotonic() < end:
                if el.GetCurrentPropertyValue(A.SelectionItemPattern.IsSelectedProperty):
                    return True
                time.sleep(POLL_S)
            return False

        def body() -> str:
            if not option:
                if "select" not in n.patterns:
                    raise Refused(f"[failed] {self.describe(ident)} is not an item that can be selected; for a list "
                                  f"or a combobox give the item's name as \"option\"")
                n.el.GetCurrentPattern(A.SelectionItemPattern.Pattern).Select()
                if not picked(n.el):
                    raise Refused(f"[failed] {self.describe(ident)} does not show as selected")
                return ", read back and it is selected"
            if "expand" in n.patterns:
                n.el.GetCurrentPattern(A.ExpandCollapsePattern.Pattern).Expand()
                time.sleep(0.2)
            items = n.el.FindAll(A.TreeScope.Descendants, A.PropertyCondition(
                A.AutomationElement.IsSelectionItemPatternAvailableProperty, True))
            want = norm(option).lower()
            hits = [it for it in items if norm(it.Current.Name).lower() == want] or [
                it for it in items if norm(it.Current.Name).lower().startswith(want)]
            if len(hits) != 1:
                names = " | ".join(norm(it.Current.Name) for it in list(items)[:30])
                raise Refused(f"[failed] {'several' if hits else 'no'} options match {option!r}. Options: {names}")
            hits[0].GetCurrentPattern(A.SelectionItemPattern.Pattern).Select()
            chosen = picked(hits[0])
            if "expand" in n.patterns:
                try:
                    n.el.GetCurrentPattern(A.ExpandCollapsePattern.Pattern).Collapse()
                except Exception:
                    pass
            if not chosen:
                raise Refused(f"[failed] {quote(norm(hits[0].Current.Name))} does not show as selected in "
                              f"{self.describe(ident)}")
            return f" = {quote(norm(hits[0].Current.Name))}, read back and it is selected"
        return self._act("select", ident, body, wait=0)

    def expand(self, ident: int, open_: bool | None = None) -> str:
        ident = self.live(ident)
        n = self.node(ident)
        return self._act("expand" if open_ is not False else "collapse", ident, lambda: self._expand(n, open_))

    def _expand(self, n: Node, open_: bool | None) -> str:
        A = automation()
        p = n.el.GetCurrentPattern(A.ExpandCollapsePattern.Pattern)
        state = str(p.Current.ExpandCollapseState)
        if open_ is None:
            open_ = state != "Expanded"
        (p.Expand if open_ else p.Collapse)()
        return " (opened)" if open_ else " (closed)"

    def scroll(self, ident: int | None = None, down: bool = True) -> str:
        """Scroll an element that scrolls, the nearest one above `ident`, or the window's biggest; the wheel
        over it when none offers the scroll pattern."""
        A = automation()

        def body() -> str:
            target = None
            if ident is not None:
                n = self.node(ident)
                while n is not None and "scroll" not in n.patterns:
                    n = n.parent
                target = n
            if target is None:
                scrolling = [n for n in self.nodes.values() if "scroll" in n.patterns and n.top == self.hwnd]
                target = max(scrolling, key=lambda n: n.rect[2] * n.rect[3], default=None)
            if target is not None:
                p = target.el.GetCurrentPattern(A.ScrollPattern.Pattern)
                if p.Current.VerticallyScrollable:
                    p.ScrollVertical(A.ScrollAmount.LargeIncrement if down else A.ScrollAmount.LargeDecrement)
                    return (" down" if down else " up") + f" ({p.Current.VerticalScrollPercent:.0f}%)"
            self.forward()
            if ident is not None:
                x, y = self.node(ident).center()
            else:
                left, top, right, bottom = win32.rect(self.hwnd)
                x, y = (left + right) // 2, (top + bottom) // 2
            win32.wheel_at(x, y, -5 if down else 5)
            return (" down" if down else " up") + " (wheel)"
        return self._act("scroll", ident, body, wait=0)

    def focus(self, ident: int) -> str:
        n = self.node(ident)
        return self._act("focus", ident, lambda: n.el.SetFocus() or "")

    def menu(self, ident: int) -> str:
        """Open the element's right-click menu as the keyboard does: selected and focused, then Shift+F10, or the
        Apps key when that opens nothing. The menu is read with the window from then on (`menus`)."""
        ident = self.live(ident)
        n = self.node(ident)
        A = automation()

        def body() -> str:
            self.forward()
            if "select" in n.patterns and not n.el.GetCurrentPropertyValue(A.SelectionItemPattern.IsSelectedProperty):
                n.el.GetCurrentPattern(A.SelectionItemPattern.Pattern).Select()
            n.el.SetFocus()
            self._focused_ok(False)
            for keys in ([win32.VK["Shift"], win32.VK["F10"]], [win32.VK["Apps"]]):
                before = set(win32.top_windows())
                win32.chord(keys)
                popup = self._popup(before)
                if popup:
                    self.menus[popup] = n
                    return " (its menu opened)"
            raise Refused(f"[failed] {self.describe(ident)} opened no menu; nothing else was done")
        return self._act("menu", ident, body, wait=OPENS_S)

    def _popup(self, before: set[int]) -> int:
        """A menu or pop-up of the program that came up after `before`, waited for OPENS_S at most, or 0."""
        end = time.monotonic() + OPENS_S
        while time.monotonic() < end:
            for h in win32.top_windows():
                if h not in before and win32.pid_of(h) in self.pids and win32.shown(h) and (
                        win32.class_of(h) == "#32768" or win32.popup(h)):
                    return h
            time.sleep(POLL_S)
        return 0

    def double(self, ident: int) -> str:
        """A real double click at the element's clickable point, once it is in front and nothing covers it there."""
        ident = self.live(ident)
        n = self.node(ident)

        def body() -> str:
            self.forward()
            x, y = self._point(n)
            win32.click_at(x, y, double=True)
            return f" (double-clicked at {x},{y})"
        return self._act("double", ident, body, wait=OPENS_S)

    def _point(self, n: Node) -> tuple[int, int]:
        """Where a click lands on `n`: the centre of the part of it its window shows (a list row runs on under
        the columns out of view). Refused when UI Automation finds there neither `n` nor an element inside it, or
        the window there is not the program's (something covers it, or it scrolled away)."""
        A = automation()
        from ..see.act import _point_type
        Point = _point_type()
        r = n.el.Current.BoundingRectangle
        x, y, wide, high = int(r.X), int(r.Y), int(r.Width), int(r.Height)
        left, top, right, bottom = win32.rect(n.top)
        x, y = (max(x, left) + min(x + wide, right)) // 2, (max(y, top) + min(y + high, bottom)) // 2
        hit = A.AutomationElement.FromPoint(Point(x, y))
        for _up in range(8):
            if hit is None or A.Automation.Compare(hit, n.el):
                break
            hit = A.TreeWalker.ControlViewWalker.GetParent(hit)
        # Inside a window that does not know the monitor's scale (not DPI aware, on a monitor at 150%), UI Automation
        # gives an element's offset from its native window unscaled, while the window is drawn scaled.
        el = n.el
        while el is not None and not el.Current.NativeWindowHandle:
            el = A.TreeWalker.RawViewWalker.GetParent(el)
        if el is not None and not A.Automation.Compare(el, n.el):
            h = el.Current.NativeWindowHandle
            scale = win32.unscaled(h)
            if scale != 1:
                left, top = win32.client_origin(h)
                x, y = int(left + (x - left) * scale), int(top + (y - top) * scale)
        if hit is None or win32.pid_of(win32.window_at(x, y)) not in self.pids:
            raise Refused(f"[refused] something else shows at the point of {n.role} {quote(clip(n.name, 60))}; "
                          f"nothing was clicked")
        return x, y

    def key(self, keys: str, ident: int | None = None) -> str:
        """One keystroke with its modifiers, e.g. "Enter", "Ctrl+A", "Shift+Tab", "F2", "Ctrl+Shift+S": where the
        focus is, or with `ident` in that control, the focus put there first (by a real click on it when it takes
        none from UI Automation)."""
        vks = parse_key(keys)
        n = self.node(ident) if ident is not None else None

        def body() -> str:
            self.forward()
            how = self._focus(n) if n is not None else ""
            self._focused_ok(False)
            win32.chord(vks)
            return f" {keys}{how}"
        return self._act("key", ident, body)

    def wait(self, seconds: float, until: str = "") -> str:
        """Wait for the program: until it shows the words `until`, or until anything in it changes, `seconds`
        at most."""
        seconds = min(max(float(seconds), 0.2), 8.0)
        if not until:
            return self._act("wait", None, lambda: f" up to {seconds:g}s", wait=seconds)
        want = norm(until).lower()

        def body() -> str:
            end = time.monotonic() + seconds
            while not self.halted():
                if want in self.look().lower():
                    return f" until it shows {quote(clip(until, 40))}: it does"
                if time.monotonic() >= end:
                    break
                time.sleep(0.3)
            raise Refused(f"[failed] waited {seconds:g}s and the window does not show {quote(clip(until, 40))}")
        return self._act("wait", None, body, wait=0)

    def focused(self) -> Node | None:
        """The element with the keyboard focus as a Node of the last look, else a fresh one read now."""
        A = automation()
        f = A.AutomationElement.FocusedElement
        if f is None or not self.ours(f.Current.ProcessId):
            return None
        key = "/".join(str(x) for x in f.GetRuntimeId())
        ident = self.handles.get(key)
        if ident in self.nodes:
            return self.nodes[ident]
        kind = f.Current.ControlType.ProgrammaticName.split(".")[-1]
        r = f.Current.BoundingRectangle
        return Node(el=f, role=ROLES.get(kind, "custom"), name=norm(f.Current.Name), auto=f.Current.AutomationId,
                    cls=f.Current.ClassName, pid=f.Current.ProcessId, enabled=f.Current.IsEnabled, focused=True,
                    secret=f.Current.IsPassword, rect=(int(r.X), int(r.Y), int(r.Width), int(r.Height)),
                    hwnd=f.Current.NativeWindowHandle, patterns=[], readonly=False,
                    top=win32.top_of(f.Current.NativeWindowHandle or self.hwnd), parent=None, cells=[])


def _holds(el, roles: set, most: int = 400) -> bool:
    """Whether anything under `el` has one of `roles`, from the look's cache: a page's document holds controls (its
    buttons, fields, list rows), a text document none. A scroll bar and its arrow buttons are the frame, not what
    the element holds: an edit control's document has them too."""
    A = automation()
    todo, seen = list(el.CachedChildren), 0
    while todo and seen < most:
        child = todo.pop()
        seen += 1
        ctype = _get(child, A.AutomationElement.ControlTypeProperty)
        role = ROLES.get(ctype.ProgrammaticName.split(".")[-1]) if ctype is not None else None
        if role in roles:
            return True
        if role not in SKIPPED:
            todo.extend(child.CachedChildren)
    return False


def _rid(el) -> str:
    """An element's RuntimeId from the cache, as one string."""
    return "/".join(str(x) for x in el.GetCachedPropertyValue(automation().AutomationElement.RuntimeIdProperty))


def parse_key(keys: str) -> list[int]:
    """Virtual keys of "Ctrl+Shift+S"; the Windows key, Alt+Tab, Ctrl+Esc and Ctrl+Alt+Delete are never sent:
    they reach other programs and the system, not this one."""
    parts = [p.strip() for p in str(keys).split("+") if p.strip()]
    if not parts:
        raise Refused("[failed] no key given")
    *mods, last = parts
    mods = [m.capitalize() if m.lower() != "ctrl" else "Ctrl" for m in mods]
    if any(m not in ("Ctrl", "Shift", "Alt") for m in mods):
        raise Refused(f"[refused] {keys!r}: only Ctrl, Shift and Alt go with a key (never the Windows key)")
    if len(last) == 1 and last.isalnum():
        vk = ord(last.upper())
    elif last in KEY_NAMES:
        vk = win32.VK[last]
    else:
        raise Refused(f"[failed] no key {last!r}; keys: {', '.join(sorted(KEY_NAMES))}, letters and digits")
    if ("Alt" in mods and last in ("Tab", "Escape", "F4")) or ("Ctrl" in mods and last == "Escape") or (
            {"Ctrl", "Alt"} <= set(mods) and last == "Delete"):
        raise Refused(f"[refused] {keys!r} switches or closes programs; it is never sent")
    return [win32.VK[m] for m in mods] + [vk]
