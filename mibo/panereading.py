"""The pane's reading (browser.Pane): every page is timed while the window is in front, shown and in use, and when it
is left it goes to the pane's `visit` (browsed.py keeps the row; a find's time also goes to the recommender), unless
its tab is private or the page is a sign-in or payment page. A page read long enough is read off once for its facts
(`page_of`, which the Reader's reads give too)."""
from __future__ import annotations

import contextlib
import ctypes
import json
import threading
import time

from . import browsed
from .webview2 import run_script, script_answer

# Reading: no input for this long and the time stops counting.
IDLE_S = 60
# How often a page in front checks for that, and for a password field come late; nothing ticks otherwise.
TICK_MS = 20000
# Shorter than this is a glance, not a reading.
READ_MIN_S = 2
SECRET_SCRIPT = "!!document.querySelector('input[type=password]')"
# What a page's facts keep of its text when it is read off as the person reads it (a read for the character
# hands over all it read), and a list's rows.
TEXT_MAX = 6000
ROWS_MAX = 40


def last_input_tick() -> int:
    """When Windows last saw a key or pointer input anywhere on this computer (GetLastInputInfo), in its own
    ticks."""
    from ctypes import wintypes

    class LastInput(ctypes.Structure):
        _fields_ = [("size", wintypes.UINT), ("time", wintypes.DWORD)]

    info = LastInput()
    info.size = ctypes.sizeof(LastInput)
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info))
    return int(info.time)


def _idle_s() -> float:
    """How long since the last key or pointer input anywhere on this computer."""
    return ((ctypes.windll.kernel32.GetTickCount() - last_input_tick()) & 0xFFFFFFFF) / 1000


def facts_script() -> str:
    """The generic reader (web/reader.js) over the page as it is: its rows, its content, its own facts."""
    from .web.read import READER
    return f"({READER})({{}})"


def page_of(url: str, data, rows: list | None = None, start: int = 0, most: int = TEXT_MAX) -> dict:
    """What a read page gives: title, declared facts and readable text, as roam.py reads them, for a list its rows
    (title, link, author, time, counts), and the page's own links to its messages or notifications ("inbox",
    reader.js). The text is the `most` characters from `start`."""
    from .pagefacts import facts_from
    data = data if isinstance(data, dict) else {}
    facts = facts_from(data, url)
    inbox = [{"href": str(link["href"])[:2000], "text": str(link.get("text") or "")[:40]}
             for link in (data.get("discovery") or {}).get("inbox") or [] if isinstance(link, dict) and link.get("href")]
    listed = [{k: str(row.get(k) or "")[:300] for k in ("title", "link", "author", "time") if row.get(k)}
              | ({"counts": row["counts"]} if isinstance(row.get("counts"), dict) and row["counts"] else {})
              for row in (data.get("rows") if rows is None else rows) or [] if isinstance(row, dict)]
    text = facts.get("text") or ""
    return {"url": url, "title": facts.get("title") or str(data.get("title") or ""),
            "site": facts.get("site", ""), "kind": facts.get("kind", ""), "author": facts.get("author", ""),
            "published": facts.get("published", ""), "description": facts.get("description", ""),
            "text": text[start:start + most],
            **({"rows": [row for row in listed if row.get("title")][:ROWS_MAX]}
               if data.get("kind") == "list" else {}),
            **({"inbox": inbox[:6]} if inbox else {})}


class ReadingPane:
    """The part of browser.Pane that times the page in front, on the form's thread. The page being read is
    `_reading`: its address, title, find id once known, seconds counted and since when (monotonic), whether it
    showed a password field, and its facts once read long enough."""

    def _begin(self, address: str) -> None:
        """A page begins to be read: the last one is handed over first."""
        self._send(self._finish())
        self._reading = {"url": address, "title": "", "id": "", "s": 0.0, "since": None, "begun": False,
                         "secret": self.private, "facts": None, "at": time.time()}
        reading = self._reading
        threading.Thread(target=self._look_up, args=(reading,), name="mibo-browser", daemon=True).start()

    def _look_up(self, reading: dict) -> None:
        ident = self.find(reading["url"])
        if ident:
            self.ui(lambda: self._found(reading, ident))

    def _found(self, reading: dict, ident: str) -> None:
        if reading is self._reading:
            reading["id"] = ident

    def _check_secret(self, reading: dict) -> None:
        """A password field on the page makes it a sign-in page: never kept. Asked again on each tick."""
        task = run_script(self._core, SECRET_SCRIPT)

        def heard() -> None:
            if script_answer(task, 10) == "true":
                reading["secret"] = True
        threading.Thread(target=heard, name="mibo-browser", daemon=True).start()

    def _resized(self, sender, args) -> None:
        from System.Windows.Forms import FormWindowState
        if self.form.WindowState == FormWindowState.Minimized:
            self._pause()
        else:
            self._count()

    def _count(self) -> None:
        """Count from now, while the page shows in front."""
        from System.Windows.Forms import Form, FormWindowState
        reading, form = self._reading, self.form
        if (reading is None or not reading["begun"] or reading["since"] is not None or self._view is None
                or self._quieted or self._hidden or not form.Visible
                or form.WindowState == FormWindowState.Minimized
                or Form.ActiveForm is None or not Form.ActiveForm.Equals(form)):
            return
        reading["since"] = time.monotonic()
        self._timer.Start()

    def _settle(self) -> None:
        """Add the time since the last look, not counting what went past a minute without input."""
        reading = self._reading
        if reading is None or reading["since"] is None:
            return
        now = time.monotonic()
        last_input = now - _idle_s()
        reading["s"] += max(0.0, min(now, last_input + IDLE_S) - reading["since"])
        reading["since"] = now

    def _tick(self, sender, args) -> None:
        self._settle()
        reading = self._reading
        if reading is None or self._core is None or not reading["begun"]:
            return
        self._check_secret(reading)
        if reading["facts"] is None and reading["s"] >= browsed.ITEM_S and not reading["secret"] and not self.private:
            # Read long enough to become an Item: what it is, read off the page once.
            reading["facts"] = {}
            task = run_script(self._core, facts_script())

            def heard() -> None:
                raw = script_answer(task, 10)
                with contextlib.suppress(ValueError, TypeError):
                    reading["facts"] = page_of(reading["url"], json.loads(raw))
            threading.Thread(target=heard, name="mibo-browser", daemon=True).start()

    def _pause(self) -> None:
        self._settle()
        if self._reading is not None:
            self._reading["since"] = None
        self._timer.Stop()

    def _finish(self) -> dict | None:
        """The reading ends: the row to hand over, or None for a private or a sign-in page, or for a glance at
        anything but a find (a find's glance is handed over: the recommender learns from it)."""
        self._pause()
        reading, self._reading = self._reading, None
        if (reading is None or (reading["s"] < READ_MIN_S and not reading["id"]) or reading["secret"] or self.private
                or not browsed.web(reading["url"]) or browsed.secret(reading["url"])):
            return None
        return {"url": reading["url"], "title": reading["title"], "s": round(reading["s"], 1),
                "at": reading["at"], "id": reading["id"], "facts": reading["facts"] or {}}

    def _send(self, sent: dict | None) -> None:
        if sent:
            threading.Thread(target=self.visit, args=(sent,), name="mibo-browser", daemon=True).start()
