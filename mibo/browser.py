"""The app's own browser on Windows: a link from the app, a chat card or the
pet's card opens inside the app window, in a pane with the conversation beside it.

The app page draws the pane's bar (browse.js) and keeps the space under it;
here a WebView2 of its own lies over that space, a child of the app window's
form that goes straight to the site. It is a place apart from the app page: no
bridge to Python, nothing of the page's token, only http and https, and
cookies and storage in a WebView2 folder of its own that stays between runs,
so the person stays signed in. Minimizing it or going to Settings only hides
the pane: the page goes on, with its sound and its history, one press away.
Closing it ends its WebView2 processes: nothing of it runs while no page is open.
The page open last, until the pane is closed, each site's own zoom (outside
private mode) and the size the person gave the window while a site was in front
are kept in kept.json beside that folder.

The pane has tabs (the strip is browsetabs.js): one WebView2 each, on the same
folder and so the same browser processes. A site's new tab or popup opens as a
tab of its own that the site keeps hold of (window.opener), so a sign-in popup
hands its answer back and closes; the bar's private button opens an InPrivate
tab beside the others. Only the tab in front is shown, timed and operated. A tab
out of the front for a few minutes, and the tabs while the app window is away,
rest: suspended with little memory until shown or called (`rests`).

`Pane` is made of parts, each in a module of its own: where its WebView lies and
how big the window is (paneplace.py), the reading timed (panereading.py), what
sites ask (paneasks.py), the menus and zoom (panemenus.py) and the character
operating the page (paneop.py). `signedread.Reader` reads one address with the
person's session, out of sight.
"""
from __future__ import annotations

import contextlib
import json
import threading
import time
import webbrowser
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

from . import browsed, signwatch
from .paneasks import AskingPane
from .panemenus import MENU, MenuPane
from .paneop import OperatedPane
from .paneplace import PlacedPane
from .panereading import TICK_MS, ReadingPane
from .storage import atomic_write_text
from .webview2 import make_view, seal

# The page's own canvas (app.css), shown before the site draws: light, dark.
CANVAS = ("#fcfcfd", "#202022")
ACTIONS = ("back", "forward", "reload", "stop", "system", "close", "private", "hide", "return", "mute", "loaded",
           "op_stop", "op_take", "fit", "tab_new", "tab_close", "tab_select", "tab_reopen", "tab_next", "tab_prev",
           "find", "print", "zoom_in", "zoom_out", "zoom_reset", "menu", "dl_open", "dl_folder",
           "allow_once", "allow_always", "refuse")
# The pane's and its tabs' own buttons among them.
TAB_ACTIONS = ("close", "system", "private", "tab_new", "tab_select", "tab_close", "tab_next", "tab_prev",
               "tab_reopen")
# Schemes that are the browser's own, or that Chromium never hands to a program: refused without a word. Any other
# scheme that is not the web is a program's (mailto:, weixin:), named on the strip.
INSIDE = ("about", "blob", "chrome", "data", "devtools", "edge", "file", "filesystem", "javascript", "view-source",
          "afp", "disk", "disks", "hcp", "ie.http", "ms-help", "nntp", "res", "shell", "vbscript", "vnd.ms.radio")
# Tabs closed that Ctrl+Shift+T can bring back, newest last (never a private one).
CLOSED_KEPT = 10
# Beside the pane's WebView2 folder: the page open last ({"url", "title"}), each site's own zoom, the window's
# size while a site is in front, once the person set one ([wide, high] in px at 100 %), the downloads, the site
# permissions allowed always ({origin: kinds}), and whether sites are fitted to the pane's width.
KEPT = "kept.json"
# A page the character opens out of sight: laid out at this size behind the app's own page, where nothing of it
# shows.
ASIDE = (1280, 800)
# A tab out of the front and not called by code this long rests (`rests`), as Chromium freezes a tab left in the
# background; looked for this often.
IDLE_S = 5 * 60
REST_LOOK_MS = 60_000


def _dark() -> bool:
    import winreg
    with contextlib.suppress(OSError), winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                        r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
        return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
    return False


