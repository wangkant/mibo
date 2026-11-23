"""How the character acts in one granted program's window, by the ids of its last look (looking.py).

Actions go through UI Automation patterns first (invoke, set value, toggle, select, expand, scroll), text into an
edit control through the control's own messages; real input (keys, a click at a point) only where a control offers
none, where its pattern did not take (text climbs from the value to the focus and keys, a click and keys, then a
paste, each rung read back: `uia.climb`, writing.py; a press whose action fails ends in a click), or where the
action is input by nature (a right-click menu through Shift+F10, a double click), only once the person has left the
keyboard and mouse alone, and only after the target window is the one in front and the focused control is checked.
Before any action the element is read again: it must still be the kind and name the look printed, or it is found
again by them, or nothing is pressed. After it the program is read again, and the line says what changed as the
program now shows it (a display, a field's text, a tick, a selection, a window): what was done is the program's
word, not the action's.
"""
from __future__ import annotations

import contextlib
import time
from collections.abc import Callable

from ..web.pagewords import SECRET_LABEL, clip, quote, well_formed
from . import uia, win32
from .looking import Looking
from .writing import Writing

PRESS_S = 0.3
OPENS_S = 1.5
# Real input waits until the person has left the keyboard and mouse alone this long, and this long at most.
IDLE_S = 1.5
IDLE_MAX_S = 10.0
# The snapshot an action left is the next one's start while it is this fresh.
FRESH_S = 1.5


