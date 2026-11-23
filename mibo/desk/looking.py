"""How the character reads one granted program's window: printed in the lines pageprint prints for a page,

    [id] role "name" = value states

`## ` lines are named groups and panes, other lines are text shown in the window, `*` marks ids new since the
last look, `[secret]` a password field, whose value is never asked of the program. Only the target window, the
windows it owns (its dialogs, the common file dialog) and, for a program with a process of its own, its menus
and pop-ups are read: which window is the program's is decided by its process, never by a title. Elements of
another process inside the window are skipped with what is under them.

The line grammar, the drop rule for nameless groups and the RuntimeId handles follow dsh's cua-windows
AccessibilityText.cs and Accessibility.cs (MIT, see NOTICE); the rest is ours.
"""
from __future__ import annotations

import os
import time
from collections.abc import Callable

from ..web.pageprint import STATE_MAX
from ..web.pagewords import SECRET_LABEL, clip, quote, well_formed
from . import shape, uia, win32

# Fewer controls than this and the picture carries a grid of numbered points to click.
FEW = 3
GRID = (8, 6)
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
# A control smaller than this share of the target window is a small named one; a nameless area this big is drawn.
SMALL_SHARE = 0.15
# Containers whose name is printed as a `## ` line when nothing can be done with them.
HEADED = {"window", "pane", "group", "toolbar", "menubar", "status", "tablist", "table", "grid", "custom"}
# Top-level windows that are never part of a program even when its process owns them.
NOT_WINDOWS = {"tooltips_class32", "IME", "MSCTFIME UI", "SysShadow", "Shell_TrayWnd", "Shell_SecondaryTrayWnd",
               "Progman", "WorkerW"}
PATTERNS = (("invoke", "IsInvokePatternAvailableProperty"), ("value", "IsValuePatternAvailableProperty"),
            ("toggle", "IsTogglePatternAvailableProperty"), ("select", "IsSelectionItemPatternAvailableProperty"),
            ("expand", "IsExpandCollapsePatternAvailableProperty"), ("scroll", "IsScrollPatternAvailableProperty"),
            ("range", "IsRangeValuePatternAvailableProperty"), ("text", "IsTextPatternAvailableProperty"))


