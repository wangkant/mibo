"""The pane's menus (browser.Pane): the bar's ··· menu (browsemenu.js) finds in the page and prints it with the
browser's own find bar and print preview, zooms, and lists the downloads (open, show in folder), which go to the
download folder; the page's right-click menu adds 问 Mibo over a selection (the text goes into the chat's box as a
quote, for the person to send or not) and, on a link, a new tab or the system browser.

Zoom is the person's own for the site, as the browser steps it, over the fit to the pane's width when that is on
(the menu's 适应宽度, on until turned off, as mobile browsers lay a desktop site out at a desktop width and show it
whole)."""
from __future__ import annotations

import contextlib
import json
import math
import os
import subprocess
import threading
import time
import webbrowser
from pathlib import Path
from urllib.parse import urlsplit

from . import browsed

# The menu's items this part answers.
MENU = ("fit", "menu", "dl_open", "dl_folder", "find", "print", "zoom_in", "zoom_out", "zoom_reset")
# The browser's own zoom steps (Chromium's), for the menu's − and +.
ZOOM_STEPS = (0.25, 0.33, 0.5, 0.67, 0.75, 0.8, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0, 4.0, 5.0)
# Fit to width: a pane narrower than this many CSS px, what a site laid out for a desktop wants (browse.js
# PAGE_WIDE), zooms the site out until its layout gets this width, so it does not scroll sideways, down to FIT_MIN,
# below which text stops being easy to read and the site lays out narrower instead.
FIT_WIDTH = 1024
FIT_MIN = 0.67
# The downloads the menu lists, newest first (those of private tabs only while the app runs); how often a download
# under way tells its progress.
DOWNLOADS_KEPT = 5
DOWNLOAD_TELL_S = 0.5
# A selection 问 Mibo puts in the chat's box, at most this long.
ASK_MAX = 2000


