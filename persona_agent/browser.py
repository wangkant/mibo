"""The app's own browser on Windows: a link from the app, a chat card or the
pet's card opens inside the app window, in a pane with the conversation beside it.

The app page draws the pane's bar (browse.js) and keeps the space under it;
here a WebView2 of its own lies over that space, a child of the app window's
form that goes straight to the site. It is a place apart from the app page: no
bridge to Python, nothing of the page's token, only http and https, no
permissions, and cookies and storage in a WebView2 folder of its own that stays
between runs, so the person stays signed in. Minimizing it or going to Settings only
hides the pane: the page goes on, with its sound and its history, one press away.
Closing it ends its WebView2 processes: nothing of it runs while no page is open.
While the pane is in front the window is as wide as a site and the chat beside it
want, where the screen allows (`_room`). The page open last, until the pane is
closed, each site's own zoom (outside private mode) and the size the person gave
the window while a site was in front are kept in kept.json beside that folder.

Every page is timed while the window is in front, shown and in use. When it is
left it goes to `visit` (browsed.py keeps the row; a find's time also goes to
the recommender), unless the bar's private switch is on or the page is a
sign-in or payment page.

`Reader` reads one address with the person's session, out of sight: a second
WebView2 on the same folder, made for the read and gone after.
"""
from __future__ import annotations

import contextlib
import ctypes
import json
import math
import re
import threading
import time
import webbrowser
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from . import browsed
from .storage import atomic_write_text

# Reading: no input for this long and the time stops counting.
IDLE_S = 60
# How often a page in front checks for that, and for a password field come late; nothing ticks otherwise.
TICK_MS = 20000
# Shorter than this is a glance, not a reading.
READ_MIN_S = 2
# The page's own canvas (app.css), shown before the site draws: light, dark.
CANVAS = ("#fcfcfd", "#202022")
# The browser's own language, fixed when it first starts (see language()).
_LANGUAGE: list[str] = []


def language() -> str:
    """The language of the browser's own prompts (Save password?): the app's as the browser first starts, not the
    system's. Every WebView2 on the pane's folder asks for this same one, or the later ones fail to start."""
    if not _LANGUAGE:
        from . import i18n
        code = i18n.lang()
        _LANGUAGE.append({"zh": "zh-CN"}.get(code, code))
    return _LANGUAGE[0]
ACTIONS = ("back", "forward", "reload", "stop", "system", "close", "private", "hide", "return", "mute", "loaded",
           "op_stop", "op_take", "fit")
# Beside the pane's WebView2 folder: the page open last ({"url", "title"}), each site's own zoom, and the window's
# size while a site is in front, once the person set one ([wide, high] in px at 100 %).
KEPT = "kept.json"
# Fit to width (the bar's switch, off until pressed): a pane narrower than this many CSS px zooms the site out
# until its layout gets this width, down to FIT_MIN, below which text stops being easy to read and the site lays
# out narrower instead.
FIT_WIDTH = 1200
FIT_MIN = 0.67
# What a page read for a tool gives: its text clipped to this, and a list's rows.
TEXT_MAX = 6000
ROWS_MAX = 40
# Reading out of sight: how long a page may take.
READ_WITHIN_S = 25.0
# A feed read in the background (Feeds): how often it is looked at, how often one site's is read, how many reads
# a day, how many of its rows are kept, and the walls that turn it off.
FEED_LOOK_S = 60.0
FEED_EVERY_S = 30 * 60.0
FEED_DAY_MAX = 24
FEED_ROWS = 20
FEED_STOPS = ("verification", "sign_in", "sign_in_overlay", "robots")
SECRET_SCRIPT = "!!document.querySelector('input[type=password]')"
# A DevTools call to the page: how long it may take. While the character operates, how often the person's own
# input in the pane is looked for (it pauses the run), and how long a page may take to come up for it.
CDP_S = 20.0
WATCH_MS = 250
OPEN_WITHIN_S = 20.0
VK_ESCAPE = 0x1B
# The steps of a run the column beside the page lists (browse.js), the ends after which the page is the person's
# until they say to go on, and for how long a run going on from one of those keeps its steps.
STEPS_KEPT = 40
THEIRS = ("handover", "asked", "paused")
GO_ON_S = 30 * 60.0


def _idle_s() -> float:
    """How long since the last key or pointer input anywhere on this computer."""
    from ctypes import wintypes

    class LastInput(ctypes.Structure):
        _fields_ = [("size", wintypes.UINT), ("time", wintypes.DWORD)]

    info = LastInput()
    info.size = ctypes.sizeof(LastInput)
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info))
    return ((ctypes.windll.kernel32.GetTickCount() - info.time) & 0xFFFFFFFF) / 1000


def _last_input_tick() -> int:
    """When Windows last saw a key or pointer input (GetLastInputInfo), in its own ticks."""
    from ctypes import wintypes

    class LastInput(ctypes.Structure):
        _fields_ = [("size", wintypes.UINT), ("time", wintypes.DWORD)]

    info = LastInput()
    info.size = ctypes.sizeof(LastInput)
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info))
    return int(info.time)


def _dark() -> bool:
    import winreg
    with contextlib.suppress(OSError):
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
    return False


def web_address(address: str) -> bool:
    return urlsplit(str(address)).scheme in ("http", "https")


def handed(status: str, note: str) -> str:
    """Why a run handed the page to the person, for the column to say what they should do: "secret:<field>",
    a wall's kind (verification, sign_in, ...), "drawn" or "stuck"; "" for any other end."""
    if status != "handover":
        return ""
    secret = re.search(r"needs their own (.+?) first", note)
    if secret:
        return f"secret:{secret.group(1)[:40]}"
    wall = re.search(r"shows a (\w+) wall", note)
    if wall:
        return wall.group(1)
    return "drawn" if "almost nothing to work with" in note or "drawn" in note else "stuck"


def tell_script(state: dict) -> str:
    """What the app page runs to show `state` in the pane's bar (browse.js)."""
    return f"window.paBrowse && paBrowse({json.dumps(state)})"