class Looking:
    """One granted program's target window as the last look read it: `look()` prints it, and the ids of that print
    are what the actions act on. `pid` is the program's process: its windows are its own; inside the target, what
    the processes it started draw counts too (a WebView2 page in the program). `shared` is true for a process that
    also draws other things (File Explorer is the taskbar and the desktop too), where only the target and the
    windows it owns are read. `halted()` says why to stop between the steps of one action ("" to go on);
    `never(hwnd)` why a window of the program is still not read."""

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
        self.nodes: dict[int, uia.Node] = {}
        self.handles: dict[str, int] = {}
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
        # The windows the last look read.
        self.seen: tuple = ()
        self.named = 0
        self.drawn = 0.0
        self.snap: tuple[float, dict] | None = None
        self.own: set[int] | None = None
        # The menus `menu` opened, each with the control it was opened on, read with the window while they show.
        self.menus: dict[int, uia.Node] = {}
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
        A = uia.automation()
        pages = [h for top in wins for h in win32.chromium_pages(top) if h not in self.woken]
        walker = A.TreeWalker.ControlViewWalker

        def ready(h: int) -> bool:
            try:
                doc = walker.GetFirstChild(uia.element(h))
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
        cache = uia.cache_request()
        previous = set(self.nodes)
        self.nodes, self.grid, self.interactive, self.words, self.shown = {}, {}, 0, {}, {}
        self.spans, self.cut = {}, []
        self.serial += 1
        wins = self.windows()
        if not wins:
            raise uia.Refused("[gone] the window is closed")
        self.seen = tuple(wins)
        self.wake(wins)
        one = Pass(self, previous)
        for i, h in enumerate(wins):
            if self.halted():
                break
            root = _cached_root(h, cache)
            if root is None:
                continue
            title = win32.title_of(h)
            if i:
                kind = "menu" if win32.class_of(h) == "#32768" else "dialog"
                one.lines.append(f"--- window {quote(clip(title, 80))} ({kind}) ---")
            for child in root.CachedChildren:
                one.read(child, h, title.lower(), None)
        self.named = len(one.small)
        self.unnamed = self._describe(one.lines, one.nameless, one.texts, one.frame)
        self.drawn = one.drawn()
        asked = ", even after its page was asked for it" if self.asleep else ""
        body = one.lines or [f"(nothing in the accessibility tree{asked}: the window draws itself)"]
        if one.count >= uia.NODES_MAX:
            body.append(f"... stopped reading at {uia.NODES_MAX} elements")
        # Uncut, for a look at a part of it (pageprint.view_of).
        self.lines = list(body)
        if _fit(body, max) < len(body):
            head = _fit(body, max * 0.8)
            tail = _fit(body[::-1], max * 0.2)
            self.cut = [(head, len(body) - tail)]
            body = [*body[:head], f"... {len(body) - head - tail} lines cut here", *body[len(body) - tail:]]
        header = f"[state] {clip(win32.title_of(self.hwnd), 120)}"
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
                lines[at] = f"(picture, no name: {said}) @{_place(box, frame)}"
        return out

    def _handle(self, el) -> int:
        """A small number for an element, the same across looks while the element lives (its RuntimeId)."""
        key = uia.runtime_id(el)
        if key not in self.handles:
            self.handles[key] = len(self.handles) + 1
        return self.handles[key]

    def _value(self, node: uia.Node) -> str:
        A = uia.automation()
        el = node.el
        try:
            if "text" in node.patterns and node.role == "document":
                return clip(str(el.GetCurrentPattern(A.TextPattern.Pattern).DocumentRange.GetText(uia.DOCUMENT_MAX)),
                            uia.DOCUMENT_MAX)
            if "value" in node.patterns:
                v = str(el.GetCurrentPropertyValue(A.ValuePattern.ValueProperty) or "")
                if v or node.role != "combobox":
                    return clip(v, uia.DOCUMENT_MAX if node.hwnd and win32.multiline(node.hwnd) else uia.VALUE_MAX)
            if "range" in node.patterns:
                return f"{float(uia.cached(el, A.RangeValuePattern.ValueProperty) or 0):g}"
            if node.role == "combobox":
                # A drop-down list holds no text of its own: what it shows is its selected item.
                picked = el.GetCurrentPattern(A.SelectionPattern.Pattern).Current.GetSelection()
                return clip(", ".join(uia.norm(it.Current.Name) for it in picked), uia.VALUE_MAX)
        except Exception:
            return ""
        return ""

    def describe(self, ident) -> str:
        n = self.nodes.get(ident) if isinstance(ident, int) else None
        if n is None:
            return f"[{ident}]"
        return f"[{ident}] {n.role}" + (f' "{clip(n.name, 60)}"' if n.name else "")

    def node(self, ident) -> uia.Node:
        n = self.nodes.get(ident)
        if n is None:
            raise uia.Refused(f"[failed] [{ident}] is not in the latest look; look again")
        return n

    def live(self, ident) -> int:
        """The id to act on, once the element is read again: it must still be the kind and name the look
        printed. One that died or changed (a list drawn again, a button renamed) is looked for again by its
        kind, name and group; when exactly one control answers to them, that one is meant. Otherwise nothing
        is done."""
        n = self.node(ident)
        try:
            now = n.el.Current
            same = uia.norm(now.Name) == n.name and uia.role_of(now.ControlType) == n.role
            seen = uia.norm(now.Name)
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
        raise uia.Refused(f"[stale] {was} is " + ("gone" if seen is None else f"now named {quote(clip(seen, 60))}")
                          + " since your look; nothing was done. The window is read again below")

    def text_of(self, ident: int) -> str:
        """A field's or document's whole text now, read again (never a secret field's)."""
        n = self.node(ident)
        if n.secret:
            raise uia.Refused(f"[refused] {self.describe(ident)} is a password field: its value is never read")
        A = uia.automation()
        if "text" in n.patterns:
            return str(n.el.GetCurrentPattern(A.TextPattern.Pattern).DocumentRange.GetText(-1))
        if "value" in n.patterns:
            return str(n.el.GetCurrentPropertyValue(A.ValuePattern.ValueProperty) or "")
        return n.name

    def _plain(self, ident: int) -> str:
        """`text_of` with Windows' line breaks as plain ones."""
        return self.text_of(ident).replace("\r\n", "\n").replace("\r", "\n")

    def texts(self, top: int) -> str:
        """The names in one window of the last look, for the gate's reading of a dialog."""
        return " ".join([n.name for n in self.nodes.values() if n.top == top] + self.words.get(top, []))

    def focused(self) -> uia.Node | None:
        """The element with the keyboard focus as a Node of the last look, else a fresh one read now."""
        A = uia.automation()
        f = A.AutomationElement.FocusedElement
        if f is None or not self.ours(f.Current.ProcessId):
            return None
        key = "/".join(str(x) for x in f.GetRuntimeId())
        ident = self.handles.get(key)
        if ident in self.nodes:
            return self.nodes[ident]
        r = f.Current.BoundingRectangle
        return uia.Node(el=f, role=uia.role_of(f.Current.ControlType), name=uia.norm(f.Current.Name),
                        auto=f.Current.AutomationId, cls=f.Current.ClassName, pid=f.Current.ProcessId,
                        enabled=f.Current.IsEnabled, focused=True, secret=f.Current.IsPassword,
                        rect=(int(r.X), int(r.Y), int(r.Width), int(r.Height)), hwnd=f.Current.NativeWindowHandle,
                        patterns=[], readonly=False, top=win32.top_of(f.Current.NativeWindowHandle or self.hwnd),
                        parent=None, cells=[])

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
            _mark(draw, x - left, y - top, str(ident), (230, 60, 40))
        if self.interactive < FEW:
            cols, rows = GRID
            wide, high = image.size
            for r in range(rows):
                for c in range(cols):
                    key = f"g{r * cols + c + 1}"
                    x, y = int((c + 0.5) * wide / cols), int((r + 0.5) * high / rows)
                    self.grid[key] = (left + x, top + y)
                    marks[key] = self.grid[key]
                    _mark(draw, x, y, key, (40, 110, 230))
        scale = min(1.0, width / max(image.size[0], 1))
        if scale < 1:
            image = image.resize((int(image.size[0] * scale), int(image.size[1] * scale)))
        return win32.jpeg64(image, 70), marks

    # --- what an action changed

    def snapshot(self) -> dict:
        """What the program shows now that an action can change and a person would read off it: its windows,
        the texts of the last look (a display, a status line), and what the fields of the last look hold
        (never a password field's). A few reads, not the whole tree."""
        shown = {}
        for key, (el, _name) in self.shown.items():
            try:
                shown[key] = uia.norm(el.Current.Name)
            except Exception:
                shown[key] = None
        held = {}
        for ident, n in self.nodes.items():
            if not n.secret and (n.role == "combobox" or ({"value", "text"} & set(n.patterns) and n.role in (
                    "textbox", "document", "spinbutton", "slider"))):
                try:
                    held[ident] = self._plain(ident) if n.role != "combobox" else self._value(n)
                except Exception:
                    continue
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


