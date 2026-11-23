"""The local page in a window of its own instead of a browser tab.

pywebview draws it: WebView2 on Windows, where it is installed with mibo,
and whatever `mibo[app]` finds on macOS and Linux. Without it, or when no
window opens, `mibo start` falls back to the browser.

On Windows the window loses its title bar to the page's own (native.py), keeps to
mibo's pages (winforms.py), shows videos full screen (fullscreen.py), and may come
with the pet (pet.py, petmoves.py, petmenu.py).
"""
from __future__ import annotations

import contextlib
import hmac
import importlib.util
import secrets
import signal
import socket
import sys
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from urllib.parse import urlsplit

from .. import browsed
from . import native, winforms
from .fullscreen import FullScreen
from .native import KEEP_ORDER
from .pet import PetWindow
from .petmoves import PetMoves

TITLE = "Mibo"
ICON = Path(__file__).parents[1] / "static" / "app"
SIZE = (1200, 820)
MIN_SIZE = (400, 560)
# How long the window has to appear before it counts as not opening.
SHOWN_WITHIN = 30
# How long the page has to ask for its title bar before the window takes its own back.
PAGE_WITHIN = 25
# What the page's own title bar may ask of a frameless window.
ACTIONS = ("minimize", "maximize", "restore", "close")


def available() -> bool:
    try:
        return importlib.util.find_spec("webview") is not None
    except (ImportError, ValueError):
        return False


def _toolkit() -> str | None:
    """Which toolkit draws the window; None lets pywebview choose."""
    if sys.platform == "win32":
        return "edgechromium"
    # pywebview tries GTK first and prints a traceback when it is absent,
    # which it is where the app extra installed Qt.
    with contextlib.suppress(ImportError, ValueError):
        if (sys.platform.startswith("linux") and importlib.util.find_spec("gi") is None
                and importlib.util.find_spec("qtpy") is not None):
            return "qt"
    return None


def icon() -> Path:
    return ICON.with_suffix(".ico" if sys.platform == "win32" else ".png")


def alert(text: str) -> None:
    """A sentence for someone who started mibo with no terminal."""
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, TITLE, 0x30)