class View(Writing, Looking):
    """One granted program's target window: `look()` prints it, the actions act by the ids of the last look."""

    # --- around every action

    def _before(self) -> dict:
        """The snapshot an action starts from: the one the action just before left, when it is that fresh."""
        if self.snap is not None and time.monotonic() - self.snap[0] < FRESH_S:
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
            time.sleep(uia.POLL_S)

    def _give_back(self, front: int) -> None:
        if not self.forwarded and front and win32.foreground() != front and \
                win32.top_of(win32.foreground()) in self.windows():
            win32.give_back(front)

    def _act(self, op: str, ident, body: Callable[[], str], wait: float = uia.SETTLE_S) -> str:
        if self.halted():
            raise uia.Refused(f"[{self.halted()}]")
        before = self._before()
        what = self.describe(ident) if ident is not None else ""
        front, self.forwarded = win32.foreground(), False
        # While this app's own window is the one in front, no other program may take the front for itself.
        if self.own is None:
            self.own = win32.own_tree()
        locked = bool(front) and win32.pid_of(front) in self.own and win32.lock_front(True)
        try:
            detail = body()
        except uia.Refused:
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

    # --- the window in front, and the focus, for real input

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
                uia.element(front).SetFocus()
            except Exception:
                # An Electron or other Chromium window takes no focus from UI Automation: brought in front by
                # Windows itself, as pywinauto's set_focus does.
                win32.give_back(front)
            time.sleep(0.15)
        front = win32.top_of(win32.foreground())
        if front not in self.windows():
            raise uia.Refused("[refused] the window could not be brought in front; nothing was typed or clicked")

    def idle(self) -> None:
        """Real keys and clicks wait until the person has left the keyboard and mouse alone: taking the front under
        their hand would send their keys here and these keys there. After IDLE_MAX_S the strip asks them."""
        end = time.monotonic() + IDLE_MAX_S
        while win32.idle_s() < IDLE_S:
            if self.halted():
                raise uia.Refused(f"[{self.halted()}]")
            if time.monotonic() >= end:
                self.busy()
                raise uia.Refused(f"[paused] the person kept using the computer for {IDLE_MAX_S:g}s; nothing was "
                                  f"typed or clicked")
            time.sleep(0.1)

    def _focused_ok(self, typing: bool) -> None:
        """Real keys go where the focus is: it must be in this program, and never in a password field."""
        A = uia.automation()
        f = A.AutomationElement.FocusedElement
        if f is None or not (self.ours(f.Current.ProcessId) or f.Current.ProcessId == win32.pid_of(self.hwnd)):
            raise uia.Refused("[refused] the keyboard focus is not in this program; nothing was typed. Name the field "
                              "the keys are for (its name or id with the action), so it is clicked into first")
        if f.Current.IsPassword or (typing and SECRET_LABEL.search(f"{f.Current.Name} {f.Current.AutomationId}")
                                    and f.Current.ControlType.ProgrammaticName.endswith("Edit")):
            raise uia.Refused("[refused] the focus is in a password field: that is for the person to type")

    def _focus_on(self, n: uia.Node, click: bool) -> None:
        """The keyboard focus put in `n` with its window in front: by UI Automation, or with `click` by a real
        click at its clickable point (a Chromium page's editable box takes no focus from UI Automation). Missed,
        with why, unless the focus is then in `n`; refused where a password field has it."""
        A = uia.automation()
        if click and n.role not in uia.FIELDS:
            # Clicked, any other control would be pressed, past the gate.
            raise uia.Missed(f"it is a {n.role}, not a text field, so it is not clicked into")
        self.forward()
        if click:
            x, y = self._point(n)
            win32.click_at(x, y)
        else:
            try:
                n.el.SetFocus()
            except Exception as e:
                raise uia.Missed(f"it takes no focus from UI Automation: {uia.reason(e)}") from None
        end = time.monotonic() + uia.SETTLE_S
        while not self._has_focus(n):
            if time.monotonic() >= end:
                f = A.AutomationElement.FocusedElement
                where = "nothing" if f is None else (
                    f"{uia.role_of(f.Current.ControlType)} {quote(clip(uia.norm(f.Current.Name), 40))}")
                raise uia.Missed(f"the focus went to {where}, not to it")
            time.sleep(uia.POLL_S)
        self._focused_ok(True)

    def _has_focus(self, n: uia.Node) -> bool:
        """Whether the keyboard focus is on `n` or inside it, or on the edit box `n` sits in (a Chromium editable
        host round the element the look printed)."""
        A = uia.automation()
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

    def _focus(self, n: uia.Node) -> str:
        """The focus put in `n` for a key: by UI Automation, else by a real click on it. Returns how it went in."""
        missed = []
        for click in (False, True):
            try:
                self._focus_on(n, click)
                return " (after a click on it)" if click else ""
            except uia.Missed as e:
                missed.append(str(e))
        raise uia.Refused(f"[failed] the focus would not go into {n.role} {quote(clip(n.name, 60))}: "
                          f"{'; then, after a click on it, '.join(missed)}. Nothing was pressed or typed: look again "
                          f"(it may be covered, or open only after another control is pressed), or ask_person")

    def _point(self, n: uia.Node) -> tuple[int, int]:
        """Where a click lands on `n`: the centre of the part of it its window shows (a list row runs on under
        the columns out of view). Refused when UI Automation finds there neither `n` nor an element inside it, or
        the window there is not the program's (something covers it, or it scrolled away)."""
        A = uia.automation()
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
            raise uia.Refused(f"[refused] something else shows at the point of {n.role} {quote(clip(n.name, 60))}; "
                              f"nothing was clicked")
        return x, y

    # --- the actions

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
        A = uia.automation()

        def press() -> str:
            if not n.enabled:
                raise uia.Refused(f"[failed] {self.describe(ident)} is disabled")
            if "invoke" in n.patterns:
                n.el.GetCurrentPattern(A.InvokePattern.Pattern).Invoke()
                return " (pressed once)"
            if "toggle" in n.patterns:
                return f" (toggled), read back and it is {'checked' if self._flip(n) == 'On' else 'unchecked'}"
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
            except uia.Refused:
                raise
            except Exception as e:
                why = uia.reason(e)
            if not self.forwarded:
                self.forward()
                try:
                    return press()
                except uia.Refused:
                    raise
                except Exception as e:
                    why = uia.reason(e)
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

    def _flip(self, n: uia.Node) -> str:
        """Toggle `n` and wait for its state to change, SETTLE_S at most; its state then ("On", "Off", ...)."""
        A = uia.automation()

        def state() -> str:
            return str(n.el.GetCurrentPropertyValue(A.TogglePattern.ToggleStateProperty))
        was = state()
        n.el.GetCurrentPattern(A.TogglePattern.Pattern).Toggle()
        end = time.monotonic() + uia.SETTLE_S
        while state() == was and time.monotonic() < end:
            time.sleep(uia.POLL_S)
        return state()

    def toggle(self, ident: int, on: bool | None = None) -> str:
        """Flip a tick box, or with `on` bring it to that state (nothing is pressed when it is there already);
        the state is read back."""
        ident = self.live(ident)
        n = self.node(ident)
        A = uia.automation()

        def body() -> str:
            if "toggle" not in n.patterns:
                raise uia.Refused(f"[failed] {self.describe(ident)} is not a tick box or a switch")
            want = None if on is None else "On" if on else "Off"
            if str(n.el.GetCurrentPropertyValue(A.TogglePattern.ToggleStateProperty)) == want:
                return f" (it was already {'checked' if on else 'unchecked'}; nothing pressed)"
            now = self._flip(n)
            if want is not None and now != want:
                raise uia.Refused(f"[failed] {self.describe(ident)} did not become {'checked' if on else 'unchecked'}")
            return f", read back and it is {'checked' if now == 'On' else 'unchecked'}"
        return self._act("toggle", ident, body, wait=0)

    def select(self, ident: int, option: str = "") -> str:
        """Select an item; for a list or a combo box, the item named `option` under it (also one scrolled out
        of view). The selection is read back."""
        ident = self.live(ident)
        n = self.node(ident)
        A = uia.automation()

        def picked(el) -> bool:
            end = time.monotonic() + uia.SETTLE_S
            while time.monotonic() < end:
                if el.GetCurrentPropertyValue(A.SelectionItemPattern.IsSelectedProperty):
                    return True
                time.sleep(uia.POLL_S)
            return False

        def body() -> str:
            if not option:
                if "select" not in n.patterns:
                    raise uia.Refused(f"[failed] {self.describe(ident)} is not an item that can be selected; for a "
                                      f"list or a combobox give the item's name as \"option\"")
                n.el.GetCurrentPattern(A.SelectionItemPattern.Pattern).Select()
                if not picked(n.el):
                    raise uia.Refused(f"[failed] {self.describe(ident)} does not show as selected")
                return ", read back and it is selected"
            if "expand" in n.patterns:
                n.el.GetCurrentPattern(A.ExpandCollapsePattern.Pattern).Expand()
                time.sleep(0.2)
            items = n.el.FindAll(A.TreeScope.Descendants, A.PropertyCondition(
                A.AutomationElement.IsSelectionItemPatternAvailableProperty, True))
            want = uia.norm(option).lower()
            hits = [it for it in items if uia.norm(it.Current.Name).lower() == want] or [
                it for it in items if uia.norm(it.Current.Name).lower().startswith(want)]
            if len(hits) != 1:
                names = " | ".join(uia.norm(it.Current.Name) for it in list(items)[:30])
                raise uia.Refused(f"[failed] {'several' if hits else 'no'} options match {option!r}. Options: {names}")
            hits[0].GetCurrentPattern(A.SelectionItemPattern.Pattern).Select()
            chosen = picked(hits[0])
            if "expand" in n.patterns:
                with contextlib.suppress(Exception):
                    n.el.GetCurrentPattern(A.ExpandCollapsePattern.Pattern).Collapse()
            if not chosen:
                raise uia.Refused(f"[failed] {quote(uia.norm(hits[0].Current.Name))} does not show as selected in "
                                  f"{self.describe(ident)}")
            return f" = {quote(uia.norm(hits[0].Current.Name))}, read back and it is selected"
        return self._act("select", ident, body, wait=0)

    def expand(self, ident: int, open_: bool | None = None) -> str:
        ident = self.live(ident)
        n = self.node(ident)
        return self._act("expand" if open_ is not False else "collapse", ident, lambda: self._expand(n, open_))

    def _expand(self, n: uia.Node, open_: bool | None) -> str:
        A = uia.automation()
        p = n.el.GetCurrentPattern(A.ExpandCollapsePattern.Pattern)
        if open_ is None:
            open_ = str(p.Current.ExpandCollapseState) != "Expanded"
        (p.Expand if open_ else p.Collapse)()
        return " (opened)" if open_ else " (closed)"

    def scroll(self, ident: int | None = None, down: bool = True) -> str:
        """Scroll an element that scrolls, the nearest one above `ident`, or the window's biggest; the wheel
        over it when none offers the scroll pattern."""
        A = uia.automation()

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
        A = uia.automation()

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
            raise uia.Refused(f"[failed] {self.describe(ident)} opened no menu; nothing else was done")
        return self._act("menu", ident, body, wait=OPENS_S)

    def _popup(self, before: set[int]) -> int:
        """A menu or pop-up of the program that came up after `before`, waited for OPENS_S at most, or 0."""
        end = time.monotonic() + OPENS_S
        while time.monotonic() < end:
            for h in win32.top_windows():
                if h not in before and win32.pid_of(h) in self.pids and win32.shown(h) and (
                        win32.class_of(h) == "#32768" or win32.popup(h)):
                    return h
            time.sleep(uia.POLL_S)
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

    def key(self, keys: str, ident: int | None = None) -> str:
        """One keystroke with its modifiers, e.g. "Enter", "Ctrl+A", "Shift+Tab", "F2", "Ctrl+Shift+S": where the
        focus is, or with `ident` in that control, the focus put there first (by a real click on it when it takes
        none from UI Automation)."""
        vks = uia.parse_key(keys)
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
        want = uia.norm(until).lower()

        def body() -> str:
            end = time.monotonic() + seconds
            while not self.halted():
                if want in self.look().lower():
                    return f" until it shows {quote(clip(until, 40))}: it does"
                if time.monotonic() >= end:
                    break
                time.sleep(0.3)
            raise uia.Refused(f"[failed] waited {seconds:g}s and the window does not show {quote(clip(until, 40))}")
        return self._act("wait", None, body, wait=0)