class Pass:
    """One look's pass over the program's windows: the lines it prints, and what it finds of the target window
    (its small named controls, its big nameless areas, its texts with their boxes, its nameless controls and
    pictures as (line, head, box, kind), and the boxes of the web pages read by their controls)."""

    def __init__(self, view: Looking, previous: set[int]):
        self.view, self.previous = view, previous
        self.A = uia.automation()
        self.lines: list[str] = []
        self.count = 0
        # How much of the target window the structure names, as see/when.py counts it.
        self.frame = win32.rect(view.hwnd)
        self.area = (self.frame[2] - self.frame[0]) * (self.frame[3] - self.frame[1]) or 1
        self.small: list[tuple] = []
        self.blank: list[tuple] = []
        self.texts: list[tuple[str, tuple]] = []
        self.nameless: list[tuple[int, str, tuple, str]] = []
        # The surface Chromium draws a page on is not a drawn area.
        self.pages: list[tuple] = []

    def drawn(self) -> float:
        """The share of the target window its biggest nameless area covers, less the small named controls in it."""
        blank = [b for b in self.blank if not any(shape.overlap(b, page) >= 0.5 * b[2] * b[3] for page in self.pages)]
        free = [b[2] * b[3] - sum(c[2] * c[3] for c in self.small if c[0] >= b[0] and c[1] >= b[1]
                                  and c[0] + c[2] <= b[0] + b[2] and c[1] + c[3] <= b[1] + b[3]) for b in blank]
        return round(min(sorted(free)[-1], self.area) / self.area, 3) if free else 0.0

    def read(self, el, top: int, inside: str, parent: uia.Node | None, where: str = "") -> None:
        """One element and what is under it; a big nameless one with nothing named inside is a drawn area."""
        printed, seen = len(self.lines), []
        self._walk(el, top, inside, parent, where, seen)
        if seen and top == self.view.hwnd:
            role, name, box = seen[0]
            if not name and role in ("pane", "custom", "document", "img", "group") and \
                    box[2] * box[3] >= SMALL_SHARE * self.area and not any(
                        '"' in line or not line.lstrip("*").startswith("[") for line in self.lines[printed:]):
                self.blank.append(box)

    def _walk(self, el, top: int, inside: str, parent: uia.Node | None, where: str, seen: list) -> None:
        if self.count >= uia.NODES_MAX:
            return
        self.count += 1
        node = self._node(el, top, parent, where)
        if node is None:
            return
        role, name, box = node.role, node.name, node.rect
        seen.append((role, name, box))
        if top == self.view.hwnd and role in uia.CONTROLS and name and box[2] * box[3] < SMALL_SHARE * self.area:
            self.small.append(box)
        acts = [p for p in node.patterns if p != "text" or role in ("document", "textbox")]
        if role == "document" and uia.holds_role(el, uia.CONTROLS - {"document"}):
            # A web page (Electron, WebView2, CEF, a browser) is a document full of controls: read as a group of
            # them, not as one text.
            if top == self.view.hwnd:
                self.pages.append(box)
            self._group(el, node, inside, more=False)
            return
        if role in ("text", "status") and name and len(self.view.shown) < WATCHED_MAX:
            # A text the window shows (a display, a status line): read again after each action.
            self.view.shown[uia.runtime_id(el)] = (el, name)
        if role == "text" and not acts:
            self._text(node, inside)
            return
        focusable = bool(uia.cached(el, self.A.AutomationElement.IsKeyboardFocusableProperty))
        if not acts and not (role in uia.CONTROLS and (focusable or name)):
            if role == "img" and not name and top == self.view.hwnd and min(box[2], box[3]) >= PICTURE_MIN:
                # A picture with no name (an avatar, an icon): said where it is and how it looks.
                self.lines.append("(picture)")
                self.nameless.append((len(self.lines) - 1, "", box, "picture"))
            self._group(el, node, inside, more=True, headed=role in HEADED)
            return
        self._control(el, node, inside)

    def _node(self, el, top: int, parent: uia.Node | None, where: str) -> uia.Node | None:
        """What the look reads of one element, or None for one it skips with what is under it."""
        E = self.A.AutomationElement
        ctype = uia.cached(el, E.ControlTypeProperty)
        role = uia.role_of(ctype) if ctype is not None else "custom"
        pid = int(uia.cached(el, E.ProcessIdProperty) or 0)
        # A packaged app's frame (ApplicationFrameHost) is not the program: only what its process draws.
        if role in uia.SKIPPED or not self.view.ours(pid):
            return None
        # Scrolled away, clipped by its window, or hidden.
        if uia.cached(el, E.IsOffscreenProperty) and role not in ("window", "menu"):
            return None
        r = uia.cached(el, E.BoundingRectangleProperty)
        box = (int(r.X), int(r.Y), int(r.Width), int(r.Height)) if r is not None and not r.IsEmpty else (0, 0, 0, 0)
        name = uia.norm(uia.cached(el, E.NameProperty))
        auto = str(uia.cached(el, E.AutomationIdProperty) or "")
        secret = bool(uia.cached(el, E.IsPasswordProperty)) or (
            role in ("textbox", "custom") and bool(SECRET_LABEL.search(f"{name} {auto}")))
        return uia.Node(el=el, role=role, name=name, auto=auto, cls=str(uia.cached(el, E.ClassNameProperty) or ""),
                        pid=pid, enabled=bool(uia.cached(el, E.IsEnabledProperty)),
                        focused=bool(uia.cached(el, E.HasKeyboardFocusProperty)), secret=secret, rect=box,
                        hwnd=int(uia.cached(el, E.NativeWindowHandleProperty) or 0),
                        patterns=[p for p, prop in PATTERNS if uia.cached(el, getattr(E, prop))],
                        readonly=bool(uia.cached(el, self.A.ValuePattern.IsReadOnlyProperty)),
                        top=top, parent=parent, cells=[], where=where)

    def _text(self, node: uia.Node, inside: str) -> None:
        """A text the window shows, on a line of its own unless a group above already says it."""
        name, top = node.name, node.top
        if name and top == self.view.hwnd:
            self.texts.append((name, node.rect))
        if name:
            # A dialog's message, for the gate's reading of what its OK confirms.
            self.view.words.setdefault(top, []).append(name)
        if name and name.lower() not in inside and (not self.lines or self.lines[-1] != name):
            self.lines.append(name)

    def _group(self, el, node: uia.Node, inside: str, *, more: bool, headed: bool = True) -> None:
        """An element nothing can be done with: its name as a `## ` line when it is a group the lines below sit in,
        then what is under it."""
        name, where = node.name, node.where
        if name and headed and name.lower() not in inside:
            self.lines.append(f"## {name}")
            inside = f"{inside} {name.lower()}"
            where = name
        for child in el.CachedChildren:
            self.read(child, node.top, inside, node.parent, where)
        if more:
            self._more(el, node.role, name, el.CachedChildren)

    def _control(self, el, node: uia.Node, inside: str) -> None:
        """A control, on its own line with its id, then what is under it."""
        view, lines = self.view, self.lines
        role, name, box, top = node.role, node.name, node.rect, node.top
        ident = view._handle(el)
        view.nodes[ident] = node
        view.interactive += 1
        value = "" if node.secret else view._value(node)
        children = list(el.CachedChildren)
        if role in ("listitem", "row", "treeitem"):
            # A list view's columns (File Explorer's name, type, size, date) go on the item's own line.
            node.cells = [(uia.norm(uia.cached(c, self.A.AutomationElement.NameProperty)), self._cell(c))
                          for c in children if self._is_cell(c)]
            children = [c for c in children if not self._is_cell(c)]
        if value == name:
            value = ""
        if lines and lines[-1].lower() == name.lower():
            lines.pop()
        head = f"[{ident}] {role}"
        start = len(lines)
        lines.append(("*" if self.previous and ident not in self.previous else "") + head
                     + self._said(el, node, value, children)
                     + (f" @{_place(box, self.frame)}" if top == view.hwnd and box[2] else ""))
        view.spans[ident] = (start, len(lines))
        if not name and top == view.hwnd and box[2]:
            self.nameless.append((len(lines) - 1, head, box, "a picture" if uia.holds_role(el, {"img"}) else ""))
        if node.secret or role in ("document", "textbox"):
            return
        inside = f"{inside} {name.lower()} {value.lower()}"
        for child in children:
            self.read(child, top, inside, node, node.where)
        self._more(el, role, name, children)
        # Its own line and the lines under it, for a look at one part (surface.py's look, ref).
        view.spans[ident] = (start, len(lines))

    def _said(self, el, node: uia.Node, value: str, children: list) -> str:
        """What a control's line says after its id and role: secret, name, value, columns, tip, states, options."""
        name = node.name
        details = [v for _n, v in node.cells if v and v != name]
        states = [s for s in self._states(el, node) if s]
        # A tooltip or accessible description, when it says more than the name.
        tip = uia.norm(uia.cached(el, self.A.AutomationElement.HelpTextProperty))
        return ((" [secret]" if node.secret else "")
                + (f' "{clip(name, 150)}"' if name else "")
                + (f" = {quote(value)}" if value else "")
                + (f" ({clip(', '.join(details), 150)})" if details else "")
                + (f" tip {quote(clip(tip, 80))}" if tip and tip != name else "")
                + (" " + " ".join(states) if states else "")
                + (self._options(children) if node.role == "combobox" else ""))

    def _options(self, children: list) -> str:
        """A combo box's choices, read from under it, so one can be selected by name without opening it."""
        E = self.A.AutomationElement
        found = [uia.norm(uia.cached(item, E.NameProperty)) for part in children for item in [part, *part.CachedChildren]
                 if uia.cached(item, E.IsSelectionItemPatternAvailableProperty)]
        found = [o for o in found if o]
        if not found:
            return ""
        return " options: " + " | ".join(clip(o, 30) for o in found[:OPTIONS_MAX]) + (
            f" | and {len(found) - OPTIONS_MAX} more" if len(found) > OPTIONS_MAX else "")

    def _states(self, el, node: uia.Node) -> list[str]:
        A = self.A
        toggle = uia.cached(el, A.TogglePattern.ToggleStateProperty) if "toggle" in node.patterns else None
        expand = uia.cached(el, A.ExpandCollapsePattern.ExpandCollapseStateProperty) if "expand" in node.patterns else None
        return [
            "" if toggle is None else {"On": "checked", "Off": "unchecked"}.get(str(toggle), "mixed"),
            "" if expand is None or str(expand) == "LeafNode" else "expanded" if str(expand) == "Expanded"
            else "collapsed",
            "selected" if "select" in node.patterns and uia.cached(el, A.SelectionItemPattern.IsSelectedProperty) else "",
            "readonly" if "value" in node.patterns and node.readonly and node.role in ("textbox", "combobox") else "",
            "disabled" if not node.enabled else "",
            "focused" if node.focused else ""]

    def _is_cell(self, el) -> bool:
        E = self.A.AutomationElement
        if str(uia.cached(el, E.ClassNameProperty) or "") == "UIProperty":
            return True
        ctype = uia.cached(el, E.ControlTypeProperty)
        return ctype is not None and ctype.ProgrammaticName in ("ControlType.Text", "ControlType.Image") and (
            el.CachedChildren.Count == 0)

    def _cell(self, el) -> str:
        A = self.A
        if uia.cached(el, A.AutomationElement.IsValuePatternAvailableProperty):
            try:
                return uia.norm(el.GetCurrentPropertyValue(A.ValuePattern.ValueProperty))
            except Exception:
                return ""
        ctype = uia.cached(el, A.AutomationElement.ControlTypeProperty)
        return "" if ctype is not None and ctype.ProgrammaticName == "ControlType.Image" else uia.norm(
            uia.cached(el, A.AutomationElement.NameProperty))

    def _more(self, el, role: str, name: str, children) -> None:
        """A list's rows that are scrolled out of view are not printed: say how many, and how to reach one."""
        if role not in LISTS:
            return
        A = self.A
        hidden = sum(1 for c in children if uia.cached(c, A.AutomationElement.IsOffscreenProperty))
        if hidden and hidden < len(children):
            self.lines.append(f"... {hidden} more in {quote(clip(name, 40)) if name else 'this ' + role} are scrolled "
                              f"out of view: select one with its name as \"option\", or scroll")
        elif uia.cached(el, A.ScrollPattern.VerticallyScrollableProperty) and float(
                uia.cached(el, A.ScrollPattern.VerticalViewSizeProperty) or 100) < 99:
            at = float(uia.cached(el, A.ScrollPattern.VerticalScrollPercentProperty) or 0)
            self.lines.append(f"... {quote(clip(name, 40)) if name else 'this ' + role} has more rows "
                              f"{'below' if at < 1 else 'above' if at > 99 else 'above and below'}: scroll to read them")


def _cached_root(hwnd: int, cache):
    """A window's element with what a look reads of it, or None. A window in the middle of drawing itself again
    can fail to answer: asked again before it is taken to have nothing to read."""
    for _again in range(3):
        try:
            return uia.element(hwnd).GetUpdatedCache(cache)
        except Exception:
            time.sleep(0.25)
    return None


def _fit(lines: list[str], budget: float) -> int:
    """How many of `lines` fit in `budget` characters."""
    size = 0
    for i, line in enumerate(lines):
        size += len(line) + 1
        if size > budget:
            return i
    return len(lines)


def _place(box: tuple, frame: tuple) -> str:
    """Where a box sits in the window, as one word of a line (`top-left`)."""
    return shape.place(box, frame).replace(" ", "-")


def _mark(draw, x: int, y: int, text: str, color) -> None:
    wide = 7 * len(text) + 6
    draw.rectangle((x - wide // 2, y - 8, x + wide // 2, y + 8), fill=color)
    draw.text((x - wide // 2 + 3, y - 7), text, fill=(255, 255, 255))