@contextlib.contextmanager
def _interrupt(stop: Callable[[], None]) -> Iterator[None]:
    """Ctrl+C calls `stop` at once. The main thread sits in the window's own
    loop, where a Python signal handler would wait for it to come back."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    reader, writer = socket.socketpair()
    writer.setblocking(False)

    def wait() -> None:
        with contextlib.suppress(OSError):
            if reader.recv(1):
                stop()

    handler = signal.signal(signal.SIGINT, lambda *_: None)
    wakeup = signal.set_wakeup_fd(writer.fileno(), warn_on_full_buffer=False)
    threading.Thread(target=wait, name="mibo-interrupt", daemon=True).start()
    try:
        yield
    finally:
        signal.set_wakeup_fd(wakeup)
        signal.signal(signal.SIGINT, handler)
        writer.close()
        reader.close()


class AppWindow(PetWindow, PetMoves, FullScreen):
    """One window on `url`. While `background` says so, closing hides the
    window behind a notification-area icon instead, where the system has one
    for us (Windows); `words` names that icon's menu.

    With `pet` (Windows), mibo starts as the character alone on the
    desktop: the window stays hidden until the pet is double-clicked, and
    closing it hides it again. The pet's menu quits, and chooses the figure
    among `figures` ([(key, label)]) through `choose`; `figure` says which it
    is. While the window shows, the pet peeks over its top edge and goes
    wherever the window goes."""

    def __init__(self, url: str, *, storage: Path, background: Callable[[], bool] = lambda: False,
                 words: Callable[[], dict] = dict, start_hidden: bool = False,
                 pet: bool = False, figure: Callable[[], str] = lambda: "",
                 figures: Callable[[], list[tuple[str, str]]] = list,
                 choose: Callable[[str], object] = lambda key: None,
                 links: Callable[[], str] = lambda: "app", find: Callable[[str], str] = lambda address: "",
                 address: Callable[[str], str] = lambda ident: ""):
        self.url = url
        self.storage = storage
        self.background = background
        self.words = words
        self.start_hidden = start_hidden
        self.pet = pet and sys.platform == "win32"
        self.figure = figure
        self.figures = figures
        self.choose = choose
        # Where links open, "app" or "system"; the find at an address, and a find's address (see browser.py).
        self.links = links
        self.find = find
        self.address = address
        self._browser = self._reader = self._feeds = None
        self._full = None
        self._init_pet()
        # Device px per CSS px of the monitor the app window is on (native.watch_scale), and its handler,
        # which .NET holds no reference to.
        self._main_scale = 1.0
        self._scale_watch = None
        # Where the pet asked the window's page to go, until the page takes it.
        self._goto = ""
        # Menu handlers stay referenced here, or .NET would lose them.
        self._open_click = lambda sender, event: self.show()
        self._quit_click = lambda sender, event: self.close()
        self.opened = False
        # Why no window opened, for the log.
        self.error = ""
        self.hidden = False
        self._window = None
        self._leaving = False
        self._tray = None
        self._told = False
        # A window started for the background is created minimized.
        self._minimized = start_hidden
        #: The window has no title bar of its own: the page draws the bar and its buttons.
        self.frameless = False
        self.maximized = False
        # The frameless window's message handler and how to undo it; .NET holds no reference.
        self._frame = None
        self._frame_seen = threading.Event()
        # Only the page inside this window knows it: a browser tab on the same
        # address neither draws the window's bar nor presses its buttons.
        self.frame_key = secrets.token_urlsafe(16)

    @property
    def can_hide(self) -> bool:
        """Closing can leave mibo running behind an icon."""
        return self._tray is not None

    def show(self) -> bool:
        """Bring the window back in front; False when there is none. With the
        pet, the window comes up where the pet was and the pet peeks over it."""
        if not self.opened or self._leaving:
            return False
        if self._pet is not None:
            if self._attached:
                self._on_ui(self._window.native.Activate)
            else:
                threading.Thread(target=self._go_in, name="mibo-pet", daemon=True).start()
            return True
        try:
            # Only out of the taskbar: restoring a maximized window would shrink it.
            if self._minimized:
                self._window.restore()
            if self.hidden:
                self._page_seen(True)
            self._window.show()
            if self.hidden:
                self.hidden = False
                if self._tray is not None:
                    self._on_ui(lambda: setattr(self._tray, "Visible", False))
        except Exception:
            return False
        return True

    def hide(self) -> bool:
        """Leave the window for the notification area; False when it cannot."""
        if self._tray is None or not self.opened or self._leaving:
            return False
        words = {"still": "", **self.words()}

        def away() -> None:
            self._tray.Visible = True
            if not self._told and words["still"]:
                self._told = True
                self._tray.ShowBalloonTip(5000, TITLE, words["still"], self._tray_info)

        try:
            self._page_seen(False)
            self._window.hide()
            self.hidden = True
            self._on_ui(away)
        except Exception:
            return False
        return True

    def open_at(self, target: str) -> bool:
        """Show the window with its page asked to go to `target` ("feed/<id>", "feed" or "chat")."""
        self._goto = str(target or "")
        shown = self.show()
        # A find from the pet's card opens in the window's browser too, over the chat that carries it.
        if self._goto.startswith("feed/") and self._browser is not None and self.links() != "system":
            found = self.address(self._goto[5:])
            if found:
                self._browser.open(found)
        # A window already in front learns it from this, one coming up from showing.
        self._frame_changed()
        return shown

    # What the pages are told as it happens, so they need not keep asking (pet.js, app.js).

    def _tell(self, view, script: str) -> None:
        """Run `script` in a window's page, on a thread of its own: whoever
        tells it, the page's server among them, never waits for the page."""
        threading.Thread(target=lambda: view.evaluate_js(script), name="mibo-tell", daemon=True).start()

    def _page_seen(self, seen: bool) -> None:
        """The app window's WebView told it shows or is hidden in the
        notification area, before the window itself goes (as in _put_away):
        its page then knows it is hidden (document.hidden) and stops asking."""
        view = self._window.native.browser.webview
        self._on_ui(lambda: setattr(view, "Visible", seen))

    def _frame_changed(self) -> None:
        if self.opened:
            self._tell(self._window, "window.paFrame && paFrame()")

    def chats_changed(self) -> None:
        """A chat changed (a reply, a remark, something shared or delivered):
        the app window's page looks now, unless it is hidden."""
        if self.opened and not self.hidden:
            self._tell(self._window, "window.paChats && paChats()")
        # The pet's compact chat too, while it is out (petchat.py).
        if self._compact is not None and self._compact.out:
            self._tell(self._compact.window, "window.paChats && paChats()")

    def notify(self, text: str) -> None:
        """A scheduled task's message (panels/schedule.py) or a card waiting on the person (cardwait.py), as a
        system notification when the app window is not in front. The icon it comes from shows for as long as the
        notification."""
        if not self.opened or self._tray is None or self._leaving:
            return
        from System.Windows.Forms import Form

        def tell() -> None:
            if not self.hidden and Form.ActiveForm is not None and Form.ActiveForm == self._window.native:
                return
            shown = self._tray.Visible
            self._tray.Visible = True
            self._tray.ShowBalloonTip(8000, TITLE, " ".join(text.split())[:200], self._tray_info)
            if not shown:
                threading.Timer(10, lambda: self._on_ui(back)).start()

        def back() -> None:
            if not self.hidden:
                self._tray.Visible = False

        self._on_ui(tell)

    def pick_folder(self) -> str:
        """The system's folder dialog over the app window (Settings › Files and commands): the folder picked, or ""."""
        import webview
        picked = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        return picked[0] if picked else ""

    def pick_files(self, many: bool) -> list[str]:
        """The system's Open dialog over the app window (a page's upload card): the files picked, or none."""
        import webview
        return list(self._window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=many) or [])

    def save_file(self, name: str) -> str:
        """The system's Save dialog over the app window (Settings › 记忆's export), offering `name`: the path chosen, or ""."""
        import webview
        picked = self._window.create_file_dialog(webview.FileDialog.SAVE, save_filename=name)
        return (picked if isinstance(picked, str) else picked[0] if picked else "") or ""

    def take_goto(self) -> str:
        """Where the page was asked to go, once."""
        target, self._goto = self._goto, ""
        return target

    def open_link(self, address: str) -> None:
        """A link that leaves the app: the browser inside the app window, unless the person chose the system's."""
        if self._browser is not None and self.links() != "system":
            if self.hidden or self._minimized:
                self.show()
            self._browser.open(address)
        else:
            import webbrowser
            threading.Thread(target=webbrowser.open, args=(address,), name="mibo-link", daemon=True).start()

    # The app's own browser pane (browser.Pane) and what it reads (browser.Reader).

    @property
    def pane(self):
        """The app's own browser pane (browser.Pane), None without one."""
        return self._browser

    def browse_place(self, box: list, scale: float, cuts: list) -> bool:
        """Where the page keeps the browser's pane, CSS px, its device pixel ratio, and what of the page lies over
        the pane (rects inside it: the chat in a narrow window, the bar's suggestions); False with no pane."""
        if self._browser is None:
            return False
        self._browser.place(box, scale, cuts)
        return True

    def browse_room(self, wide: float, scale: float) -> bool:
        """The pane came to the front and its page asks for a window `wide` of its CSS px wide, or with 0 it left
        the front and the window takes its own size back (browser.Pane._room); False with no pane."""
        if self._browser is None:
            return False
        self._browser.room(wide, scale)
        return True

    def browse_do(self, action: str, tab: int = 0) -> bool:
        """A button of the pane's bar or its tab strip (browser.ACTIONS; `tab` names the tab); False with no pane."""
        if self._browser is None:
            return False
        self._browser.do(action, tab)
        return True

    def browse_read(self, url: str, start: int = 0) -> dict:
        """One address read with the person's session, out of sight (browser.Reader), from character `start`."""
        if self._reader is None or not browsed.shared(self.storage.parent):
            return {"error": "off"}
        return self._reader.read(url, runtime=self.storage.parent.parent, start=start)

    def browse_clear(self, since: float = 0.0) -> None:
        """The history from `since` on (all of it with 0): its rows and the library items they made (browsed.clear),
        what the pane keeps of it (Pane.forget), and the profile's own history, download history and cache of that
        time. Sign-ins and saved passwords stay: Settings › 连接 has them."""
        from ..signwatch import Profile
        if self._browser is not None:
            # On the form's thread in this order, so the page open now is read as from now before the rows go.
            self._browser.forget(zoom=not since)
            Profile(self._browser).clear("history", since)
        browsed.clear(self.storage.parent, since)

    def browse_permits(self) -> list[dict]:
        """The site permissions the person decided in the app's browser, by site (browser.Pane.permits)."""
        return self._browser.permits() if self._browser is not None else []

    def browse_unpermit(self, origin: str, kind: str) -> None:
        """One site permission taken back: the site is asked again next time."""
        if self._browser is not None:
            self._browser.unpermit(origin, kind)

    def _make_pane(self) -> None:
        """The browser pane in the app window, the reader that reads with its session, and the feeds it reads.
        Without it, as without the tray, links go to the system browser."""
        from .. import browser
        desktop = self.storage.parent
        self._browser = browser.Pane(
            desktop / "browser", self._window.native, ui=self._on_ui, find=self.find,
            visit=self._visit, tell=lambda state: self._tell(self._window, browser.tell_script(state)),
            full=self._full_screen)
        self._reader = browser.Reader(desktop / "browser", self._window.native, ui=self._on_ui,
                                      pace=browsed.Pace(desktop))
        self._feeds = browser.Feeds(self._reader, desktop.parent, shared=lambda: browsed.shared(desktop))

    def _read(self, ident: str, seconds: float) -> None:
        """A find read in the app's browser, told to the recommender as the page tells it a reaction."""
        import httpx

        from ..welcome import TOKEN_HEADER

        address = urlsplit(self.url)
        httpx.post(f"{address.scheme}://{address.netloc}/api/feed/react", timeout=5, trust_env=False,
                   json={"id": ident, "action": "read", "read_s": seconds, "surface": "browser"},
                   headers={TOKEN_HEADER: address.fragment.partition("token=")[2]})

    def _visit(self, row: dict) -> None:
        """A page read in the app's browser: its row kept; read long enough and shared, an Item of the
        person's reading; a find's or such an Item's time told to the recommender."""
        desktop = self.storage.parent
        from ..browser import READ_MIN_S
        from ..web import signin
        # A signed-in site's pages are the person's own: kept only where they let it be browsed in the background.
        if signin.kept_out(desktop, row["url"]):
            return
        if row["s"] < READ_MIN_S:
            # A glance at a find: not a page they read, only told to the recommender as the look it was.
            if browsed.shared(desktop):
                self._read(row["id"], max(row["s"], 0.1))
            return
        if not browsed.record(desktop, row) or not browsed.shared(desktop):
            return
        ident = row["id"] or browsed.keep_item(desktop.parent, row, row["facts"])
        if ident:
            self._read(ident, row["s"])

    def attended(self) -> bool:
        """The person is at the app: its window shows, neither hidden nor minimized."""
        return self.opened and not self.hidden and not self._minimized

    def _watch_main_scale(self) -> None:
        """On the window's thread: from monitor to monitor it keeps its size in CSS px."""
        form = self._window.native
        self._main_scale = form._scale
        self._scale_watch = native.watch_scale(form.Handle.ToInt64(), self._main_rescaled)

    def _main_rescaled(self, scale: float, suggested: tuple[int, int, int, int]) -> None:
        """Where Windows suggests, no smaller than MIN_SIZE CSS px there, and the pane where the page keeps it."""
        import ctypes
        from ctypes import wintypes

        from System.Drawing import Size

        form, old = self._window.native, self._main_scale
        self._main_scale = scale
        user32 = ctypes.WinDLL("user32")
        user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                        ctypes.c_int, ctypes.c_int, wintypes.UINT]
        least = Size(int(MIN_SIZE[0] * scale), int(MIN_SIZE[1] * scale))
        # The smaller minimum first, so the old one never holds the new size back.
        if scale < old:
            form.MinimumSize = least
        left, top, right, bottom = suggested
        user32.SetWindowPos(form.Handle.ToInt64(), None, left, top, right - left, bottom - top, KEEP_ORDER)
        if scale >= old:
            form.MinimumSize = least
        if self._browser is not None:
            self._browser.rescale(scale / old)

    def close(self) -> None:
        self._leaving = True
        if self._feeds is not None:
            self._feeds.stop.set()
        if self._browser is not None:
            with contextlib.suppress(Exception):
                self._browser.close()
        # Every window goes, the hidden compact chat too: pywebview ends its loop only when none is left.
        compact = self._compact.window if self._compact is not None else None
        for window in (compact, self._pet, self._window):
            if window is not None:
                with contextlib.suppress(Exception):
                    window.destroy()

    def _on_ui(self, action: Callable[[], object]) -> None:
        winforms.on_thread(self._window.native, action)

    def _make_tray(self) -> None:
        """The icon a hidden window is reached through. Its handlers stay
        referenced here, or .NET would lose them."""
        from System.Drawing import Icon
        from System.Windows.Forms import ContextMenuStrip, NotifyIcon, ToolStripMenuItem, ToolTipIcon

        words = {"open": "Open Mibo", "pet": "Show the pet", "quit": "Quit", **self.words()}
        self._tray_info = ToolTipIcon.Info
        # With the pet the icon shows only while it is hushed, and can bring it back.
        entries = ((words["open"], self._open_click), *(((words["pet"], self._pet_click),) if self.pet else ()),
                   (words["quit"], self._quit_click))

        def make() -> None:
            tray = NotifyIcon()
            tray.Icon = Icon(str(icon()))
            tray.Text = TITLE
            menu = ContextMenuStrip()
            for label, handler in entries:
                item = ToolStripMenuItem(label)
                item.Click += handler
                menu.Items.Add(item)
            tray.ContextMenuStrip = menu
            tray.DoubleClick += self._open_click
            # A press on a notification opens the window it is about.
            tray.BalloonTipClicked += self._open_click
            tray.Visible = False
            self._tray = tray

        self._on_ui(make)

    def _closing(self):
        if self._leaving:
            return None
        if self._pet is not None:
            # The pet is still there: the window only goes away until asked for
            # again, after the pet's head has gone down behind its edge.
            threading.Thread(target=self._go_out, args=("hide",), name="mibo-pet", daemon=True).start()
            return False
        if self._tray is not None and self.background():
            self.hide()
            return False
        self._leaving = True
        return None

    def _sized(self, minimized: bool, maximized: bool | None = None) -> Callable[[], None]:
        def note() -> None:
            self._minimized = minimized
            if maximized is not None:
                self.maximized = maximized
                # Its page draws the bar for it (app.js).
                self._frame_changed()
        return note

    def control(self, action: str) -> bool:
        """What the page's own title bar asks for: one of ACTIONS. False when
        there is no window to do it to."""
        if not self.opened or self._leaving or action not in ACTIONS:
            return False
        try:
            if action == "minimize" and self._attached:
                # The pet's head goes down behind the edge first.
                threading.Thread(target=self._go_out, args=("minimize",), name="mibo-pet",
                                 daemon=True).start()
            elif action == "minimize":
                self._window.minimize()
            elif action == "maximize":
                self._window.maximize()
            elif action == "restore":
                self._window.restore()
            else:
                # As the system's close button: it may hide the window or ask first,
                # so the page is not kept waiting for the answer.
                threading.Thread(target=self._window.destroy, name="mibo-close", daemon=True).start()
        except Exception:
            return False
        return True

    # The title bar the page draws on Windows.

    def _before_show(self) -> None:
        with contextlib.suppress(Exception):
            self._frame = native.strip_title_bar(self._window)
            self.frameless = self._frame is not None

    @property
    def page_url(self) -> str:
        """The address this window loads: `url` and the key its page shows for the bar."""
        return f"{self.url}{'&' if '#' in self.url else '#'}frame={self.frame_key}"

    def is_own_page(self, key: str) -> bool:
        return hmac.compare_digest(str(key or ""), self.frame_key)

    def frame_seen(self) -> None:
        """The page asked how the window stands, so it draws the bar and the buttons."""
        self._frame_seen.set()

    def _framed_again(self) -> None:
        """The window gets its own title bar back."""
        if self.frameless:
            self.frameless = False
            with contextlib.suppress(Exception):
                self._frame[1]()

    def _unless_seen(self) -> None:
        # A page that never came up draws no buttons: nobody is left with a
        # window that cannot be closed.
        if not self._frame_seen.wait(PAGE_WITHIN) and not self._leaving:
            self._framed_again()

    # Opening.

    def run(self) -> bool:
        """Show the window and block until it closes. False when none opened."""
        try:
            import webview
        except Exception as error:
            self.error = repr(error)
            return False
        windows = sys.platform == "win32"
        if windows:
            native.own_process()
        # A file:// page could read any file beside it, ~/mibo/settings.json among them.
        webview.settings["ALLOW_FILE_URLS"] = False
        try:
            self._create(webview, windows)
            with _interrupt(self.close):
                # Private: nothing the page stores outlives the window.
                webview.start(lambda: self._ready(webview, windows), gui=_toolkit(), private_mode=True,
                              storage_path=str(self.storage), icon=str(icon()))
        except Exception as error:
            self.error = repr(error)
            return False
        finally:
            if not self.opened:
                # No window after all: the browser that takes over draws no window bar.
                self.frameless = False
            if self._tray is not None:
                with contextlib.suppress(Exception):
                    self._tray.Visible = False
                    self._tray.Dispose()
        return self.opened

    def _create(self, webview, windows: bool) -> None:
        """The app window, and the pet's beside it, made before the toolkit starts."""
        # WebView2 takes its menu setting from the next load on, so Windows
        # starts on an empty page and `_ready` loads the real one after it.
        self._window = webview.create_window(
            TITLE, None if windows else self.page_url, width=SIZE[0], height=SIZE[1],
            min_size=MIN_SIZE, text_select=True, zoomable=True,
            # Started for the background: no window flashes up before it hides.
            minimized=self.start_hidden and windows, hidden=self.pet)
        if self.pet:
            self._make_pet(webview, TITLE)
        events = self._window.events
        events.closing += self._closing
        events.minimized += self._sized(True)
        events.restored += self._sized(False, False)
        events.maximized += self._sized(False, True)
        if windows:
            events.before_show += self._before_show

    def _ready(self, webview, windows: bool) -> None:
        """On a thread of its own once the toolkit runs: the window counts as opened, or is closed."""
        if not self._window.events.shown.wait(SHOWN_WITHIN):
            self.error = "the window did not appear"
            self.close()
            return
        if self._leaving:
            # Asked to close before there was a window to close.
            self.close()
            return
        # Without WebView2, Windows offers an engine too old for the page.
        if windows and webview.renderer != "edgechromium":
            self.error = "the WebView2 runtime is missing"
            self.close()
            return
        address = urlsplit(self.url)
        origin = f"{address.scheme}://{address.netloc}"
        if windows:
            self._dress(origin)
        self.opened = True
        if self._pet is not None:
            self._start_pet(origin, SHOWN_WITHIN)
        elif self.start_hidden:
            self.hide()

    def _dress(self, origin: str) -> None:
        """On Windows, before the window counts as opened: its menus, tray, pane and watches, and its real page."""
        regions = False
        with contextlib.suppress(Exception):
            if self._window.events.loaded.wait(SHOWN_WITHIN):
                regions = winforms.text_menus(self._window)
        if not regions:
            # The page could not be the bar the window is moved by.
            self._framed_again()
        with contextlib.suppress(Exception):
            self._make_tray()
        with contextlib.suppress(Exception):
            self._make_pane()
        # A player in the page itself (a chat's card, the feed) goes full screen the same way.
        with contextlib.suppress(Exception):
            self._on_ui(self._watch_full_screen)
        with contextlib.suppress(Exception):
            self._on_ui(self._watch_main_scale)
        winforms.own_pages(self._window, origin, self.open_link)
        self._window.load_url(self.page_url)
        if self.frameless:
            threading.Thread(target=self._unless_seen, name="mibo-frame", daemon=True).start()