def facts_script() -> str:
    """The generic reader (web/reader.js) over the page as it is: its rows, its content, its own facts."""
    from .web.read import READER
    return f"({READER})({{}})"


def page_of(url: str, data, rows: list | None = None, start: int = 0) -> dict:
    """What a read page gives: title, declared facts and readable text, as roam.py reads them, and for a list
    its rows (title, link, author, time, counts). The text is the TEXT_MAX characters from `start`; where the
    page has more, "of" says how many there are in all."""
    from .roam import facts_from
    data = data if isinstance(data, dict) else {}
    facts = facts_from(data, url)
    listed = [{k: str(row.get(k) or "")[:300] for k in ("title", "link", "author", "time") if row.get(k)}
              | ({"counts": row["counts"]} if isinstance(row.get("counts"), dict) and row["counts"] else {})
              for row in (data.get("rows") if rows is None else rows) or [] if isinstance(row, dict)]
    text = facts.get("text") or ""
    return {"url": url, "title": facts.get("title") or str(data.get("title") or ""),
            "site": facts.get("site", ""), "kind": facts.get("kind", ""), "author": facts.get("author", ""),
            "published": facts.get("published", ""), "description": facts.get("description", ""),
            "text": text[start:start + TEXT_MAX], **({"from": start, "of": len(text)} if len(text) > TEXT_MAX else {}),
            **({"rows": [row for row in listed if row.get("title")][:ROWS_MAX]}
               if data.get("kind") == "list" else {})}


def _run(core, script: str):
    """Run `script` in a page, on the form's thread; its answer is heard there too (as pywebview does)."""
    from System import Action, String
    from System.Threading.Tasks import Task, TaskScheduler

    done = threading.Event()
    heard: list = []

    def finished(task) -> None:
        with contextlib.suppress(Exception):
            heard.append(task.Result)
        done.set()
    core.ExecuteScriptAsync(script).ContinueWith(Action[Task[String]](finished),
                                                  TaskScheduler.FromCurrentSynchronizationContext())
    return done, heard


def _wait(asked, seconds: float):
    """What a script run by `_run` answered, from a thread other than the form's; None when it took too long."""
    if not asked:
        return None
    done, heard = asked
    return heard[0] if done.wait(seconds) and heard else None


def _devtools(core, method: str, params: dict, box: dict, done: threading.Event) -> None:
    """One DevTools protocol call in the page, in process (no debugging port); started on the form's thread,
    its answer heard on a pool thread, so a thread waiting for it never holds the form."""
    from System import Action, String
    from System.Threading.Tasks import Task

    def finished(task) -> None:
        try:
            box["result"] = json.loads(str(task.Result))
        except Exception:
            inner = task.Exception.InnerException if task.Exception is not None else None
            box["error"] = str(inner.Message if inner is not None else "the call failed")
        done.set()
    box["handler"] = finished
    core.CallDevToolsProtocolMethodAsync(method, json.dumps(params)).ContinueWith(
        Action[Task[String]](finished))


def _call(ui: Callable, core_of: Callable, method: str, params: dict, timeout: float) -> dict:
    """`method` sent to the page `core_of()` gives (on the form's thread), from a thread other than the
    form's; a suspended page is resumed first. Raises RuntimeError with the page's own reason."""
    box: dict = {}
    done = threading.Event()

    def start() -> None:
        core = core_of()
        if core is None:
            box["error"] = "the page is closed"
            done.set()
            return
        if core.IsSuspended:
            core.Resume()
        _devtools(core, method, params, box, done)
    ui(start)
    if not done.wait(timeout):
        raise RuntimeError(f"Timed out: {method}")
    if "error" in box:
        raise RuntimeError(box["error"])
    return box["result"]


