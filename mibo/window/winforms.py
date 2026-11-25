"""The WinForms form and the WebView2 of a pywebview window on Windows: work done on the form's own thread,
the page's right-click menus, the window kept on mibo's own pages, and its page at rest while out of sight.
pywebview loads pythonnet, which these import when called."""
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


def rest(view) -> None:
    """On the form's thread, before its window goes out of sight: the WebView hidden first (hidden after its
    window, it would never learn it is out of sight, and only a WebView that knows suspends), then kept to little
    memory and its page suspended, which runs no script until it wakes."""
    view.Visible = False
    # An older WebView2 runtime has neither.
    with contextlib.suppress(Exception):
        from Microsoft.Web.WebView2.Core import CoreWebView2MemoryUsageTargetLevel
        view.CoreWebView2.MemoryUsageTargetLevel = CoreWebView2MemoryUsageTargetLevel.Low
        view.CoreWebView2.TrySuspendAsync()


def wake(view) -> None:
    """On the form's thread: the WebView's memory as before and its page resumed, then shown."""
    with contextlib.suppress(Exception):
        from Microsoft.Web.WebView2.Core import CoreWebView2MemoryUsageTargetLevel
        core = view.CoreWebView2
        core.MemoryUsageTargetLevel = CoreWebView2MemoryUsageTargetLevel.Normal
        if core.IsSuspended:
            core.Resume()
    view.Visible = True


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
