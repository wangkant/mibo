"""Reading with the person's session, out of sight (Windows): `Reader` reads one address in a second WebView2 on the
pane's folder, made for the read and gone after, and `Feeds` reads the person's own feed on the sites where they
turned that on, in the background, through the Reader."""
from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

from . import browsed
from .panereading import page_of
from .webview2 import CDP_S, call_devtools, make_view, seal

# Reading out of sight: how long a page may take.
READ_WITHIN_S = 25.0
# A feed read in the background (Feeds): how often it is looked at, how often one site's is read, how many reads
# a day, how many of its rows are kept, and the walls that turn it off.
FEED_LOOK_S = 60.0
FEED_EVERY_S = 30 * 60.0
FEED_DAY_MAX = 24
FEED_ROWS = 20
FEED_STOPS = ("verification", "sign_in", "sign_in_overlay", "robots")


class Reader:
    """Reads with the person's session (the pane's WebView2 folder), out of sight: a hidden WebView2 in
    `form`, made for one site and disposed after (web/tabs.HiddenTab reads through it). Read only: it goes
    only to that site's addresses, and requests to other sites, and any but GET, are refused, so the
    person's cookies go to that site alone; a move to another site (a sign-in elsewhere) stops the read.
    Pace (browsed.Pace): one read of a site at a time with a pause between, a few sites side by side, a day's
    cap per site, and a site whose check or sign-in wall showed is not read again for a while. Cookies and
    storage are never read out: only the page's text leaves."""

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
        from .web import read as reading
        from .web.tabs import HiddenTab
        with self.pace.slot(url):
            refused = self.pace.refuse(url)
            if refused:
                return {"error": refused}
            self.pace.wait(url)
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
            # The whole text it read: the character's reader (web/pagetext.py) fits it to the model.
            return page_of(page.url, page.data, page.rows, start, most=len(page.data.get("text") or ""),
                           pictures=background)


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
        threading.Thread(target=self._run, name="mibo-feeds", daemon=True).start()

    def _run(self) -> None:
        while not self.stop.wait(FEED_LOOK_S):
            for key, feed in feeds_on(self.runtime).items():
                if self.stop.is_set() or not self.shared():
                    break
                self._read(key, feed)

    def _read(self, key: str, feed: dict) -> None:
        """One site's feed, when it is due: read, noted on the site's card, and its rows kept as finds."""
        from .web import sites
        today = time.strftime("%Y-%m-%d")
        n = feed.get("n", 0) if feed.get("day") == today else 0
        if n >= FEED_DAY_MAX or time.time() - float(feed.get("at") or 0) < FEED_EVERY_S:
            return
        page = self.reader.read(feed["url"], screens=1, runtime=self.runtime, background=True)
        error = page.get("error", "")

        def note(card: dict) -> None:
            kept = card.setdefault("feed", {})
            kept.update(at=time.time(), day=today, n=n + 1, last=error or "ok")
            if error in FEED_STOPS:
                kept.update(on=False, stopped=error)
        sites._change(self.runtime, key, note)
        if not error:
            keep_finds(self.runtime, key, page.get("rows") or [])


def feeds_on(runtime: Path) -> dict:
    """{site key: its feed} for the sites whose background reading the person turned on."""
    from .web import sites
    return {key: card["feed"] for key, card in sites.load(runtime).items()
            if isinstance(card, dict) and isinstance(card.get("feed"), dict) and card["feed"].get("on")
            and browsed.web(card["feed"].get("url", ""))}


def keep_finds(runtime: Path, key: str, rows: list) -> int:
    """A feed's rows as library finds of that site (source "feed <site>"); how many were new. A row whose link has
    a platform's player (a Douyin or TikTok video) is a video with that player, so it plays on its card. A row's
    cover is fetched as a visitor would (the row's page as referer, no cookies) and kept with it."""
    from .library import Item, Library, item_id
    from .pagefacts import site_name
    from .players import player_for
    from .sources import base, catalog
    from .web import sites
    library, new, covered = Library(runtime), 0, []
    for row in rows[:FEED_ROWS]:
        link = str(row.get("link") or "")
        if not row.get("title") or not browsed.web(link) or sites.key_of(link) != key or browsed.secret(link):
            continue
        if library.get(item_id(link)) is None:
            player = player_for(link)
            item = library.add(Item(url=link, site=site_name(link), kind="video" if player else "post", embed=player,
                                    title=str(row["title"])[:300], author=str(row.get("author") or "")[:200],
                                    source=f"feed {key}"))
            if str(row.get("picture") or "").startswith(("https://", "http://", "//")):
                covered.append(base.Find(item, base.secure(row["picture"])))
            new += 1
    if covered:
        asyncio.run(catalog.cover_kept(runtime, covered))
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
        from System.Drawing import Rectangle
        view = make_view(self.reader.folder)
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
        seal(core)
        settings = core.Settings
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
        if (str(request.Method).upper() != "GET" or not browsed.web(address)
                or browsed.site_of(urlsplit(address).hostname or "") != self.site):
            args.Response = sender.Environment.CreateWebResourceResponse(None, 403, "Blocked", "")

    def _starting(self, sender, args) -> None:
        address = str(args.Uri)
        if not browsed.web(address):
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
        # Refused for this read only: the person is asked when they visit the site themselves.
        from Microsoft.Web.WebView2.Core import CoreWebView2PermissionState
        args.State = CoreWebView2PermissionState.Deny
        args.SavesInProfile = False

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
        return call_devtools(self.reader.ui, lambda: self.core, method, params, CDP_S)

    def close(self) -> None:
        def drop() -> None:
            view, self.view, self.core = self.view, None, None
            if view is not None:
                self.reader.form.Controls.Remove(view)
                view.Dispose()
        self.reader.ui(drop)