def tell_script(state: dict) -> str:
    """What the app page runs to show `state` in the pane's bar (browse.js)."""
    return f"window.paBrowse && paBrowse({json.dumps(state)})"


class _Tab:
    """One tab of the pane: its WebView (made once it has a page to show), its core once that is ready, whether it
    is private (an InPrivate profile: no sign-in of the person's, nothing kept), the address on its way, the
    site's request a popup waits on (with its deferral), the tab that opened it, what the strip shows, what its page
    asks of the person (the strip under the bar shows the first, while the tab is in front), the permissions
    allowed this time, for its page as it is now ({origin: kinds}), since when it is out of the front and when
    code last called its page (monotonic), which `rests` goes by, and whether it rests."""

    def __init__(self, ident: int, private: bool, opener: _Tab | None = None):
        self.id, self.private, self.opener = ident, private, opener
        self.view = self.core = None
        self.pending = ""
        self.popup: tuple | None = None
        self.url = self.title = ""
        self.loading = self.sound = False
        # Opened by the character out of sight (Pane.place_page): drawn behind the app's page until it comes to
        # the front.
        self.aside = False
        self.notices: list[dict] = []
        self.once: dict[str, set] = {}
        self.left = time.monotonic()
        self.used = float("-inf")
        self.resting = False


def rests(tab: _Tab, front: bool, worked: bool, away: bool, quiet: bool, now: float) -> bool:
    """Whether a tab's page rests: hidden, kept to little memory and suspended (Pane._settle). Every page while quiet.
    Else none that plays sound, none while the character's run is under way in the pane (`worked`), none that code
    called within IDLE_S; of the others, each while the app window is away (in the notification area or minimized),
    except a page the character opened out of sight, and any out of the front for IDLE_S."""
    if quiet:
        return True
    if tab.sound or worked or now - tab.used < IDLE_S:
        return False
    return (away and not tab.aside) or (not front and now - tab.left >= IDLE_S)


