"""How the character writes into a field of another program's window: up the ladder UI automation tools climb
(`uia.climb`), the field read back after every rung, and never into a password field. Mixed into `view.View`, whose
`_act`, `live`, `forward`, `_focus_on` and `_focused_ok` it uses.
"""
from __future__ import annotations

import time
from collections.abc import Callable

from ..web.pagewords import clip, quote
from . import uia, win32


def held_by(el) -> str | None:
    """What a live element holds now, or None when it offers no way to say."""
    A = uia.automation()
    if el.GetCurrentPropertyValue(A.AutomationElement.IsTextPatternAvailableProperty):
        return str(el.GetCurrentPattern(A.TextPattern.Pattern).DocumentRange.GetText(-1))
    if el.GetCurrentPropertyValue(A.AutomationElement.IsValuePatternAvailableProperty):
        return str(el.GetCurrentPropertyValue(A.ValuePattern.ValueProperty) or "")
    return None


class Writing:
    """Setting, typing into and pasting into a field of the last look."""

    def set_value(self, ident: int, text: str, append: bool = False) -> str:
        """Replace what a field holds with `text` (or, with `append`, add it after what it holds), up the ladder
        `climb` names: its value pattern or the edit control's own messages, then the focus and keys, then a real
        click and keys, then a click and a paste. The field is read back after each rung, and the line says what
        it holds. Never into a password field."""
        ident, n = self._field(ident)
        A = uia.automation()
        want = text.replace("\r\n", "\n")
        op = "append to" if append else "set"

        def body() -> str:
            if not append and len(self.text_of(ident)) > uia.DOCUMENT_MAX:
                # The look showed only its beginning: writing that back would cut the rest off.
                raise uia.Refused(f"[failed] {self.describe(ident)} holds more text than the look shows; setting it "
                                  f"would lose the rest. Use append, or the program's own find and replace")
            was = self._unfilled(n, self._plain(ident)) if append else ""
            # Added to a document, text starts on a line of its own.
            apart = append and n.role == "document" and was and not was.endswith("\n") and not want.startswith("\n")
            whole = was + ("\n" if apart else "") + want if append else want
            add = whole[len(was):] if append else whole
            start = [win32.VK["Ctrl"], win32.VK["End"]] if append else [win32.VK["Ctrl"], ord("A")]

            def landed(holds: str) -> bool:
                return uia.same_text(holds, whole)

            def by_value() -> None:
                if "value" in n.patterns and not n.readonly:
                    n.el.GetCurrentPattern(A.ValuePattern.Pattern).SetValue(
                        whole.replace("\n", "\r\n") if n.hwnd and win32.multiline(n.hwnd) else whole)
                else:
                    win32.edit_replace(n.hwnd, add, whole=not append, end=append)
            rungs = [(uia.BY_KEYS, self._rung(n, ident, add, landed, start=start)),
                     (uia.BY_CLICK, self._rung(n, ident, add, landed, click=True, start=start)),
                     (uia.BY_PASTE, self._rung(n, ident, add, landed, click=True, paste=True, start=start))]
            # A combo box's edit takes a set value without telling its program (a file dialog then saves under
            # the old name), so that one is typed.
            if not win32.in_combo(n.hwnd) and (("value" in n.patterns and not n.readonly) or (
                    n.hwnd and win32.edit_box(n.hwnd))):
                rungs.insert(0, (uia.BY_VALUE, by_value))
            # Appended text typed twice would be there twice; a whole text written again only replaces itself.
            return self._climbed(op, ident, rungs, self._reader(n, ident), landed, again=not append,
                                 lead=f" = {quote(clip(text, 60))}",
                                 proof="read back and it holds exactly that" + (
                                     " after what it held" if append and was else ""))
        return self._act("append" if append else "set", ident, body, wait=0)

    def type(self, ident: int | None, text: str) -> str:
        """Type `text` at the caret of `ident`, up the ladder `climb` names: an edit control's own messages, then
        the focus and real keys, then a real click and keys, then a click and a paste; a line break goes as
        Shift+Enter. The field is read back after each rung. Without `ident`, real keys where the focus is. Never
        into a password field."""
        ident, n = self._field(ident)
        if n is None:
            def at_focus() -> str:
                self.forward()
                self._focused_ok(True)
                self._type(text)
                return f" {quote(clip(text, 60))}"
            return self._act("type", None, at_focus)

        def body() -> str:
            read = self._reader(n, ident)
            landed = self._inserted(text, read() if read else "")
            rungs = [(uia.BY_KEYS, self._rung(n, ident, text, landed)),
                     (uia.BY_CLICK, self._rung(n, ident, text, landed, click=True)),
                     (uia.BY_PASTE, self._rung(n, ident, text, landed, click=True, paste=True))]
            if n.hwnd and win32.edit_box(n.hwnd) and not win32.in_combo(n.hwnd):
                rungs.insert(0, (uia.BY_MESSAGES, lambda: win32.edit_replace(n.hwnd, text, whole=False)))
            return self._climbed("type into", ident, rungs, read, landed, again=False,
                                 lead=f" {quote(clip(text, 60))}", proof="read back and it is there")
        return self._act("type", ident, body, wait=0)

    def paste(self, ident: int | None, text: str) -> str:
        """Put `text` in at the caret of `ident` as Ctrl+V does, focused by UI Automation, else by a real click: the
        person's clipboard is kept, the text set there, Ctrl+V sent once the focus is checked, and their clipboard
        put back once the field shows the text. Without `ident`, where the focus is. Never into a password field."""
        ident, n = self._field(ident)
        if n is None:
            return self._act("paste", None, lambda: self._paste_at_focus(text))

        def body() -> str:
            read = self._reader(n, ident)
            landed = self._inserted(text, read() if read else "")
            rungs = [(uia.BY_FOCUS_PASTE, self._rung(n, ident, text, landed, paste=True)),
                     (uia.BY_PASTE, self._rung(n, ident, text, landed, click=True, paste=True))]
            return self._climbed("paste into", ident, rungs, read, landed, again=False,
                                 lead=f" {quote(clip(text, 60))}", proof="read back and it is there")
        return self._act("paste", ident, body, wait=0)

    def _paste_at_focus(self, text: str) -> str:
        """A paste where the focus is, read back from the focused element when it offers a way."""
        A = uia.automation()
        want = uia.plain_text(text)
        self.forward()
        self._focused_ok(True)
        field = A.AutomationElement.FocusedElement
        got: list[str | None] = [None]

        def landed() -> bool:
            got[0] = held_by(field)
            return got[0] is not None and want in uia.plain_text(got[0])
        self._paste_keys(text, landed)
        if got[0] is None:
            return f" {quote(clip(text, 60))} (through the clipboard, theirs put back)"
        if want not in uia.plain_text(got[0]):
            raise uia.Refused(f"[failed] paste into the focused field: after pasting, it holds "
                              f"{quote(clip(got[0], 200))}, which does not have the text given")
        return f" {quote(clip(text, 60))} (through the clipboard, theirs put back), read back and it is there"

    # --- the steps of a write

    def _field(self, ident: int | None) -> tuple[int | None, uia.Node | None]:
        """The id and node a write goes into, read again (None, None for where the focus is); refused for a
        password field."""
        if ident is None:
            return None, None
        ident = self.live(ident)
        n = self.node(ident)
        if n.secret:
            raise uia.Refused(f"[refused] {self.describe(ident)} is a password field: it is for the person to fill")
        return ident, n

    def _rung(self, n: uia.Node, ident: int, text: str, landed: Callable[[str], bool], *, click: bool = False,
              paste: bool = False, start: list[int] | None = None) -> Callable[[], None]:
        """One rung of real input: the focus put in `n` (by a click with `click`), the `start` keys, then `text`
        typed or, with `paste`, pasted until the field shows it."""
        def act() -> None:
            self._focus_on(n, click)
            if start:
                win32.chord(start)
            if paste:
                self._paste_keys(text, lambda: landed(self._plain(ident)))
            else:
                self._type(text)
        return act

    def _climbed(self, op: str, ident: int, rungs: list, read: Callable[[], str] | None,
                 landed: Callable[[str], bool], *, again: bool, lead: str, proof: str) -> str:
        """The ladder climbed for one write: the end of its line (`lead` the text written, `proof` what reading it
        back found), or the write refused with what to do next."""
        rung, holds, tried = uia.climb(rungs, read, landed, again=again)
        if not rung:
            raise self._missed(op, ident, holds, tried, len(tried) < len(rungs), read is not None)
        if read is None:
            return f"{lead}{uia.HOW[rung]}; {uia.UNREAD}"
        return f"{lead}{uia.HOW[rung]}, {proof}" + uia.tried_before(tried)

    def _reader(self, n: uia.Node, ident: int) -> Callable[[], str] | None:
        """How a write reads its field back, or None when the field offers no way to read its text."""
        return (lambda: self._plain(ident)) if {"value", "text"} & set(n.patterns) else None

    @staticmethod
    def _unfilled(n: uia.Node, holds: str) -> str:
        """What an empty field holds, as text written after it: nothing, where the field shows only its own name
        (Chromium reads an empty box as its placeholder, which is also its name)."""
        return "" if n.name and uia.same_text(holds, n.name) else holds

    @staticmethod
    def _inserted(text: str, was: str) -> Callable[[str], bool]:
        """Whether a field holds `text` once more than it did before (`was`): text put in at the caret."""
        want = uia.plain_text(text)
        return lambda holds: uia.plain_text(holds).count(want) > uia.plain_text(was).count(want)

    def _missed(self, op: str, ident: int, holds: str, tried: list[str], partly: bool, readable: bool) -> uia.Refused:
        """Why a write took on no rung, with what to do next: never the same write again."""
        what = self.describe(ident)
        n = self.node(ident)
        if not readable:
            return uia.Refused(f"[failed] {op} {what}: tried {'; then '.join(tried)}; none got to the field. Nothing "
                               f"was written: look again (another control may have to be pressed first), or "
                               f"ask_person and say what the window shows")
        shown = (f"only its own name {quote(clip(holds, 60))}, as an empty field shows its placeholder"
                 if n.name and uia.same_text(holds, n.name) else quote(clip(holds, 200)))
        if partly:
            return uia.Refused(f"[failed] {op} {what}: after {tried[-1]} it holds {shown}, which is not the text "
                               f"given; nothing more was put in, so nothing goes in twice. Set the field to the whole "
                               f"text to correct it")
        return uia.Refused(f"[failed] {op} {what}: tried {'; then '.join(tried)}; after them it holds {shown}. "
                           f"Nothing was written, and set, type or paste again will not take either: look again "
                           f"(another control may have to be pressed first, such as a new chat or an edit button, or "
                           f"the text goes in another field), or ask_person and say what the window shows")

    def _paste_keys(self, text: str, landed: Callable[[], bool]) -> None:
        """Ctrl+V with `text` on the clipboard, the person's own put back once `landed()` (the program reads the
        clipboard when it handles the keys), 2 * SETTLE_S at most."""
        theirs = win32.clipboard_save()
        try:
            win32.clipboard_put(win32.clipboard_text(text))
            win32.chord([win32.VK["Ctrl"], ord("V")])
            end = time.monotonic() + 2 * uia.SETTLE_S
            while not landed() and time.monotonic() < end:
                time.sleep(uia.POLL_S)
        finally:
            win32.clipboard_put(theirs)

    def _type(self, text: str) -> None:
        """Real keystrokes in short runs; between runs, a stop or a focus that moved ends the typing."""
        A = uia.automation()
        start = list(A.AutomationElement.FocusedElement.GetRuntimeId())
        for i in range(0, len(text), 40):
            why = self.halted()
            if why:
                raise uia.Refused(f"[{why}] stopped while typing, after {i} characters")
            self._focused_ok(True)
            if list(A.AutomationElement.FocusedElement.GetRuntimeId()) != start:
                raise uia.Refused(f"[failed] the focus moved while typing, after {i} characters; look again")
            win32.type_text(text[i:i + 40])