class MenuPane:
    """The part of browser.Pane behind its menus and its zoom, on the form's thread."""

    def _from_menu(self, action: str, ident: int) -> None:
        """One of the ··· menu's items; `ident` names the download a press in its list is for. Finding, printing and
        zooming need a page."""
        if action == "fit":
            # 适应宽度: the site fitted to the pane's width, or at its own size, from now on.
            self.fit = self._kept["fit"] = not self.fit
            self._keep()
            self._zoom(show=True)
        elif action == "menu":
            # The menu opened: its list again, with any file deleted since.
            self._tell_downloads()
        elif action in ("dl_open", "dl_folder"):
            self._opened(ident, action == "dl_folder")
        elif self._core is None:
            return
        elif action == "find":
            self._find()
        elif action == "print":
            # The browser's own print preview, as Ctrl P opens it.
            from Microsoft.Web.WebView2.Core import CoreWebView2PrintDialogKind
            self._view.Focus()
            self._core.ShowPrintUI(CoreWebView2PrintDialogKind.Browser)
        else:
            self._zoom_step({"zoom_in": 1, "zoom_out": -1}.get(action, 0))

    def _download(self, sender, args) -> None:
        """Every download goes to the download folder and into the menu's list (the browser's own flyout is not
        shown), where its progress and end follow it. One while the character operates waits (a deferral) in
        op["downloads"], the same record, for the person's answer on a card (operate.Hands): saved on yes,
        cancelled on no."""
        from Microsoft.Web.WebView2.Core import CoreWebView2DownloadInterruptReason, CoreWebView2DownloadState
        args.Handled = True
        operation, tab = args.DownloadOperation, self._tab_of(sender)
        self._download_n += 1
        record = {"id": self._download_n, "path": str(args.ResultFilePath), "url": str(operation.Uri),
                  "bytes": int(operation.TotalBytesToReceive or 0), "got": 0, "state": "progress",
                  "private": tab is not None and tab.private, "told": 0.0}
        self._downloads.insert(0, record)
        del self._downloads[DOWNLOADS_KEPT:]

        def changed(sender, _) -> None:
            state = sender.State
            record["path"], record["got"] = str(sender.ResultFilePath), int(sender.BytesReceived)
            record["bytes"] = int(sender.TotalBytesToReceive or 0) or record["bytes"]
            if state == CoreWebView2DownloadState.Completed:
                record["state"] = "done"
            elif state == CoreWebView2DownloadState.Interrupted:
                record["state"] = ("cancelled" if sender.InterruptReason == CoreWebView2DownloadInterruptReason.UserCanceled
                                   else "failed")
            self._tell_downloads(keep=record["state"] != "progress")

        def received(sender, _) -> None:
            record["got"] = int(sender.BytesReceived)
            if time.monotonic() - record["told"] >= DOWNLOAD_TELL_S:
                record["told"] = time.monotonic()
                self._tell_downloads()
        record["handlers"] = (changed, received)
        operation.StateChanged += changed
        operation.BytesReceivedChanged += received
        if self.op is not None:
            record["state"], deferral = "waiting", args.GetDeferral()

            def answer(yes: bool) -> None:
                def finish() -> None:
                    args.Cancel = not yes
                    record["state"] = "progress" if yes else "cancelled"
                    deferral.Complete()
                    self._tell_downloads()
                self.ui(finish)
            record["answer"] = answer
            self.op.setdefault("downloads", []).append(record)
        self._tell_downloads()

    def _tell_downloads(self, keep: bool = False) -> None:
        """The menu's list as it stands (a file deleted since is marked); with `keep` it is kept too, without
        those of private tabs and those still under way."""
        self.tell({"downloads": [{"id": r["id"], "name": Path(r["path"]).name, "state": r["state"], "bytes": r["bytes"],
                                  "got": r["got"], "gone": r["state"] == "done" and not Path(r["path"]).exists()}
                                 for r in self._downloads]})
        if keep:
            self._kept["downloads"] = [{k: r[k] for k in ("path", "url", "bytes", "got", "state")}
                                       for r in self._downloads if not r["private"] and r["state"] in ("done", "failed")]
            self._keep()

    def _opened(self, ident: int, folder: bool) -> None:
        """A download in the menu's list opened (once it is done), or shown in its folder (the folder alone when
        the file is gone): the person's own press."""
        record = next((r for r in self._downloads if r["id"] == ident), None)
        if record is None:
            return
        path = Path(record["path"])
        if folder:
            subprocess.Popen(f'explorer /select,"{path}"' if path.exists() else f'explorer "{path.parent}"')
        elif record["state"] == "done" and path.exists():
            os.startfile(str(path))

    def _menu(self, sender, args) -> None:
        """The page's right-click menu: 问 Mibo first over a selection; on a link, 在新标签页中打开链接 in place of the
        browser's new window, and 在系统浏览器中打开链接. The rest is the browser's own."""
        from Microsoft.Web.WebView2.Core import CoreWebView2ContextMenuItemKind as Kind

        from . import i18n
        target, items, lang = args.ContextMenuTarget, args.MenuItems, i18n.lang()

        def item(key: str, act: str = "", value: str = ""):
            made = sender.Environment.CreateContextMenuItem(i18n.t(f"browse.{key}", lang) if key else "", None,
                                                            Kind.Command if key else Kind.Separator)
            if key:
                made.CustomItemSelected += lambda s, a: self._picked(act, value)
            return made
        link = str(target.LinkUri or "") if target.HasLinkUri else ""
        if browsed.web(link):
            at = next((n for n in range(items.Count) if str(items[n].Name) == "openLinkInNewWindow"), 0)
            if at < items.Count and str(items[at].Name) == "openLinkInNewWindow":
                items.RemoveAt(at)
            items.Insert(at, item("linkSystem", "system", link))
            items.Insert(at, item("linkTab", "tab", link))
        selection = str(target.SelectionText or "").strip() if target.HasSelection else ""
        if selection:
            items.Insert(0, item(""))
            items.Insert(0, item("askSelection", "ask", selection))

    def _picked(self, act: str, value: str) -> None:
        """One of the page's own right-click items: the selection to the chat's box as a quote (the page's text,
        for the person to send or not), a link in a tab behind the one in front, or in the system browser."""
        if act == "ask":
            self.tell({"ask": value[:ASK_MAX]})
        elif act == "tab":
            tab = self._new_tab(self.private)
            tab.url = tab.pending = value
            self._make(tab)
            self.tell(self._strip())
        elif act == "system":
            threading.Thread(target=webbrowser.open, args=(value,), name="mibo-browser", daemon=True).start()

    def _find(self) -> None:
        """The menu's 查找: the browser's own find bar, as Ctrl F opens it, with the page's selection in it."""
        from System import Action, String
        from System.Threading.Tasks import Task, TaskScheduler
        core, view = self._core, self._view

        def start(task) -> None:
            term = ""
            with contextlib.suppress(Exception):
                term = str(json.loads(str(task.Result)) or "").strip()
            options = core.Environment.CreateFindOptions()
            options.FindTerm = term[:200]
            options.ShouldHighlightAllMatches = True
            options.SuppressDefaultFindDialog = False
            view.Focus()
            core.Find.StartAsync(options)
        core.ExecuteScriptAsync("getSelection().toString()").ContinueWith(
            Action[Task[String]](start), TaskScheduler.FromCurrentSynchronizationContext())

    def _zoom_step(self, step: int) -> None:
        """The menu's −, + and its percentage: the site's own zoom one browser step down or up, or none (0)."""
        own = self._zooms().get(self._host(), 1.0)
        steps = ZOOM_STEPS if step > 0 else ZOOM_STEPS[::-1]
        self._set_own_zoom(next((z for z in steps if (z - own) * step > 0.001), own) if step else 1.0)

    def _set_own_zoom(self, own: float) -> None:
        """The person's own zoom for the site in front (none at 1), shown, and kept outside private mode."""
        host, zooms = self._host(), self._zooms()
        if abs(own - 1.0) < 0.005:
            zooms.pop(host, None)
        else:
            zooms[host] = own
        self._zoom(show=True)
        if not self.private:
            self._keep()

    def _zooms(self) -> dict:
        """The person's own zoom per site: kept, or in private mode for this run only."""
        return self._zoom_private if self.private else self._kept["zoom"]

    def _fit_factor(self) -> float:
        if not self.fit or self._box is None:
            return 1.0
        # The site's CSS px at zoom 1 are the monitor's, whatever the app page's own zoom. The form's scale is the
        # one it was made on, and the WebView may draw at the app page's (a window far off the screens): the larger
        # of the two never leaves the site wider than the pane.
        wide = self._box.Width / max(self.form._scale, self._scale)
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
        # A tab behind is zoomed again as it comes to the front.
        if view is None or (sender is not None and not view.Equals(sender)):
            return
        now = float(view.ZoomFactor)
        if abs(now - self._zoom_set) <= 0.0005:
            return
        if self._full or self._navigating:
            self._zoom()
            return
        self._set_own_zoom(round(now / self._fit_factor(), 3))
