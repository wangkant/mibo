"""The WinForms form and the WebView2 of a pywebview window on Windows: work done on the form's own thread,
the page's right-click menus, and the window kept on mibo's own pages. pywebview loads pythonnet, which these
import when called."""
from __future__ import annotations

import contextlib
from collections.abc import Callable
from urllib.parse import urlsplit


def on_thread(form, action: Callable[[], object]) -> None:
    """Run `action` on the form's own thread and wait for it; what it returns is dropped."""
    from System import Func, Type

    def run() -> None:
        action()

    form.Invoke(Func[Type](run))


def text_menus(window) -> bool:
    """pywebview turns right-click off on Windows. Put it back where there is
    text to paste into or to copy: an API key is often pasted that way.
    Also lets the page mark part of itself as the bar the window is moved by;
    True when this WebView2 can do that."""
    form = window.native
    found = {"regions": False}

    def on_menu(sender, args) -> None:
        target = args.ContextMenuTarget
        args.Handled = not (target.IsEditable or target.HasSelection)

    def enable() -> None:
        core = form.browser.webview.CoreWebView2
        core.Settings.AreDefaultContextMenusEnabled = True
        core.ContextMenuRequested += on_menu
        # `app-region: drag` in the page; an older runtime has no such setting.
        with contextlib.suppress(Exception):
            core.Settings.IsNonClientRegionSupportEnabled = True
            found["regions"] = bool(core.Settings.IsNonClientRegionSupportEnabled)

    on_thread(form, enable)
    return found["regions"]


def own_pages(window, origin: str, open_link: Callable[[str], None]) -> None:
    """Keep a Windows window on mibo's own pages. Any page it loads gets
    pywebview's bridge to Python, so nothing dropped on it loads, it goes to no
    other site, and a page's new windows go to `open_link` when they are web
    addresses, never to whatever else Windows would start for them.
    The players' iframes are frames, not the window's page, and still load."""
    form = window.native

    def on_navigation(sender, args) -> None:
        address = urlsplit(str(args.Uri))
        args.Cancel = f"{address.scheme}://{address.netloc}" != origin

    def on_new_window(sender, args) -> None:
        args.Handled = True
        address = str(args.Uri)
        if urlsplit(address).scheme in ("http", "https"):
            open_link(address)

    def hold() -> None:
        form.browser.webview.AllowExternalDrop = False
        core = form.browser.webview.CoreWebView2
        core.NavigationStarting += on_navigation
        # pywebview's own handler gives any address at all to the system.
        core.NewWindowRequested -= form.browser.on_new_window_request
        core.NewWindowRequested += on_new_window

    on_thread(form, hold)
