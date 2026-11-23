"""The part of `hands.Hands` for an action with an effect outside the window: the person's press on a card first
(or, in auto mode, the reviewer's pass), the action exactly once, then a look again for proof that it took. And
the files such an action touches, read from File Explorer and the Save and Open dialogs. Mixed into `hands.Hands`,
whose `view`, `program`, `modes`, `review`, `ask`, `held`, `task` and `lang` it uses.
"""
from __future__ import annotations

import os
import re
import secrets
import time
from collections.abc import Callable
from pathlib import Path

from ..web.pagewords import clip, quote
from . import gate, uia, win32
from .operate import UNANSWERED

# How long a program is given to show what a confirmed action did, before the line says it does not show yet.
PROOF_S = 1.5
# The common Save and Open dialogs: the file name box and the address band, in English and Chinese Windows.
FILE_NAME = re.compile(r"(?:file name|文件名)\s*(?:\(&?\w\))?\s*[:：]?", re.I)
ADDRESS = re.compile(r"(?:address|地址)\s*[:：]\s*(.+)", re.I)


class Outside:
    """Asking for, doing once and proving an action with an effect outside the window."""

    def _composer(self, node):
        """The text box a Send or Post button sends from: the nearest field of its window that holds text
        (never a password field), or None."""
        x, y = node.center()
        boxes = [n for n in self.view.nodes.values() if n.top == node.top and n.role in ("textbox", "document")
                 and not n.secret and not n.readonly and n is not node and self._said(n)]
        return min(boxes, key=lambda n: abs(n.center()[1] - y) * 3 + abs(n.center()[0] - x), default=None)

    def _outside(self, kind: str, why: str, node, text: str, files: list[str], run: Callable[[], str],
                 source=None) -> dict:
        """The person's press on a card first, each time (in auto mode the reviewer may pass what acting.decide
        sends it); then the action exactly once; then a look again. `source` is the field the text comes from,
        when it is not the target itself."""
        from .. import acting
        v = self.view
        name = node.name if node is not None else ""
        before = (self._fingerprint(node), self._fingerprint(source))
        window = clip(win32.title_of(node.top if node else v.hwnd), 120)
        how = "confirmed by the person"
        answer = verdict = None
        if self.review is not None and acting.decide(self.modes.mode(), kind, "", "programs") == "review":
            verdict = self.review({"kind": kind, "where": f"{self.program['name']} — {window}",
                                   "target": files[:50] or ([name] if name else []), "text": text[:2000],
                                   "page_says": name})
            if verdict.decision == "refuse":
                return {"status": "declined", "kind": kind,
                        "line": f"[declined] {kind} ({clip(name, 40)}), nothing was done. {verdict.declined()}"
                                + ("; turned down three times in a row: stop and hand the task back" if verdict.stop
                                   else "")}
            if verdict.decision == "go":
                answer, how = {"yes": True}, verdict.line(self.lang)
        if answer is None:
            try:
                picture = thumbnail(win32.capture(v.hwnd)[0], 60)
            except Exception:
                picture = ""
            card = {"id": secrets.token_urlsafe(8), "type": "desk_action", "kind": kind,
                    "program": self.program["name"], "exe": self.program["exe"], "window": window,
                    "target": f"{node.role} {quote(clip(name, 80))}" if node is not None else "",
                    "text": text[:2000], "files": files[:50], "why": why[:200], "task": self.task, "picture": picture,
                    # Why the reviewer did not pass it, in one line.
                    **({"review": verdict.line(self.lang)} if verdict is not None else {})}
            answer = self.ask(card)
        if answer is None:
            return {"status": "declined", "kind": kind,
                    "line": f"[declined] {UNANSWERED} for {kind} ({clip(name, 40)}); nothing was done"}
        if not answer.get("yes"):
            return {"status": "declined", "kind": kind,
                    "line": f"[declined] the person said no to {kind} ({clip(name, 40)}); nothing was done"}
        if self.held():
            return {"status": self.held(), "kind": kind, "line": f"[{self.held()}] nothing was done"}
        if (self._fingerprint(node), self._fingerprint(source)) != before:
            return {"status": "failed", "kind": kind,
                    "line": "[changed] the window changed since the question; nothing was done, look again"}
        line = run()
        if not line.startswith("[ok]"):
            return {"status": "failed", "kind": kind, "line": line}
        proof = self._proof(kind, source or node, text, files)
        return {"status": "ok", "kind": kind, "outside": True, "line": f"{line} ({kind}, {how}; done once){proof}"}

    def _fingerprint(self, node) -> tuple:
        """What the card showed of the target, read again: its name and, for a field, what it holds."""
        if node is None:
            return ()
        try:
            name = str(node.el.Current.Name)
            held = "" if node.secret else self._said(node)
            return name, held
        except Exception:
            return ("gone",)

    def _said(self, node) -> str:
        """What a field or document holds now (never a password field's), or ""."""
        A = uia.automation()
        if node is None or node.secret:
            return ""
        try:
            if node.el.GetCurrentPropertyValue(A.AutomationElement.IsValuePatternAvailableProperty):
                return str(node.el.GetCurrentPropertyValue(A.ValuePattern.ValueProperty) or "")[:2000]
            if node.el.GetCurrentPropertyValue(A.AutomationElement.IsTextPatternAvailableProperty):
                return str(node.el.GetCurrentPattern(A.TextPattern.Pattern).DocumentRange.GetText(2000))
        except Exception:
            return ""
        return ""

    def _proof(self, kind: str, node, text: str, files: list[str]) -> str:
        """Done is not proven by the press: look again. A file view shows the new name or the files gone; a
        field that sent its text is empty again. The program is given PROOF_S to show it, read until it does."""
        end = time.monotonic() + PROOF_S
        if kind in ("send", "submit") and node is not None and text:
            while self._said(node) and time.monotonic() < end:
                time.sleep(0.05)
            if not self._said(node):
                return "; looked again: the field is empty"
            return "; looked again: the field still holds the text, so look before saying it went, and never press again"
        while True:
            try:
                self.view.look()
            except uia.Refused as e:
                return f"; {e}"
            names = {n.name for n in self.view.nodes.values() if n.role in ("listitem", "row", "treeitem")}
            shown = (kind == "file" and files and text in names and files[0] not in names) or (
                kind == "delete" and files and names and not any(f in names for f in files))
            if shown or not ((kind == "file" and text) or kind == "delete") or not files or time.monotonic() >= end:
                break
            time.sleep(0.2)
        if kind == "file" and files and text:
            if text in names and files[0] not in names:
                return f"; looked again: {files[0]!r} now shows as {text!r}"
            return "; looked again: the new name does not show yet, so look before saying it is done, and never do it again"
        if kind == "delete" and files and names:
            gone = [f for f in files if f not in names]
            return (f"; looked again: {len(gone)} of {len(files)} no longer show" if gone else
                    "; looked again: still showing, so look before saying it is done, and never do it again")
        return "; looked again"

    # --- File Explorer and the file dialogs

    def _base(self) -> str:
        return Path(self.program.get("exe", "")).name.lower()

    def _address_bar(self, node) -> bool:
        return node is not None and self._base() == "explorer.exe" and node.role in (
            "textbox", "combobox") and not gate.in_shell_view(node) and not gate.SEARCH.search(
                f"{node.name} {node.auto}")

    def _is_folder(self, node) -> bool | None:
        """For an item of a file view, whether its Type column says folder; None when it has no such column."""
        if node.role not in ("listitem", "treeitem", "row") or not gate.in_shell_view(node):
            return None
        if node.role == "treeitem":
            return True
        kinds = [value for _name, value in node.cells]
        return win32.folder_type() in kinds if kinds else None

    def _files(self, node, kind: str, said: str = "") -> list[str]:
        """The files an action touches: the item renamed or opened, else the items selected in the file view
        of the same window (for Delete, Paste and the like)."""
        if node is None:
            return []
        # An item of a right-click menu acts on what the menu was opened on.
        node = self.view.menus.get(node.top, node)
        items = ("listitem", "row", "treeitem")
        if node.parent is not None and node.parent.role in items and gate.in_shell_view(node):
            return [node.parent.name]
        if node.role in items and gate.in_shell_view(node) and kind in ("open", "file"):
            return [node.name]
        if kind not in ("delete", "file", "open"):
            return []
        saved = self._dialog_file(node.top) if kind in ("file", "open") else ""
        if saved:
            return [saved]
        return self._picked(node.top) or ([node.name] if node.role in items and gate.in_shell_view(node) else [])

    def _dialog_file(self, top: int) -> str:
        """In a Save or Open dialog: the file its File name box names, in the folder its address shows."""
        mine = [n for n in self.view.nodes.values() if n.top == top]
        box = next((n for n in mine if n.role == "textbox" and FILE_NAME.fullmatch(n.name)), None)
        name = self._said(box).strip().strip('"') if box is not None else ""
        if not name:
            return ""
        A = uia.automation()
        bars = uia.element(top).FindAll(A.TreeScope.Descendants, A.PropertyCondition(
            A.AutomationElement.ControlTypeProperty, A.ControlType.ToolBar))
        folder = next((m.group(1).strip() for b in bars for m in [ADDRESS.match(uia.norm(b.Current.Name))] if m), "")
        return name if os.path.isabs(name) or not folder else os.path.join(folder, name)

    def _picked(self, top: int) -> list[str]:
        """The items selected in the file view of window `top`."""
        return [n.name for n in self.view.nodes.values() if n.top == top and n.role in ("listitem", "row", "treeitem")
                and gate.in_shell_view(n) and self._selected(n)]

    @staticmethod
    def _selected(n) -> bool:
        A = uia.automation()
        try:
            return bool(n.el.GetCurrentPropertyValue(A.SelectionItemPattern.IsSelectedProperty))
        except Exception:
            return False


def thumbnail(image, quality: int) -> str:
    """A window's picture for a card, without the marks: at most 720 pixels a side, a JPEG in base64."""
    image.thumbnail((720, 720))
    return win32.jpeg64(image, quality)