class Pane(PlacedPane, ReadingPane, AskingPane, MenuPane, OperatedPane):
    """The site's WebViews in the app window's `form`, one per tab, made when a link opens and
    gone again when the pane closes. Its work runs on the form's thread, through
    `ui`. `tell(state)` hands the page what its bar shows, `find` names the find
    at an address ("" for none; called on a thread of its own), and `visit(row)`
    takes a page left ({"url", "title", "s", "at", "id", "facts"}; on a thread of its
    own). `full(core, on)` makes the window full screen for a video, or puts it
    back; it answers with `cover`. Its state lives here; the parts it is made of
    (the classes it derives from) work on it."""

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
        # The tabs in the strip's order, the one in front, the addresses of tabs closed (Ctrl+Shift+T), and the
        # last tab number given.
        self._tabs: list[_Tab] = []
        self._tab: _Tab | None = None
        self._closed: list[str] = []
        self._made = 0
        # The space the page keeps for the WebView (form px), and what of the app page lies over it (the chat in a
        # narrow window, the address bar's suggestions): rects in its CSS px.
        self._box = None
        self._cuts: list = []
        # The cuts that stood before, each with the input tick (GetTickCount) it ended at: a press on a card that
        # closes it is judged by the cuts it was pressed on, not by the page laid out again after it.
        self._cuts_before: list[tuple[int, list]] = []
        # While the pane is in front: the window as it stood for the chat, where it was put, and the size given it.
        self._roomed: dict | None = None
        # The page being read: its address, title, find id once known, seconds counted and since when
        # (monotonic), whether it showed a password field, and its facts once read long enough.
        self._reading: dict | None = None
        self._quieted = False
        self._full = False
        # Hidden: the person minimized the pane or went to Settings, and the page goes on behind the chip that
        # brings it back.
        self._hidden = False
        # The app window is out of sight (AppWindow._settle): the pages rest as `rests` says.
        self._out = False
        self._timer = self._rest_timer = None
        # .NET holds no reference to these.
        self._handlers = (lambda s, a: self._count(), lambda s, a: self._pause(), self._resized, self._tick,
                          self._resize_end, lambda s, a: self._settle())
        # While the character operates the page: the task, the step it is on, why it must stop ("stopped",
        # "paused" when the person moved in the pane), and the input watch that finds the person's own moves
        # (the run's own clicks go through DevTools, not Windows).
        self.op: dict | None = None
        self._op_last: dict | None = None
        self._op_timer = None
        self._op_seen = 0
        self._op_looked = 0
        self._op_tick = lambda sender, args: self._input_tick()
        self._listeners: list = []
        # Zoom: the app page's px per CSS px, the person's own zoom per site (kept in KEPT; in private mode for this
        # run only), the menu's 适应宽度 (fit to width, kept in KEPT, on until turned off), the factor last set here,
        # and what the bar was told. KEPT also holds the page open last and the window's size with a site in front.
        self._scale = 1.0
        self._kept = self._read_kept()
        self.fit = self._kept["fit"]
        self._zoom_private: dict[str, float] = {}
        self._zoom_set = 0.0
        self._zoom_told: tuple = ()
        # Between a navigation's start and its end, WebView2 may bring back a zoom it remembers for the site.
        self._navigating = False
        # The downloads the menu lists, newest first ({"id", "path", "url", "bytes", "got", "state", "private"}); the
        # kept ones come back from KEPT.
        self._downloads: list[dict] = [{**row, "id": n + 1, "private": False}
                                       for n, row in enumerate(self._kept["downloads"])]
        self._download_n = len(self._downloads)
        # The site permissions the person allowed always ({origin: kinds}): kept in KEPT, in private mode for this
        # run only; and the last number given to something the strip shows.
        self._permits_private: dict[str, list] = {}
        self._noticed = 0
        self.ui(self._watch_form)

    # ---- the tab in front: its WebView, its core, whether it is private

    @property
    def _view(self):
        return self._tab.view if self._tab is not None else None

    @property
    def _core(self):
        return self._tab.core if self._tab is not None else None

    @property
    def private(self) -> bool:
        return self._tab is not None and self._tab.private

    def _tab_of(self, sender) -> _Tab | None:
        """The tab a WebView or a core belongs to."""
        return next((tab for tab in self._tabs if sender is not None and (
            (tab.view is not None and tab.view.Equals(sender)) or (tab.core is not None and tab.core.Equals(sender)))),
            None)

    # ---- what the app asks, from any thread

    def open(self, address: str) -> None:
        """A link from the app: in a new tab when the one in front has a page."""
        self.ui(lambda: self._open(address))

    def go(self, address: str) -> None:
        """What the person typed in the bar: in the tab in front."""
        self.ui(lambda: self._open(address, here=True))

    def place_page(self, address: str, show: bool) -> dict:
        """A page the character opens (surface.py): with `show` as a link does, in front; else in a tab of its own
        behind the others, the tab in front and what the person sees left as they are. Its tab's number and
        address."""
        made: list = []

        def go() -> None:
            if show:
                self._open(address)
            tab = self._tab if show else self._aside(address)
            made.append({"id": tab.id, "url": address, "title": ""})
        self.ui(go)
        return made[0]

    def tabs(self) -> list[dict]:
        """Every tab: its number, title, address, whether it is private, in front, or opened out of sight."""
        found: list = []
        self.ui(lambda: found.extend({"id": t.id, "title": t.title, "url": t.url, "private": t.private,
                                      "front": t is self._tab, "aside": t.aside} for t in self._tabs))
        return found

    def front(self, ident: int) -> bool:
        """Tab `ident` comes to the front, the pane shown; False when there is no such tab."""
        done: list = []

        def bring() -> None:
            tab = next((t for t in self._tabs if t.id == ident), None)
            if tab is not None:
                self._switch(tab)
                if self._hidden:
                    self._do("return")
                self.tell({"open": True, "url": tab.url, "host": urlsplit(tab.url).hostname or "",
                           "title": tab.title, "private": tab.private, **self._strip()})
            done.append(tab is not None)
        self.ui(bring)
        return bool(done and done[0])

    def core_of(self, ident: int = 0):
        """The page of tab `ident`, or of the tab in front with 0; None when it is not there."""
        if not ident:
            return self._core
        return next((t.core for t in self._tabs if t.id == ident), None)

    def do(self, action: str, tab: int = 0) -> None:
        """A press in the bar, the strip or the menu; `tab` names the tab a strip press is for, or the download a
        press in the menu's list is for."""
        self.ui(lambda: self._do(action, tab))

    def quiet(self, on: bool) -> None:
        if self._tabs:
            self.ui(lambda: self._quiet(on))

    def close(self) -> None:
        """The app is quitting: the page left is handed over now, while the page's server still answers. Its
        address stays kept, offered when the app starts again."""
        sent: list = []
        self.ui(lambda: sent.append(self._shut(forget=False)))
        if sent and sent[0]:
            with contextlib.suppress(Exception):
                self.visit(sent[0])

    def forget(self, zoom: bool) -> None:
        """History cleared: the page open last, the tabs closed lately and the list of downloads are forgotten (the
        files stay), with `zoom` every site's zoom too; the pane stays open, its page read as from now."""
        def drop() -> None:
            reading = self._reading
            if reading is not None:
                reading.update(s=0.0, at=time.time(), since=time.monotonic() if reading["since"] is not None else None)
            self._closed.clear()
            self._kept["last"] = {}
            if zoom:
                self._kept["zoom"].clear()
            self._downloads.clear()
            self._tell_downloads(keep=True)
            self.tell({"kept": None})
        self.ui(drop)

    # ---- on the form's thread

    def _watch_form(self) -> None:
        from System.Windows.Forms import Timer
        activated, deactivated, resized, tick, resize_end, look = self._handlers
        self.form.Activated += activated
        self.form.Deactivate += deactivated
        self.form.Resize += resized
        self.form.ResizeEnd += resize_end
        self._timer = Timer()
        self._timer.Interval = TICK_MS
        self._timer.Tick += tick
        # Tabs left idle come to rest.
        self._rest_timer = Timer()
        self._rest_timer.Interval = REST_LOOK_MS
        self._rest_timer.Tick += look
        self._rest_timer.Start()

    def _open(self, address: str, here: bool = False) -> None:
        """`address` in the tab in front when `here` or when it is still empty (and not private), else in a new
        tab: a link from the app or a tab brought back is never private."""
        if self._tab is None or not (here or (self._tab.view is None and not self._tab.private)):
            self._switch(self._new_tab(False))
        tab = self._tab
        self._begin(address)
        tab.url, tab.title = address, ""
        if tab.core is None:
            tab.pending = address
            # With the pane already placed the WebView is made now; else once the page says where it goes.
            if tab.view is None and self._box is not None:
                self._make(tab)
        else:
            tab.core.Navigate(address)
        if self._quieted:
            self._quiet(False)
        if self._hidden:
            self._do("return")
        self.tell({"open": True, "url": address, "host": urlsplit(address).hostname or "", "title": "",
                   "back": False, "forward": False, "loading": True, "private": self.private, **self._strip()})

    def _new_tab(self, private: bool, opener: _Tab | None = None) -> _Tab:
        """A tab with no page yet, after the one in front (a site's new tab beside the tab that opened it)."""
        self._made += 1
        tab = _Tab(self._made, private, opener)
        at = self._tabs.index(self._tab) + 1 if self._tab in self._tabs else len(self._tabs)
        self._tabs.insert(at, tab)
        return tab

    def _aside(self, address: str) -> _Tab:
        """A tab out of sight at the end of the strip, its WebView made now behind the app's page and muted."""
        from System.Drawing import Rectangle
        self._made += 1
        tab = _Tab(self._made, False)
        tab.aside, tab.url, tab.pending, tab.used = True, address, address, time.monotonic()
        self._tabs.append(tab)
        self._make(tab, Rectangle(0, 0, *ASIDE))
        self.tell(self._strip())
        return tab

    def _switch(self, tab: _Tab) -> None:
        """`tab` comes to the front: the one before is hidden and its reading ends, this one is shown, sized, cut
        and zoomed as the pane is, and its page is read from now. A run under way pauses (it acts on the page in
        front only), unless it waits for the person's own sign-in."""
        if tab is self._tab:
            return
        tab.aside = False
        before = self._tab
        if before is not None:
            self._send(self._finish())
            before.left = time.monotonic()
            if before.view is not None:
                before.view.Visible = False
        self._tab = tab
        op = self.op
        if op is not None and not op.get("held") and not op.get("wait"):
            op["held"] = "paused"
            self._tell_op()
        if tab.view is not None:
            tab.view.Visible = not self._hidden and not self._quieted
            if self._box is not None:
                tab.view.Bounds = self._box
                self._cut()
            tab.view.BringToFront()
            self._zoom_told = ()
            self._zoom()
        # A page that rested while out of the front wakes as it shows.
        self._settle()
        if tab.core is not None and browsed.web(str(tab.core.Source)):
            self._begin(str(tab.core.Source))
            self._reading["begun"] = True
            self._count()
        self._state()
        self._tell_prompt()
        if tab.core is not None:
            self._sound(tab.core, None)

    def _close_tab(self, tab: _Tab) -> None:
        """A tab closes (its ×, Ctrl+W, or the page's own window.close()): its address can come back with
        Ctrl+Shift+T, unless it was private or a sign-in or payment page. The tab that opened it, else the one
        beside it, comes to the front; the last tab closes the pane."""
        if len(self._tabs) == 1:
            self._send(self._shut())
            return
        url = str(tab.core.Source) if tab.core is not None else ""
        if not tab.private and browsed.web(url) and not browsed.secret(url):
            self._closed.append(url)
            del self._closed[:-CLOSED_KEPT]
        at = self._tabs.index(tab)
        if tab is self._tab:
            self._send(self._finish())
            self._tab = None
        self._tabs.remove(tab)
        self._drop(tab)
        if self._tab is None:
            self._switch(tab.opener if tab.opener in self._tabs else self._tabs[min(at, len(self._tabs) - 1)])
        else:
            self.tell(self._strip())

    def _drop(self, tab: _Tab) -> None:
        """A tab's WebView and its page go; a popup still waiting is let go as the site's own, and what its page
        asked is refused."""
        self._clear(tab)
        if tab.popup is not None:
            args, deferral = tab.popup
            tab.popup = None
            args.Handled = True
            deferral.Complete()
        if tab.view is not None:
            self.form.Controls.Remove(tab.view)
            tab.view.Dispose()
        tab.view = tab.core = None

    def _strip(self) -> dict:
        """What the strip shows: each tab's number, title, address, private, loading and sound, and the one in front."""
        return {"tabs": [{"id": t.id, "title": t.title, "url": t.url, "private": t.private, "loading": t.loading,
                          "sound": t.sound} for t in self._tabs],
                "tab": self._tab.id if self._tab is not None else 0}

    def _make(self, tab: _Tab, box=None) -> None:
        """The tab's WebView, on the pane's folder (so in the same browser processes as the other tabs); with `box`
        out of sight there, behind the app's page."""
        from System.Drawing import ColorTranslator
        view = make_view(self.folder, tab.private)
        view.DefaultBackgroundColor = ColorTranslator.FromHtml(CANVAS[_dark()])
        view.Bounds = box or self._box
        view.Visible = box is not None or (tab is self._tab and not self._hidden and not self._quieted)
        view.CoreWebView2InitializationCompleted += self._ready
        view.ZoomFactorChanged += self._zoomed
        view.KeyDown += self._key
        self.form.Controls.Add(view)
        if box is None:
            view.BringToFront()
        else:
            view.SendToBack()
        tab.view = view
        view.EnsureCoreWebView2Async(None)

    def _ready(self, sender, args) -> None:
        tab = self._tab_of(sender)
        if tab is None:
            return
        if not args.IsSuccess:
            # No view for it: the tab goes, and a popup waiting on it is let go.
            self._close_tab(tab)
            return
        core = sender.CoreWebView2
        seal(core)
        core.Settings.IsSwipeNavigationEnabled = True
        # The browser's own password saving and autofill, and each page looked at for a sign-in (signwatch.py).
        signwatch.ready(self, core, tab.private)
        core.NavigationStarting += self._starting
        core.NavigationCompleted += self._completed
        core.NewWindowRequested += self._new_window
        core.WindowCloseRequested += self._close_requested
        core.PermissionRequested += self._permission
        core.LaunchingExternalUriScheme += self._external
        core.DocumentTitleChanged += self._changed
        core.SourceChanged += self._changed
        core.HistoryChanged += self._changed
        core.ContainsFullScreenElementChanged += self._full_screen
        core.DownloadStarting += self._download
        core.ContextMenuRequested += self._menu
        core.IsDocumentPlayingAudioChanged += self._sound
        core.IsMutedChanged += self._sound
        tab.core = core
        if tab.aside:
            # Out of sight: no sound, and the page acts as a page in front would (focus, as Playwright's do).
            core.IsMuted = True
            core.CallDevToolsProtocolMethodAsync("Emulation.setFocusEmulationEnabled", '{"enabled": true}')
        if tab.popup is not None:
            # The site's popup is this tab's page: it keeps window.opener, so a sign-in hands its answer back.
            request, deferral = tab.popup
            tab.popup = None
            request.NewWindow = core
            request.Handled = True
            deferral.Complete()
        elif tab.pending:
            core.Navigate(tab.pending)
            tab.pending = ""
        if tab is self._tab:
            self._count()

    def _starting(self, sender, args) -> None:
        """Only web addresses load: file:, about:, data: and the browser's other schemes are refused; a program's
        scheme goes on to `_external`, which never lets it start. A new page drops what the last one asked."""
        from Microsoft.Web.WebView2.Core import CoreWebView2NavigationKind
        if not browsed.web(args.Uri):
            scheme = urlsplit(str(args.Uri)).scheme
            args.Cancel = not scheme or scheme in INSIDE
            return
        tab = self._tab_of(sender)
        tab.loading = True
        if tab.notices or tab.once:
            self._clear(tab)
            if tab is self._tab:
                self._tell_prompt()
        if tab is not self._tab:
            self.tell(self._strip())
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
        tab = self._tab_of(sender)
        tab.loading = False
        if tab is not self._tab:
            self._changed(sender, args)
            return
        if args.IsSuccess:
            source = str(sender.Source)
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

    def _changed(self, sender, args) -> None:
        tab = self._tab_of(sender)
        if tab is self._tab:
            self._state()
        elif tab is not None:
            tab.url, tab.title = str(sender.Source), str(sender.DocumentTitle or "").strip()
            self.tell(self._strip())

    def _state(self, loading: bool | None = None) -> None:
        """What the bar shows of the tab in front (an empty one has no address yet), with the strip."""
        tab, core = self._tab, self._core
        if core is not None:
            tab.url, tab.title = str(core.Source), str(core.DocumentTitle or "").strip()
        source, title = tab.url, tab.title
        if self._reading is not None and self._reading["url"] == source:
            self._reading["title"] = title
        state = {"url": source, "host": urlsplit(source).hostname or "", "title": title,
                 "back": core is not None and bool(core.CanGoBack), "forward": core is not None and bool(core.CanGoForward),
                 "private": tab.private, "loading": tab.loading if loading is None else loading, **self._strip()}
        self.tell(state)
        self._keep_last(source, title)

    def _sound(self, sender, args) -> None:
        """A tab began or stopped playing sound, or was muted: the bar and the chip show a speaker for the one in
        front, the strip one on each tab that plays."""
        tab = self._tab_of(sender)
        tab.sound = bool(sender.IsDocumentPlayingAudio)
        if tab is self._tab:
            self.tell({"sound": tab.sound, "muted": bool(sender.IsMuted), **self._strip()})
        else:
            self.tell(self._strip())

    def _new_window(self, sender, args) -> None:
        """A site's new tab or popup, only from the person's click: a tab of its own in front, whose page the site
        keeps hold of (the WebView is made, then handed to the site in `_ready`). While the character acts, it
        opens in the page it acts on instead, so the run stays on the one page its guards watch. A popup the page
        opens by itself is stopped and named on the strip, which can open it in a tab."""
        args.Handled = True
        uri = str(args.Uri)
        if not args.IsUserInitiated:
            opener = self._tab_of(sender)
            if browsed.web(uri) and self.op is None and opener is not None:
                self._notice(opener, "popup", url=uri)
            return
        if not (browsed.web(uri) or uri == "about:blank"):
            return
        op = self.op
        if op is not None and not op.get("held") and not op.get("wait"):
            if browsed.web(uri):
                self._send(self._finish())
                sender.Navigate(uri)
            return
        opener = self._tab_of(sender)
        tab = self._new_tab(opener.private, opener)
        tab.popup, tab.url = (args, args.GetDeferral()), uri if browsed.web(uri) else ""
        self._switch(tab)
        self._make(tab)

    def _close_requested(self, sender, args) -> None:
        """The page closed its own window (a sign-in popup that is done): its tab goes, once the event is over."""
        from System import Action
        tab = self._tab_of(sender)
        self.form.BeginInvoke(Action(lambda: self._close_tab(tab) if tab in self._tabs else None))

    def _do(self, action: str, ident: int = 0) -> None:
        """The bar's, the strip's and the menu's buttons, from the page; `ident` names the tab a strip press is for,
        or the download of a press in the menu's list."""
        if action in TAB_ACTIONS:
            self._tab_action(action, ident)
        elif action in ("hide", "return"):
            self._hide(action == "hide")
        elif action == "loaded":
            self._loaded()
        elif action in ("op_stop", "op_take"):
            self._take(action == "op_stop")
        elif action in ("allow_once", "allow_always", "refuse"):
            # The strip's buttons; `ident` names what they answer.
            self._answer(ident, {"allow_once": "once", "allow_always": "always"}.get(action, "no"))
        elif action in MENU:
            self._from_menu(action, ident)
        elif self._core is not None:
            self._navigate(action)

    def _tab_action(self, action: str, ident: int) -> None:
        """The pane's close, the system browser's button, and the tabs': a new one (private or not), one picked or
        closed (`ident`), the next or the one before, the last one closed brought back."""
        if action == "close":
            self._send(self._shut())
        elif action == "system":
            # Read elsewhere from here on: the tab has done its part.
            core = self._core
            target = str(core.Source) if core is not None else self._tab.pending
            if browsed.web(target):
                threading.Thread(target=webbrowser.open, args=(target,), name="mibo-browser",
                                 daemon=True).start()
            self._close_tab(self._tab)
        elif action in ("private", "tab_new"):
            # An empty tab in front, private or not, and the address to type in; the other tabs stay as they are.
            self._switch(self._new_tab(action == "private"))
            self.tell({"focus": "address"})
        elif action in ("tab_select", "tab_close"):
            tab = next((t for t in self._tabs if t.id == ident), None)
            if tab is not None:
                (self._switch if action == "tab_select" else self._close_tab)(tab)
        elif action in ("tab_next", "tab_prev") and len(self._tabs) > 1:
            at = self._tabs.index(self._tab) + (1 if action == "tab_next" else -1)
            self._switch(self._tabs[at % len(self._tabs)])
        elif action == "tab_reopen" and self._closed:
            self._open(self._closed.pop())

    def _hide(self, hidden: bool) -> None:
        """最小化 or Settings: the page goes on behind the chip, with its sound and its history; back, it is as it
        was. A run under way pauses: the page is out of sight."""
        self._hidden = hidden
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

    def _loaded(self) -> None:
        """The app page loaded again: a page still open waits behind its chip; with none, the page open last is
        offered."""
        self._tell_downloads()
        if self._tab is None:
            if self._kept["last"]:
                self.tell({"kept": self._kept["last"]})
            return
        self._state()
        self._tell_prompt()
        if self._core is not None:
            self._sound(self._core, None)
        self._zoom_told = ()
        self._zoom()
        self._do("hide")

    def _navigate(self, action: str) -> None:
        """The bar's back, forward, reload, stop and mute, on the page in front."""
        core = self._core
        if action == "mute":
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

    def _key(self, sender, args) -> None:
        """Ctrl L in the page: to the bar's address, as in any browser. Ctrl T, Ctrl W, Ctrl Shift T, Ctrl Tab and
        Ctrl Shift Tab: a new tab, this one closed, the last one closed back, the next and the one before. Ctrl 0
        (WebView2 may leave the zoom as it is): back to the fit for the site."""
        from System.Windows.Forms import Keys
        tabs = ((Keys.T, "tab_reopen" if args.Shift else "tab_new"), (Keys.W, "tab_close"),
                (Keys.Tab, "tab_prev" if args.Shift else "tab_next"))
        action = next((name for key, name in tabs if args.KeyCode == key), "") if args.Control and not args.Alt else ""
        if action:
            args.Handled = True
            self._do(action, self._tab.id)
        elif args.Control and args.KeyCode == Keys.L:
            self.form.browser.webview.Focus()
            self.tell({"focus": "address"})
        elif args.Control and args.KeyCode in (Keys.D0, Keys.NumPad0) and self._host() in self._zooms():
            self._set_own_zoom(1.0)

    # ---- kept between runs (KEPT)

    def _read_kept(self) -> dict:
        try:
            kept = json.loads((self.folder / KEPT).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            kept = {}
        return {"zoom": kept.get("zoom") or {}, "last": kept.get("last") or {}, "size": kept.get("size") or [],
                "downloads": kept.get("downloads") or [], "permits": kept.get("permits") or {},
                "fit": kept.get("fit", True)}

    def _keep(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self.folder / KEPT, json.dumps(self._kept, ensure_ascii=False))

    def _keep_last(self, url: str, title: str) -> None:
        """The page open now, offered again after a restart; never in private mode or a sign-in or payment page."""
        last = {"url": url, "title": title[:200]}
        if self.private or not browsed.web(url) or browsed.secret(url) or last == self._kept["last"]:
            return
        self._kept["last"] = last
        self._keep()

    def _shut(self, forget: bool = True) -> dict | None:
        """The pane closes: every tab's WebView and their processes go, and the reading ends. Closed by the person,
        the page open last is forgotten too; the app quitting keeps it, to offer when the app starts again."""
        sent = self._finish()
        if self._full:
            self.full(self._core, False)
        for tab in self._tabs:
            self._drop(tab)
        self._tabs, self._tab, self._box = [], None, None
        self._quieted = self._full = self._hidden = False
        if forget and self._kept["last"]:
            self._kept["last"] = {}
            self._keep()
        self.tell({"open": False})
        return sent

    def _quiet(self, on: bool) -> None:
        """Quiet hides the pane with the pet and suspends every tab's page; they come back as they were."""
        if on == self._quieted:
            return
        self._quieted = on
        if on:
            self._pause()
        self._settle()
        if not on:
            self._count()

    def away(self, on: bool) -> None:
        """The app window went out of sight or came back (AppWindow._settle): the pages rest or wake as `rests`
        says."""
        self._out = on
        if self._tabs:
            self.ui(self._settle)

    def in_use(self, ident: int = 0):
        """The page of tab `ident` (the one in front with 0) for code that calls it, which keeps it from resting
        for IDLE_S; None when it is not there. On the form's thread."""
        tab = next((t for t in self._tabs if t.id == ident), None) if ident else self._tab
        if tab is None:
            return None
        tab.used = time.monotonic()
        if tab.resting:
            self._settle()
        return tab.core

    def _settle(self) -> None:
        """Each tab's page as `rests` says: resting, out of sight with little memory and suspended; else shown if it is
        in front or opened out of sight, with its memory as before. A page at rest wakes when it shows (WebView2
        resumes it) or when code calls it (webview2.call_devtools)."""
        from Microsoft.Web.WebView2.Core import CoreWebView2MemoryUsageTargetLevel
        now, worked = time.monotonic(), self.op is not None
        for tab in self._tabs:
            still = rests(tab, tab is self._tab, worked, self._out, self._quieted, now)
            # Only a change: what else hides a tab (a video of the app's page full screen, paneplace.cover) holds.
            if tab.core is None or still == tab.resting:
                continue
            tab.resting = still
            tab.view.Visible = not still and (tab.aside or (tab is self._tab and not self._hidden))
            tab.core.MemoryUsageTargetLevel = (CoreWebView2MemoryUsageTargetLevel.Low if still
                                               else CoreWebView2MemoryUsageTargetLevel.Normal)
            if still:
                tab.core.TrySuspendAsync()