class Pane:
    """The site's WebView in the app window's `form`, made when a link opens and
    gone again when the pane closes. Its work runs on the form's thread, through
    `ui`. `tell(state)` hands the page what its bar shows, `find` names the find
    at an address ("" for none; called on a thread of its own), and `visit(row)`
    takes a page left ({"url", "title", "s", "at", "id", "facts"}; on a thread of its
    own). `full(core, on)` makes the window full screen for a video, or puts it
    back; it answers with `cover`."""

    def __init__(self, folder: Path, form, *, ui: Callable[[Callable[[], None]], None],
                 tell: Callable[[dict], None], find: Callable[[str], str], visit: Callable[[dict], None],
                 full: Callable[[object, bool], None]):
        self.folder = Path(folder)
        self.form = form
        self.ui = ui
        self.tell = tell
        self.find = find
        self.visit = visit
        self.full = full
        self._view = self._core = None
        # Where to go once the WebView is ready, the space the page keeps for it (form px), and what of the app page
        # lies over it (the chat in a narrow window, the address bar's suggestions): rects in its CSS px.
        self._pending = ""
        self._box = None
        self._cuts: list = []
        # While the pane is in front: the window as it stood for the chat, where it was put, and the size given it.
        self._roomed: dict | None = None
        # The page being read: its address, title, find id once known, seconds counted and since when
        # (monotonic), whether it showed a password field, and its facts once read long enough.
        self._reading: dict | None = None
        self._quieted = False
        self._full = False
        # The bar's private switch: nothing is kept while it is on. Hidden: the person minimized the pane or went to
        # Settings, and the page goes on behind the chip that brings it back.
        self.private = False
        self._hidden = False
        self._timer = None
        # .NET holds no reference to these.
        self._handlers = (lambda s, a: self._count(), lambda s, a: self._pause(), self._resized, self._tick,
                          self._resize_end)
        # While the character operates the page: the task, the step it is on, why it must stop ("stopped",
        # "paused" when the person moved in the pane), and the input watch that finds the person's own moves
        # (the run's own clicks go through DevTools, not Windows).
        self.op: dict | None = None
        self._op_last: dict | None = None
        self._op_timer = None
        self._op_seen = 0
        self._op_tick = lambda sender, args: self._input_tick()
        self._listeners: list = []
        self._loaded = threading.Event()
        # Zoom: the bar's 适应宽度 (fit to width, off until pressed), the app page's px per CSS px, the person's own
        # zoom per site (kept in KEPT; in private mode for this run only), the factor last set here, and what the
        # bar was told. KEPT also holds the page open last and the window's size with a site in front.
        self.fit = False
        self._scale = 1.0
        self._kept = self._read_kept()
        self._zoom_private: dict[str, float] = {}
        self._zoom_set = 0.0
        self._zoom_told: tuple = ()
        # Between a navigation's start and its end, WebView2 may bring back a zoom it remembers for the site.
        self._navigating = False
        self.ui(self._watch_form)

    # ---- what the app asks, from any thread

    def open(self, address: str) -> None:
        self.ui(lambda: self._open(address))

    def place(self, box: list, scale: float, cuts: list) -> None:
        self.ui(lambda: self._place(box, scale, cuts))

    def room(self, wide: float, scale: float) -> None:
        self.ui(lambda: self._room(wide, scale))

    def rescale(self, factor: float) -> None:
        """On the form's thread: the window came onto a monitor of another scale (`factor` times the
        last). The page's CSS px stay as they were, so it may not say where the pane is again."""
        if self._box is not None:
            self._place(self._css, self._scale * factor, self._cuts)

    def do(self, action: str) -> None:
        self.ui(lambda: self._do(action))

    def quiet(self, on: bool) -> None:
        if self._view is not None:
            self.ui(lambda: self._quiet(on))

    def close(self) -> None:
        """The app is quitting: the page left is handed over now, while the page's server still answers. Its
        address stays kept, offered when the app starts again."""
        sent: list = []
        self.ui(lambda: sent.append(self._shut(forget=False)))
        if sent and sent[0]:
            with contextlib.suppress(Exception):
                self.visit(sent[0])

    def forget(self) -> None:
        """Browsing data cleared: the pane closes, and the page open last and every site's zoom are forgotten."""
        def drop() -> None:
            self._send(self._shut())
            self._kept["zoom"].clear()
            self._keep()
        self.ui(drop)

    # ---- on the form's thread

    def _watch_form(self) -> None:
        from System.Windows.Forms import Timer
        activated, deactivated, resized, tick, resize_end = self._handlers
        self.form.Activated += activated
        self.form.Deactivate += deactivated
        self.form.Resize += resized
        self.form.ResizeEnd += resize_end
        self._timer = Timer()
        self._timer.Interval = TICK_MS
        self._timer.Tick += tick

    def _begin(self, address: str) -> None:
        """A page begins to be read: the last one is handed over first."""
        self._send(self._finish())
        self._reading = {"url": address, "title": "", "id": "", "s": 0.0, "since": None, "begun": False,
                         "secret": self.private, "facts": None, "at": time.time()}
        reading = self._reading
        threading.Thread(target=self._look_up, args=(reading,), name="personagent-browser", daemon=True).start()

    def _open(self, address: str) -> None:
        self._begin(address)
        if self._core is None:
            self._pending = address
        else:
            self._core.Navigate(address)
        if self._quieted:
            self._quiet(False)
        if self._hidden:
            self._do("return")
        # The page shows the pane and says where it is (place); the WebView is made then.
        self.tell({"open": True, "url": address, "host": urlsplit(address).hostname or "", "title": "",
                   "back": False, "forward": False, "loading": True, "private": self.private})

    def _look_up(self, reading: dict) -> None:
        ident = self.find(reading["url"])
        if ident:
            self.ui(lambda: self._found(reading, ident))

    def _found(self, reading: dict, ident: str) -> None:
        if reading is self._reading:
            reading["id"] = ident

    def _place(self, box: list, scale: float, cuts: list) -> None:
        """The page's pane moved or changed size, or part of the app page came over it (`cuts`: [x, y, wide, high]
        in CSS px inside it): the WebView follows, made the first time."""
        from System.Drawing import Rectangle
        if not self._pending and self._view is None:
            return
        # The app page fills the form; its CSS px times its device pixel ratio make form px.
        origin = self.form.browser.webview.Location
        x, y, wide, high = (int(round(v * scale)) for v in box)
        self._box = Rectangle(origin.X + x, origin.Y + y, max(wide, 1), max(high, 1))
        self._css, self._scale, self._cuts = box, scale, cuts
        if self._view is None:
            self._make()
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
        to that once, within its monitor's work area, and never gets smaller; the size the person gave it while a
        site was in front (KEPT) is used instead of the page's. When the pane leaves the front the window takes
        back the size it had for the chat. Not while maximized or in full screen."""
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
        size = Size(min(max(form.Width, round(kept[0] * unit)), area.Width),
                    min(max(form.Height, round(kept[1] * unit)), area.Height))
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

    def _make(self) -> None:
        from Microsoft.Web.WebView2.WinForms import CoreWebView2CreationProperties, WebView2
        from System.Drawing import ColorTranslator

        view = WebView2()
        properties = CoreWebView2CreationProperties()
        properties.UserDataFolder = str(self.folder / "webview")
        # Private: an InPrivate profile, so no sign-in of the person's reaches the page and nothing of it stays.
        properties.IsInPrivateModeEnabled = self.private
        properties.Language = language()
        view.CreationProperties = properties
        view.DefaultBackgroundColor = ColorTranslator.FromHtml(CANVAS[_dark()])
        view.Bounds = self._box
        view.CoreWebView2InitializationCompleted += self._ready
        view.ZoomFactorChanged += self._zoomed
        view.KeyDown += self._key
        self.form.Controls.Add(view)
        view.BringToFront()
        self._view = view
        view.EnsureCoreWebView2Async(None)

    def _ready(self, sender, args) -> None:
        if not args.IsSuccess or self._view is None:
            return
        core = self._view.CoreWebView2
        settings = core.Settings
        # Nothing reaches Python from here, and nobody inspects the app through it.
        settings.IsWebMessageEnabled = False
        settings.AreHostObjectsAllowed = False
        settings.AreDevToolsEnabled = False
        settings.IsSwipeNavigationEnabled = True
        # The browser's own password saving and autofill, and each page looked at for a sign-in (signwatch.py).
        from . import signwatch
        signwatch.ready(self, core)
        core.NavigationStarting += self._starting
        core.NavigationCompleted += self._completed
        core.NewWindowRequested += self._new_window
        core.PermissionRequested += self._permission
        core.LaunchingExternalUriScheme += self._external
        core.DocumentTitleChanged += self._changed
        core.SourceChanged += self._changed
        core.HistoryChanged += self._changed
        core.ContainsFullScreenElementChanged += self._full_screen
        core.DownloadStarting += self._download
        core.IsDocumentPlayingAudioChanged += self._sound
        core.IsMutedChanged += self._sound
        self._core = core
        if self._pending:
            core.Navigate(self._pending)
            self._pending = ""
        self._count()

    def _starting(self, sender, args) -> None:
        """Only web addresses load: file:, about:, data: and every other scheme are refused."""
        from Microsoft.Web.WebView2.Core import CoreWebView2NavigationKind
        if not web_address(args.Uri):
            args.Cancel = True
            return
        self._navigating = True
        reading = self._reading
        # Leaving the page: a click on it, or back and forward. A redirect or a reload stays on it.
        if (reading is not None and reading["begun"] and not args.IsRedirected
                and args.NavigationKind != CoreWebView2NavigationKind.Reload
                and (args.IsUserInitiated or args.NavigationKind == CoreWebView2NavigationKind.BackOrForward)):
            self._send(self._finish())
        self._state(loading=True)

    def _completed(self, sender, args) -> None:
        self._loaded.set()
        if args.IsSuccess:
            source = str(self._core.Source)
            if self._reading is None:
                # A page come to from the last one.
                self._begin(source)
            reading = self._reading
            reading["url"], reading["begun"] = source, True
            self._check_secret(reading)
            self._count()
        # WebView2 brings back a zoom it remembers for the site as it navigates: the fit goes over it.
        self._navigating = False
        self._zoom()
        self._state(loading=False)

    def _check_secret(self, reading: dict) -> None:
        """A password field on the page makes it a sign-in page: never kept. Asked again on each tick."""
        task = _run(self._core, SECRET_SCRIPT)

        def heard() -> None:
            if _wait(task, 10) == "true":
                reading["secret"] = True
        threading.Thread(target=heard, name="personagent-browser", daemon=True).start()

    def _changed(self, sender, args) -> None:
        self._state()

    def _state(self, loading: bool | None = None) -> None:
        core = self._core
        source = str(core.Source)
        title = str(core.DocumentTitle or "").strip()
        if self._reading is not None and self._reading["url"] == source:
            self._reading["title"] = title
        state = {"url": source, "host": urlsplit(source).hostname or "", "title": title,
                 "back": bool(core.CanGoBack), "forward": bool(core.CanGoForward), "private": self.private}
        if loading is not None:
            state["loading"] = loading
        self.tell(state)
        self._keep_last(source, title)

    def _sound(self, sender, args) -> None:
        """The page began or stopped playing sound, or was muted: the bar and the chip show a speaker for it."""
        self.tell({"sound": bool(self._core.IsDocumentPlayingAudio), "muted": bool(self._core.IsMuted)})

    def _new_window(self, sender, args) -> None:
        """A new tab or window opens in this same view; only what the person clicked."""
        args.Handled = True
        if args.IsUserInitiated and web_address(args.Uri):
            self._send(self._finish())
            self._core.Navigate(args.Uri)

    def _permission(self, sender, args) -> None:
        """Camera, microphone, location, notifications and the rest: refused without asking."""
        from Microsoft.Web.WebView2.Core import CoreWebView2PermissionState
        args.State = CoreWebView2PermissionState.Deny

    def _download(self, sender, args) -> None:
        """A download while the character operates waits (a deferral) in op["downloads"] for the person's answer
        on a card (operate.Hands): saved to the download folder on yes, cancelled on no. Theirs go as ever."""
        if self.op is None:
            return
        deferral, operation = args.GetDeferral(), args.DownloadOperation

        def answer(yes: bool) -> None:
            def finish() -> None:
                args.Cancel = not yes
                deferral.Complete()
            self.ui(finish)
        self.op.setdefault("downloads", []).append({
            "url": str(operation.Uri), "path": str(args.ResultFilePath),
            "bytes": int(operation.TotalBytesToReceive or 0), "answer": answer})

    def _external(self, sender, args) -> None:
        """mailto:, a program's own scheme: nothing on this computer is started from a site."""
        args.Cancel = True

    def _full_screen(self, sender, args) -> None:
        """A video's full screen is the whole monitor's: the window covers it (`full`, then `cover`)."""
        self.full(self._core, bool(self._core.ContainsFullScreenElement))

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

    def _do(self, action: str) -> None:
        """The bar's buttons, from the page."""
        core = self._core
        if action == "close":
            self._send(self._shut())
        elif action == "system":
            # Read elsewhere from here on: the pane has done its part.
            target = str(core.Source) if core is not None else self._pending
            if web_address(target):
                threading.Thread(target=webbrowser.open, args=(target,), name="personagent-browser",
                                 daemon=True).start()
            self._send(self._shut())
        elif action == "private":
            # From now on nothing is kept, the page in front included; off again, the next page counts.
            self.private = not self.private
            if self.private and self._reading is not None:
                self._reading["secret"] = True
            if self._view is not None:
                self._remake()
            self.tell({"private": self.private})
        elif action == "fit":
            # The bar's 适应宽度 / 100%: the site fitted to the pane's width, or at its own size.
            self.fit = not self.fit
            self._zoom(show=True)
        elif action in ("op_stop", "op_take"):
            # The bar's 停止 (or Esc) and 我来接手: the run stops at its next step.
            if self.op is not None:
                self.op["held"] = "stopped" if action == "op_stop" else "paused"
                self._tell_op()
        elif action in ("hide", "return"):
            # 最小化 or Settings: the page goes on behind the chip, with its sound and its history; "return"
            # brings it back as it was. A run under way pauses: the page is out of sight.
            self._hidden = action == "hide"
            if self._view is not None:
                self._view.Visible = not self._hidden and not self._quieted
            if self._hidden:
                self._pause()
                if self.op is not None and not self.op.get("held"):
                    self.op["held"] = "paused"
                    self._tell_op()
            else:
                self._count()
            self.tell({"hidden": self._hidden})
        elif action == "loaded":
            # The app page loaded again: a page still open waits behind its chip; with none, the page open last
            # is offered.
            if core is None:
                if self._view is None and self._kept["last"]:
                    self.tell({"kept": self._kept["last"]})
                return
            self._state()
            self._sound(None, None)
            self._zoom_told = ()
            self._zoom()
            self._do("hide")
        elif core is None:
            return
        elif action == "mute":
            core.IsMuted = not core.IsMuted
        elif action == "back" and core.CanGoBack:
            self._send(self._finish())
            core.GoBack()
        elif action == "forward" and core.CanGoForward:
            self._send(self._finish())
            core.GoForward()
        elif action == "reload":
            core.Reload()
        elif action == "stop":
            core.Stop()

    # ---- zoom: the person's own for the site, as the browser steps it; over the fit to the pane's width when on

    def _fit_factor(self) -> float:
        if not self.fit or self._box is None:
            return 1.0
        # The site's CSS px at zoom 1 are the monitor's, whatever the app page's own zoom.
        wide = self._box.Width / self.form._scale
        return 1.0 if wide >= FIT_WIDTH else max(FIT_MIN, wide / FIT_WIDTH)

    def _host(self) -> str:
        return (urlsplit(str(self._core.Source)).hostname or "") if self._core is not None else ""

    def _zoom(self, show: bool = False) -> None:
        """Set the site's zoom: 1 in full screen, else the fit times the person's own for this site."""
        view = self._view
        if view is None:
            return
        target = 1.0 if self._full else self._fit_factor() * self._zooms().get(self._host(), 1.0)
        # Down to the next thousandth: rounding up would leave the site a pixel short of the width it needs.
        target = math.floor(min(5.0, max(0.25, target)) * 1000) / 1000
        self._zoom_set = target
        if abs(float(view.ZoomFactor) - target) > 0.0005:
            view.ZoomFactor = target
        told = (round(target * 100), self.fit)
        if show or told != self._zoom_told:
            self._zoom_told = told
            self.tell({"zoom": told[0], "fit": self.fit, "zoom_show": show})

    def _zoomed(self, sender, args) -> None:
        """The zoom changed. Set here: nothing to do. While a page loads (WebView2 gives a new page the zoom set
        last) or in full screen: ours goes over it. Otherwise the person's Ctrl +/- or Ctrl wheel, the browser's
        own steps: kept for the site (over the fit, when that is on; Ctrl 0 comes through _key)."""
        view = self._view
        if view is None:
            return
        now = float(view.ZoomFactor)
        if abs(now - self._zoom_set) <= 0.0005:
            return
        if self._full or self._navigating:
            self._zoom()
            return
        host, zooms = self._host(), self._zooms()
        own = round(now / self._fit_factor(), 3)
        if abs(own - 1.0) < 0.005:
            zooms.pop(host, None)
        else:
            zooms[host] = own
        self._zoom(show=True)
        if not self.private:
            self._keep()

    def _key(self, sender, args) -> None:
        """Ctrl L in the page: to the bar's address, as in any browser. Ctrl 0 (WebView2 may leave the zoom as it
        is): back to the fit for the site."""
        from System.Windows.Forms import Keys
        if args.Control and args.KeyCode == Keys.L:
            self.form.browser.webview.Focus()
            self.tell({"focus": "address"})
        elif args.Control and args.KeyCode in (Keys.D0, Keys.NumPad0) and self._zooms().pop(self._host(), None):
            self._zoom(show=True)
            if not self.private:
                self._keep()

    def _zooms(self) -> dict:
        """The person's own zoom per site: kept, or in private mode for this run only."""
        return self._zoom_private if self.private else self._kept["zoom"]

    # ---- kept between runs (KEPT)

    def _read_kept(self) -> dict:
        try:
            kept = json.loads((self.folder / KEPT).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            kept = {}
        return {"zoom": kept.get("zoom") or {}, "last": kept.get("last") or {}, "size": kept.get("size") or []}

    def _keep(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self.folder / KEPT, json.dumps(self._kept, ensure_ascii=False))

    def _keep_last(self, url: str, title: str) -> None:
        """The page open now, offered again after a restart; never in private mode or a sign-in or payment page."""
        last = {"url": url, "title": title[:200]}
        if self.private or not web_address(url) or browsed.secret(url) or last == self._kept["last"]:
            return
        self._kept["last"] = last
        self._keep()

    # ---- the character operating the page (web/operate.py), from a thread other than the form's

    def cdp(self, method: str, params: dict | None = None, timeout: float = CDP_S) -> dict:
        """One DevTools protocol call in the page open now."""
        return _call(self.ui, lambda: self._core, method, params or {}, timeout)

    def listen(self, name: str, handler: Callable[[dict], None]) -> None:
        """`handler(params)` on each DevTools event `name` of the page open now."""
        def on(sender, args) -> None:
            with contextlib.suppress(ValueError):
                handler(json.loads(str(args.ParameterObjectAsJson)))

        def add() -> None:
            if self._core is not None:
                self._core.GetDevToolsProtocolEventReceiver(name).DevToolsProtocolEventReceived += on
                self._listeners.append(on)
        self.ui(add)

    def address(self) -> str:
        found: list = []
        self.ui(lambda: found.append(str(self._core.Source) if self._core is not None else self._pending))
        return found[0] if found else ""

    def bar_address(self) -> str:
        """The address its bar shows: the page open, or the one on its way while a slow page has not answered."""
        current = self.address()
        return current if web_address(current) else (self._reading or {}).get("url", "")

    def ready(self, address: str = "") -> bool:
        """The pane open and in front with a page loaded: on `address` when it is given and the page open is
        on another site, or none is open. False when no page came up in time."""
        current = self.address()
        if address and (not web_address(current) or browsed.site_of(urlsplit(address).hostname or "")
                        != browsed.site_of(urlsplit(current).hostname or "")):
            self.open(address)
        elif not web_address(current):
            return False
        else:
            self.ui(lambda: (self._quiet(False), self._do("return")))
        began = time.monotonic()
        while time.monotonic() - began < OPEN_WITHIN_S:
            if self._core is not None and web_address(self.address()):
                with contextlib.suppress(RuntimeError):
                    state = self.cdp("Runtime.evaluate", {"expression": "document.readyState",
                                                          "returnByValue": True}, timeout=5)
                    if (state.get("result") or {}).get("value") in ("interactive", "complete"):
                        return True
            time.sleep(0.3)
        return False

    def operate(self, task: str, go_on: bool = False) -> None:
        """A run begins: the column beside the page shows it, and the person's moves in the pane pause it. Going
        on from a run that left the page to the person, the column keeps what was asked and the steps so far."""
        last = self._op_last
        if not (go_on and last and last["end"] in THEIRS and time.monotonic() - last["at"] < GO_ON_S):
            last = None
        self.op = {"task": last["task"] if last else task[:200], "step": 0, "note": "", "held": "", "end": "",
                   "why": "", "steps": last["steps"] if last else [], "card": None}
        with contextlib.suppress(RuntimeError):
            self.cdp("Page.enable")
        self.ui(self._watch_input)
        self._tell_op()

    def op_step(self, n: int, note: str) -> None:
        if self.op is not None:
            self.op.update(step=n, note=note[:120])
            self._tell_op()

    def op_said(self, text: str) -> None:
        """The step about to happen, in the person's words: the one before it is done. The same step again
        (another scroll) counts up instead of making a new line."""
        op = self.op
        if op is None or not text:
            return
        steps = op["steps"]
        last = steps[-1] if steps else None
        if last and last["state"] == "doing":
            last["state"] = "done"
        if (last and last["state"] == "done" and last["text"] == text[:120] and not last.get("why")
                and last.get("note", "") == op["note"]):
            last.update(state="doing", n=last.get("n", 1) + 1)
        else:
            # With what the step is for (the loop's note, op_step), which the column shows over it.
            steps.append({"text": text[:120], "state": "doing", **({"note": op["note"]} if op["note"] else {})})
            del steps[:-STEPS_KEPT]
        self._tell_op()

    def op_result(self, state: str, why: str = "") -> None:
        """How the step under way came out: "done", or "failed" with why in the person's words."""
        op = self.op
        if op is None or not op["steps"] or op["steps"][-1]["state"] != "doing":
            return
        op["steps"][-1].update(state=state, **({"why": why} if why else {}))
        self._tell_op()

    def op_card(self, card: dict, text: str) -> None:
        """A card waits on the person's press, beside the page: the column shows it, and `text` as the step."""
        op = self.op
        if op is None:
            return
        if op["steps"] and op["steps"][-1]["state"] == "doing":
            op["steps"][-1]["state"] = "done"
        op["steps"].append({"text": text[:160], "state": "waiting", "card": True,
                            **({"note": op["note"]} if op["note"] else {})})
        op["card"] = card
        self._tell_op()

    def op_answered(self, state: str, text: str) -> None:
        """The card is answered (or gone unanswered): its step says how, and the card goes."""
        op = self.op
        if op is None:
            return
        for step in reversed(op["steps"]):
            if step["state"] == "waiting":
                step.update(state=state, text=text[:160])
                break
        op["card"] = None
        self._tell_op()

    def op_end(self, status: str, note: str, unfinished: str = "") -> None:
        """The run ended: the column says how, and stays until the person closes it. A step it never finished
        says `unfinished`."""
        op = self.op
        if op is None:
            return
        self.ui(self._unwatch_input)
        for step in op["steps"]:
            if step["state"] in ("doing", "waiting"):
                step.update(state="done" if status == "done" else "stopped", why="" if status == "done" else unfinished)
        op.update(end=status, note=note[:300], why=handed(status, note), card=None)
        self._tell_op()
        self._op_last = {**op, "at": time.monotonic()}
        self.op = None

    def op_steps(self) -> list:
        """The steps of the run under way, else of the last one."""
        return list((self.op or self._op_last or {}).get("steps") or [])

    def _tell_op(self) -> None:
        op = self.op
        self.tell({"operating": None if op is None else {
            k: op.get(k) for k in ("task", "step", "note", "held", "end", "why", "steps", "card", "wait")}})

    def _watch_input(self) -> None:
        from System.Windows.Forms import Timer
        self._unwatch_input()
        timer = Timer()
        timer.Interval = WATCH_MS
        self._op_seen = _last_input_tick()
        timer.Tick += self._op_tick
        timer.Start()
        self._op_timer = timer

    def _unwatch_input(self) -> None:
        if self._op_timer is not None:
            self._op_timer.Stop()
            self._op_timer.Dispose()
            self._op_timer = None

    def _input_tick(self) -> None:
        """The person's own click or key in the pane (a pointer only passing over it does not count): Esc
        stops the run, anything else pauses it."""
        from System.Drawing import Rectangle
        from System.Windows.Forms import Cursor
        seen, where = _last_input_tick(), (Cursor.Position.X, Cursor.Position.Y)
        moved, self._op_seen = seen != self._op_seen, seen
        before, self._op_where = getattr(self, "_op_where", where), where
        if not moved or self.op is None or self._view is None or self.op.get("held") or not self._view.Visible:
            return
        keys = ctypes.windll.user32.GetAsyncKeyState
        box = self._view.RectangleToScreen(Rectangle(0, 0, self._view.Width, self._view.Height))
        clicked = box.Contains(Cursor.Position) and any(keys(button) & 0x8001 for button in (0x01, 0x02, 0x04))
        typed = self._view.ContainsFocus and where == before
        if not (clicked or typed):
            return
        # Waiting for their sign-in, the page is theirs to type in: only Esc stops the run.
        if self.op.get("wait") and not keys(VK_ESCAPE) & 0x8001:
            return
        self.op["held"] = "stopped" if keys(VK_ESCAPE) & 0x8001 else "paused"
        self._tell_op()

    def _remake(self) -> None:
        """The WebView made again on the same page, in the profile the private switch says."""
        address = str(self._core.Source) if self._core is not None else self._pending
        view, self._view, self._core = self._view, None, None
        self.form.Controls.Remove(view)
        view.Dispose()
        self._pending = address if web_address(address) else ""
        self._make()

    def _shut(self, forget: bool = True) -> dict | None:
        """The pane closes: the WebView and its processes go, and the reading ends. Closed by the person, the page
        open last is forgotten too; the app quitting keeps it, to offer when the app starts again."""
        sent = self._finish()
        if self._full:
            self.full(self._core, False)
        if self._view is not None:
            self.form.Controls.Remove(self._view)
            self._view.Dispose()
        self._view = self._core = self._box = None
        self._pending = ""
        self._quieted = self._full = self._hidden = False
        if forget and self._kept["last"]:
            self._kept["last"] = {}
            self._keep()
        self.tell({"open": False})
        return sent

    def _quiet(self, on: bool) -> None:
        """Quiet hides the pane's WebView with the pet and suspends its page; it comes back as it was."""
        from Microsoft.Web.WebView2.Core import CoreWebView2MemoryUsageTargetLevel
        if self._view is None or on == self._quieted:
            return
        self._quieted = on
        if on:
            self._pause()
            self._view.Visible = False
            if self._core is not None:
                self._core.MemoryUsageTargetLevel = CoreWebView2MemoryUsageTargetLevel.Low
                self._core.TrySuspendAsync()
        else:
            if self._core is not None:
                self._core.MemoryUsageTargetLevel = CoreWebView2MemoryUsageTargetLevel.Normal
            self._view.Visible = not self._hidden
            self._count()

    def _resized(self, sender, args) -> None:
        from System.Windows.Forms import FormWindowState
        if self.form.WindowState == FormWindowState.Minimized:
            self._pause()
        else:
            self._count()

    # ---- the reading

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
            task = _run(self._core, facts_script())

            def heard() -> None:
                raw = _wait(task, 10)
                with contextlib.suppress(ValueError, TypeError):
                    reading["facts"] = page_of(reading["url"], json.loads(raw))
            threading.Thread(target=heard, name="personagent-browser", daemon=True).start()

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
        if (reading is None or reading["s"] < READ_MIN_S and not reading["id"] or reading["secret"] or self.private
                or not web_address(reading["url"]) or browsed.secret(reading["url"])):
            return None
        return {"url": reading["url"], "title": reading["title"], "s": round(reading["s"], 1),
                "at": reading["at"], "id": reading["id"], "facts": reading["facts"] or {}}

    def _send(self, sent: dict | None) -> None:
        if sent:
            threading.Thread(target=self.visit, args=(sent,), name="personagent-browser", daemon=True).start()


class Reader:
    """Reads with the person's session (the pane's WebView2 folder), out of sight: a hidden WebView2 in
    `form`, made for one site and disposed after (web/tabs.HiddenTab reads through it). Read only: it goes
    only to that site's addresses, and requests to other sites, and any but GET, are refused, so the
    person's cookies go to that site alone; a move to another site (a sign-in elsewhere) stops the read.
    Pace (browsed.Pace): one read at a time, a pause between, a day's cap per site, and a site whose check
    or sign-in wall showed is not read again for a while. Cookies and storage are never read out: only the
    page's text leaves."""

    def __init__(self, folder: Path, form, *, ui: Callable[[Callable[[], None]], None], pace: browsed.Pace):
        self.folder = Path(folder)
        self.form = form
        self.ui = ui
        self.pace = pace

    def read(self, url: str, screens: int = 0, runtime: Path | None = None, background: bool = False,
             start: int = 0) -> dict:
        """{"url", "title", "site", "kind", "author", "published", "description", "text"} (and "rows" for a
        list, `screens` more screens scrolled; the text from character `start`, with "from" and "of" where the
        page has more than one read gives), or {"error": why} with why one of not_web, sign_in_page,
        wall, host_day_cap, failed, or the wall met (verification, sign_in, sign_in_overlay, error, dead, empty,
        robots for a `background` read robots.txt refuses)."""
        import asyncio

        from .web import read as reading
        from .web.tabs import HiddenTab
        with self.pace.lock:
            refused = self.pace.refuse(url)
            if refused:
                return {"error": refused}
            self.pace.wait()
            hidden = _Hidden(self, url)
            try:
                if not hidden.made.wait(READ_WITHIN_S) or hidden.core is None:
                    page = reading.Page(url, wall="failed")
                else:
                    page = asyncio.run(reading.read(HiddenTab(hidden), url, screens=screens, runtime=runtime,
                                                    background=background, mode="pane"))
            finally:
                hidden.close()
            wall = "sign_in" if hidden.left else page.wall
            self.pace.done(url, wall if wall in ("verification", "sign_in", "sign_in_overlay") else "")
            if wall:
                return {"error": wall}
            return page_of(page.url, page.data, page.rows, start)


class Feeds:
    """The person's own feed on a site, read in the background, only where they turned it on in Settings
    (the card's "feed": {on, url, day, n, at, stopped}): at most every FEED_EVERY_S and FEED_DAY_MAX a day a
    site, through the Reader (its pace, robots.txt honoured), read only. A check or a sign-in wall turns the
    site's reading off until the person turns it on again. The rows go to the library as finds."""

    def __init__(self, reader: Reader, runtime: Path, *, shared: Callable[[], bool]):
        self.reader = reader
        self.runtime = Path(runtime)
        self.shared = shared
        self.stop = threading.Event()
        threading.Thread(target=self._run, name="personagent-feeds", daemon=True).start()

    def _run(self) -> None:
        while not self.stop.wait(FEED_LOOK_S):
            for key, feed in feeds_on(self.runtime).items():
                if self.stop.is_set() or not self.shared():
                    break
                today = time.strftime("%Y-%m-%d")
                n = feed.get("n", 0) if feed.get("day") == today else 0
                if n >= FEED_DAY_MAX or time.time() - float(feed.get("at") or 0) < FEED_EVERY_S:
                    continue
                page = self.reader.read(feed["url"], screens=1, runtime=self.runtime, background=True)
                error = page.get("error", "")

                def note(card: dict, error=error, n=n, today=today) -> None:
                    kept = card.setdefault("feed", {})
                    kept.update(at=time.time(), day=today, n=n + 1, last=error or "ok")
                    if error in FEED_STOPS:
                        kept.update(on=False, stopped=error)
                from .web import sites
                sites._change(self.runtime, key, note)
                if not error:
                    keep_finds(self.runtime, key, page.get("rows") or [])


def feeds_on(runtime: Path) -> dict:
    """{site key: its feed} for the sites whose background reading the person turned on."""
    from .web import sites
    return {key: card["feed"] for key, card in sites.load(runtime).items()
            if isinstance(card, dict) and isinstance(card.get("feed"), dict) and card["feed"].get("on")
            and web_address(card["feed"].get("url", ""))}


def keep_finds(runtime: Path, key: str, rows: list) -> int:
    """A feed's rows as library finds of that site (source "feed <site>"); how many were new."""
    from .library import Item, Library, item_id
    from .roam import site_name
    from .web import sites
    library, new = Library(runtime), 0
    for row in rows[:FEED_ROWS]:
        link = str(row.get("link") or "")
        if not row.get("title") or not web_address(link) or sites.key_of(link) != key or browsed.secret(link):
            continue
        if library.get(item_id(link)) is None:
            library.add(Item(url=link, site=site_name(link), kind="post", title=str(row["title"])[:300],
                             author=str(row.get("author") or "")[:200], source=f"feed {key}"))
            new += 1
    return new


class _Hidden:
    """One hidden WebView2 for one site, as HiddenTab drives it: `goto`, `cdp`, `address`, `close`, each
    from a thread other than the form's."""

    def __init__(self, reader: Reader, url: str):
        self.reader = reader
        self.site = browsed.site_of(urlsplit(url).hostname or "")
        self.view = self.core = None
        self.made = threading.Event()
        self.loaded = threading.Event()
        # Sent to another site (a sign-in elsewhere): the read stops there.
        self.left = ""
        reader.ui(self._make)

    def _make(self) -> None:
        from Microsoft.Web.WebView2.WinForms import CoreWebView2CreationProperties, WebView2
        from System.Drawing import Rectangle

        view = WebView2()
        properties = CoreWebView2CreationProperties()
        properties.UserDataFolder = str(self.reader.folder / "webview")
        properties.Language = language()
        view.CreationProperties = properties
        view.Visible = False
        view.Bounds = Rectangle(0, 0, 1280, 900)
        self.view = view
        # .NET holds no reference to these.
        self._handlers = (self._ready, self._requested, self._starting, self._completed, self._refuse,
                          self._deny, self._cancel)
        view.CoreWebView2InitializationCompleted += self._ready
        self.reader.form.Controls.Add(view)
        view.SendToBack()
        view.EnsureCoreWebView2Async(None)

    def _ready(self, sender, args) -> None:
        if not args.IsSuccess or self.view is None:
            self.made.set()
            return
        from Microsoft.Web.WebView2.Core import CoreWebView2WebResourceContext
        core = self.view.CoreWebView2
        settings = core.Settings
        settings.IsWebMessageEnabled = False
        settings.AreHostObjectsAllowed = False
        settings.AreDevToolsEnabled = False
        settings.AreDefaultScriptDialogsEnabled = False
        settings.AreDefaultContextMenusEnabled = False
        settings.IsStatusBarEnabled = False
        core.IsMuted = True
        core.AddWebResourceRequestedFilter("*", CoreWebView2WebResourceContext.All)
        core.WebResourceRequested += self._requested
        core.NavigationStarting += self._starting
        core.NavigationCompleted += self._completed
        core.NewWindowRequested += self._refuse
        core.PermissionRequested += self._deny
        core.LaunchingExternalUriScheme += self._cancel
        core.DownloadStarting += self._cancel
        self.core = core
        self.made.set()

    def _requested(self, sender, args) -> None:
        # Only the site asked for, and only reading: nothing else goes anywhere with the cookies.
        request = args.Request
        address = str(request.Uri)
        if (str(request.Method).upper() != "GET" or not web_address(address)
                or browsed.site_of(urlsplit(address).hostname or "") != self.site):
            args.Response = sender.Environment.CreateWebResourceResponse(None, 403, "Blocked", "")

    def _starting(self, sender, args) -> None:
        address = str(args.Uri)
        if not web_address(address):
            args.Cancel = True
            return
        if browsed.site_of(urlsplit(address).hostname or "") != self.site or browsed.secret(address):
            self.left = address
            args.Cancel = True
            self.loaded.set()

    def _completed(self, sender, args) -> None:
        self.loaded.set()

    def _refuse(self, sender, args) -> None:
        args.Handled = True

    def _deny(self, sender, args) -> None:
        from Microsoft.Web.WebView2.Core import CoreWebView2PermissionState
        args.State = CoreWebView2PermissionState.Deny

    def _cancel(self, sender, args) -> None:
        args.Cancel = True

    def goto(self, url: str, timeout: float = READ_WITHIN_S) -> str:
        """Go to `url` of this site and wait for it; the address where it ended (the other site's when the
        read was sent away)."""
        from .web.tabs import TabError
        if browsed.site_of(urlsplit(url).hostname or "") != self.site:
            raise TabError("another site than the one this read is for")
        self.loaded.clear()
        self.reader.ui(lambda: self.core.Navigate(url))
        if not self.loaded.wait(timeout):
            raise TabError("timeout")
        return self.left or self.address()

    def address(self) -> str:
        found: list = []
        self.reader.ui(lambda: found.append(str(self.core.Source) if self.core is not None else ""))
        return found[0] if found else ""

    def cdp(self, method: str, params: dict) -> dict:
        return _call(self.reader.ui, lambda: self.core, method, params, CDP_S)

    def close(self) -> None:
        def drop() -> None:
            view, self.view, self.core = self.view, None, None
            if view is not None:
                self.reader.form.Controls.Remove(view)
                view.Dispose()
        self.reader.ui(drop)
