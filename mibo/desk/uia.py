"""The building blocks of seeing and working another program's window through Windows UI Automation
(System.Windows.Automation through pythonnet, which pywebview already loads on Windows): the library, an element's
cached properties, the roles a look prints, the ladder a write climbs, and the keys that may be sent.

The window itself is a `view.View`: `looking.Looking` reads it, `writing.Writing` writes into its fields, and
`view.View` presses, picks and types keys. Those reach `automation`, `element` and the timings here through this
module, so tests can put stand-ins in their place.
"""
from __future__ import annotations

import re
import time
from collections.abc import Callable

from ..web.pagewords import clip
from ..web.pagewords import norm as _norm
from . import win32

ASSEMBLY = ", Version=4.0.0.0, Culture=neutral, PublicKeyToken=31bf3856ad364e35"
# At most this many elements are read of one look; a value is cut at these lengths.
NODES_MAX = 2500
VALUE_MAX = 100
DOCUMENT_MAX = 4000
# An action's result is waited for on the program's state: read again until something changed, this long at most.
SETTLE_S = 0.45
POLL_S = 0.03

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
# Not printed, with what is under them: the window's own frame buttons and the scroll bars (scroll is an action).
SKIPPED = {"titlebar", "scrollbar", "thumb", "tooltip", "separator"}
CONTROLS = {"button", "textbox", "document", "link", "checkbox", "radio", "combobox", "listitem", "menuitem",
            "tab", "treeitem", "slider", "spinbutton", "row", "columnheader"}
KEY_NAMES = set(win32.VK) - {"Ctrl", "Shift", "Alt", "Apps"}
BIDI = re.compile(r"[‎‏‪-‮⁦-⁩]")


class Refused(Exception):
    """An action this layer will not do; its text goes back to the loop as is."""


class Missed(Exception):
    """One rung of a write or a focus that did not get to the field; the next rung is tried."""


def reason(e: Exception) -> str:
    """An exception's first line, as a step's line quotes it."""
    return (str(e).splitlines() or [type(e).__name__])[0][:120]


# --- the library and the elements

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


def cache_request():
    """What one look reads of every element of a window, in one round trip."""
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


def role_of(control_type) -> str:
    """The role a look prints for a ControlType."""
    return ROLES.get(control_type.ProgrammaticName.split(".")[-1], "custom")


def cached(el, prop):
    """A cached property, None where the element does not support it."""
    v = el.GetCachedPropertyValue(prop, True)
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    return None if automation().AutomationElement.NotSupported.Equals(v) else v


def holds_role(el, roles: set, most: int = 400) -> bool:
    """Whether anything under `el` has one of `roles`, from the look's cache: a page's document holds controls (its
    buttons, fields, list rows), a text document none. A scroll bar and its arrow buttons are the frame, not what
    the element holds: an edit control's document has them too."""
    A = automation()
    todo, seen = list(el.CachedChildren), 0
    while todo and seen < most:
        child = todo.pop()
        seen += 1
        ctype = cached(child, A.AutomationElement.ControlTypeProperty)
        role = ROLES.get(ctype.ProgrammaticName.split(".")[-1]) if ctype is not None else None
        if role in roles:
            return True
        if role not in SKIPPED:
            todo.extend(child.CachedChildren)
    return False


def runtime_id(el) -> str:
    """An element's RuntimeId from the cache, as one string."""
    return "/".join(str(x) for x in el.GetCachedPropertyValue(automation().AutomationElement.RuntimeIdProperty))


# --- the ladder a write climbs

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


def tried_before(tried: list[str]) -> str:
    """What a write's line adds about the rungs that did not take before the one that did."""
    return f"; before that, {clip(' and '.join(tried), 200)} did not take" if tried else ""


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
            tried.append(f"{name} ({clip(reason(e), 90)})")
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


# --- keys

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
