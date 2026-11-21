"""The app browser's ··· menu, its right-click items and its downloads list. Windows only: the real app window,
off screen, with no figure on the desktop.

    python tools/panemenu.py <scratch home> --out <folder> [--site-port 59652] [--model-port 59653]

A practice page of its own on this computer, with a paragraph, a link and a file to download. It counts which of
find, print, zoom, copy link, open in the system browser and the downloads list can be reached from the bar, then
uses each one; it right-clicks a selection and a link (the menu itself is not shown: the items are read and the
press is made in code), and downloads the file into <folder>/downloads. The clipboard is put back as it was.
results.json in <folder> holds the numbers."""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PAGES = {
    "/a.html": b"""<!doctype html><title>Page A</title><body style="font:16px sans-serif;padding:24px">
<p id="text">Lorem ipsum dolor sit amet. Lorem again, and lorem a third time.</p>
<p><a id="link" href="b.html">Page B</a></p>
<p><a id="dl" href="notes.txt">notes.txt</a></p>""",
    "/b.html": b"<!doctype html><title>Page B</title><p>B",
}
FILE = b"practice download\n" * 64
# What the bar offers, by name: a control in the bar itself or in its menu (data-act), and the old bar's buttons.
FEATURES = {"find": "[data-act=find]", "print": "[data-act=print]", "zoom": "[data-act=zoom_in]",
            "copy": "[data-act=copy]", "system": "[data-act=system], .browse-bar .browse-system",
            "downloads": ".browse-download"}
REACH = ("(() => { const out = {}; for (const [name, sel] of Object.entries(%s)) out[name] = [...document.querySelectorAll(sel)]"
         ".some((e) => e.getClientRects().length && !e.closest('[hidden]')); return out; })()")


class Site(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        body = FILE if path == "/notes.txt" else PAGES.get(path, b"")
        self.send_response(200 if body else 404)
        if path == "/notes.txt":
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Disposition", "attachment; filename=notes.txt")
        else:
            self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass


def clipboard(d, put=None) -> tuple:
    """On the window's thread: `put` set first (text, "" to empty it, or what it held as a whole), then its text
    and what it holds as a whole, to put back after."""
    from System.Windows.Forms import Clipboard
    box: dict = {}

    def run() -> None:
        if put == "":
            Clipboard.Clear()
        elif isinstance(put, str):
            Clipboard.SetText(put)
        elif put is not None:
            Clipboard.SetDataObject(put, True)
        box["text"] = str(Clipboard.GetText()) if Clipboard.ContainsText() else ""
        box["all"] = Clipboard.GetDataObject()
    d._ui(run)
    return box["text"], box["all"]


def click_in_page(d, selector: str, button: str = "left") -> bool:
    """A real click (DevTools input) on an element of the site in front."""
    pane = d.app._browser
    answer = pane.cdp("Runtime.evaluate", {"expression": f"(() => {{ const r = document.querySelector({json.dumps(selector)})"
                                           ".getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()",
                                           "returnByValue": True})
    at = (answer.get("result") or {}).get("value")
    if not at:
        return False
    for kind in ("mouseMoved", "mousePressed", "mouseReleased"):
        pane.cdp("Input.dispatchMouseEvent", {"type": kind, "x": at[0], "y": at[1], "button": button,
                                              "buttons": (1 if button == "left" else 2) if kind == "mousePressed" else 0,
                                              "clickCount": 1})
    return True


def watch_menus(d) -> list:
    """Each right-click menu the site asks for, after the app has changed it: its items and what was under the
    pointer. The menu is not shown (Handled)."""
    seen: list = []

    def on(sender, args) -> None:
        target = args.ContextMenuTarget
        seen.append({"items": [(str(i.Name), str(i.Label)) for i in args.MenuItems],
                     "selection": str(target.SelectionText or "") if target.HasSelection else "",
                     "link": str(target.LinkUri or "") if target.HasLinkUri else "", "args": args})
        args.Handled = True

    def add() -> None:
        d.app._browser._core.ContextMenuRequested += on
    d._ui(add)
    return seen


def browser_windows(d) -> list:
    """The visible windows of the site's browser process (the browser's own find bar is one): their class names."""
    import ctypes
    from ctypes import wintypes
    box: dict = {}
    d._ui(lambda: box.update(pid=int(d.app._browser._core.BrowserProcessId)))
    found: list = []
    user32 = ctypes.windll.user32

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == box["pid"] and user32.IsWindowVisible(hwnd):
            name = ctypes.create_unicode_buffer(128)
            user32.GetClassNameW(hwnd, name, 128)
            found.append(name.value)
        return True
    user32.EnumWindows(each, 0)
    return found


def menu(d, open_it: bool = True) -> None:
    """The bar's ··· menu opened (or closed), where there is one."""
    shown = d.shown(".browse-menu")
    if open_it != shown and d.shown(".browse-more"):
        d.click(".browse-more")
        time.sleep(0.5)


def walk(d, results: dict, downloads: Path) -> None:
    pane = d.app._browser
    d.app.open_link(SITE + "/a.html")
    d.until("document.querySelector('.browse') && !document.querySelector('.browse').hidden", 20)
    deadline = time.time() + 15
    while time.time() < deadline and "Page A" not in str(pane._core.DocumentTitle if pane._core is not None else ""):
        time.sleep(0.4)
    time.sleep(1)
    d._ui(lambda: setattr(pane._core.Profile, "DefaultDownloadFolderPath", str(downloads)))

    # 1. What the bar offers.
    menu(d)
    reach = d.js(REACH % json.dumps(FEATURES)) or {}
    d.shot("menu")
    results["reach"] = reach

    # 2. Find: the selection is what is looked for.
    pane.cdp("Runtime.evaluate", {"expression": "(() => { const r = document.createRange(); r.setStart(document.getElementById('text').firstChild, 0);"
                                                " r.setEnd(document.getElementById('text').firstChild, 5); getSelection().removeAllRanges(); getSelection().addRange(r); })()"})
    matches, bar = 0, []
    windows = browser_windows(d)
    if d.shown(".browse-menu [data-act=find]"):
        d.click(".browse-menu [data-act=find]")
        time.sleep(1.5)
        box: dict = {}
        d._ui(lambda: box.update(n=int(pane._core.Find.MatchCount)))
        matches = box["n"]
        bar = [w for w in browser_windows(d) if w not in windows]
        d.shot("find")
        d._ui(lambda: pane._core.Find.Stop())
    results["find"] = {"matches": matches, "find_bar": bar, "menu_closed": not d.shown(".browse-menu")}

    # 3. Zoom from the menu.
    zoom: dict = {}
    menu(d)
    d._ui(lambda: zoom.update(before=float(pane._view.ZoomFactor)))
    if d.shown(".browse-menu [data-act=zoom_in]"):
        d.click(".browse-menu [data-act=zoom_in]")
        time.sleep(0.6)
        d._ui(lambda: zoom.update(after_in=float(pane._view.ZoomFactor)))
        zoom["shown"] = d.text(".browse-menu .browse-menu-zoom-value")
        d.click(".browse-menu [data-act=zoom_reset]")
        time.sleep(0.6)
        d._ui(lambda: zoom.update(after_reset=float(pane._view.ZoomFactor)))
    results["zoom"] = zoom

    # 4. Copy link, the clipboard put back after.
    _, kept = clipboard(d)
    menu(d)
    copied = ""
    if d.shown(".browse-menu [data-act=copy]"):
        clipboard(d, "")
        d.click(".browse-menu [data-act=copy]")
        time.sleep(0.6)
        copied, _ = clipboard(d)
    clipboard(d, kept)
    results["copy"] = {"copied": copied, "ok": copied == SITE + "/a.html"}

    # 5. The system browser (the driver keeps the address instead of opening one).
    menu(d)
    before = len(d.links)
    for sel in (".browse-menu [data-act=system]", ".browse-bar .browse-system"):
        if d.shown(sel):
            d.click(sel)
            break
    time.sleep(1)
    results["system"] = {"opened": d.links[before:], "pane_kept": bool(pane._tabs)}
    if not pane._tabs:
        d.app.open_link(SITE + "/a.html")
        deadline = time.time() + 15
        while time.time() < deadline and "Page A" not in str(pane._core.DocumentTitle if pane._core is not None else ""):
            time.sleep(0.4)

    # 6. Right-click on a selection and on a link.
    seen = watch_menus(d)
    pane.cdp("Runtime.evaluate", {"expression": "(() => { const r = document.createRange(); r.selectNodeContents(document.getElementById('text'));"
                                                " getSelection().removeAllRanges(); getSelection().addRange(r); })()"})
    click_in_page(d, "#text", "right")
    time.sleep(1)
    click_in_page(d, "#link", "right")
    time.sleep(1)
    on_text = seen[0] if seen else {}
    on_link = seen[1] if len(seen) > 1 else {}
    results["context"] = {"text_items": [n for n, _ in on_text.get("items", [])],
                          "text_labels": [label for _, label in on_text.get("items", [])][:4],
                          "link_items": [n for n, _ in on_link.get("items", [])],
                          "link_labels": [label for _, label in on_link.get("items", [])][:4]}
    # The press on 问 Mibo and on 在新标签页中打开链接, made in code: the native menu is not shown here.
    asked = ""
    if hasattr(pane, "_picked") and on_text.get("selection"):
        d._ui(lambda: pane._picked("ask", on_text["selection"]))
        time.sleep(1.2)
        asked = d.js("document.querySelector('#chat-view .chat:not([hidden]) .chat-input')?.value || ''") or ""
        d.shot("ask")
    tabs_before = len(pane._tabs)
    if hasattr(pane, "_picked") and on_link.get("link"):
        d._ui(lambda: pane._picked("tab", on_link["link"]))
        time.sleep(2.5)
    results["context"].update(asked=asked, quoted=asked.startswith("> Lorem ipsum"),
                              new_tab=len(pane._tabs) - tabs_before,
                              front_kept=pane.address().endswith("/a.html"))
    if len(pane._tabs) > tabs_before:
        pane.do("tab_close", pane._tabs[-1].id if pane._tab is not pane._tabs[-1] else pane._tab.id)
        time.sleep(1)

    # 7. A download: where it went, and the list in the menu (opening its folder is recorded, not done).
    opened: list = []
    import os
    real = (os.startfile, subprocess.Popen)
    os.startfile = lambda path, *a: opened.append(("open", str(path)))
    subprocess.Popen = lambda args, *a, **k: opened.append(("folder", args))
    try:
        click_in_page(d, "#dl")
        deadline = time.time() + 15
        while time.time() < deadline and not (downloads / "notes.txt").exists():
            time.sleep(0.4)
        time.sleep(1.5)
        menu(d)
        rows = d.js("[...document.querySelectorAll('.browse-download')].map((r) => r.textContent.trim())") or []
        reach2 = d.js(REACH % json.dumps(FEATURES)) or {}
        d.shot("downloads")
        if d.shown(".browse-download [data-act=dl_folder]"):
            d.click(".browse-download [data-act=dl_folder]")
            time.sleep(0.8)
    finally:
        os.startfile, subprocess.Popen = real
    results["downloads"] = {"saved": (downloads / "notes.txt").exists(), "rows": rows, "folder_asked": opened}
    results["reach"]["downloads"] = bool(reach2.get("downloads"))

    # 8. Print: the browser's own print preview (seen in the picture).
    menu(d)
    printed = False
    if d.shown(".browse-menu [data-act=print]"):
        d.click(".browse-menu [data-act=print]")
        time.sleep(2.5)
        d.shot("print")
        printed = True
    results["print"] = {"asked": printed}
    results["reach_count"] = sum(bool(v) for v in results["reach"].values())
    d.log(json.dumps(results, ensure_ascii=False))


def main() -> int:
    global SITE
    home, out = Path(sys.argv[1]), Path(sys.argv[sys.argv.index("--out") + 1])
    site_port = int(sys.argv[sys.argv.index("--site-port") + 1]) if "--site-port" in sys.argv else 59652
    model_port = int(sys.argv[sys.argv.index("--model-port") + 1]) if "--model-port" in sys.argv else 59653
    SITE = f"http://127.0.0.1:{site_port}"
    downloads = (out / "downloads").resolve()
    downloads.mkdir(parents=True, exist_ok=True)
    import window_driver

    from mibo import window as appwindow
    from mibo.welcome import save_app_settings
    desktop = home / "runtime" / "desktop"
    desktop.mkdir(parents=True, exist_ok=True)
    save_app_settings(desktop, toured=True, pet_shown=False)
    made = appwindow.AppWindow.__init__

    def no_figure(self, *args, **kwargs):
        made(self, *args, **kwargs)
        self.pet = False
    appwindow.AppWindow.__init__ = no_figure
    window_driver.ThreadingHTTPServer = lambda address, handler: ThreadingHTTPServer((address[0], model_port), handler)

    site = ThreadingHTTPServer(("127.0.0.1", site_port), Site)
    threading.Thread(target=site.serve_forever, daemon=True).start()
    results: dict = {}
    failed = window_driver.run(home, lambda d: walk(d, results, downloads), out=out, lang="zh")
    site.shutdown()
    site.server_close()
    (out / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=1))
    return failed


SITE = ""

if __name__ == "__main__":
    raise SystemExit(main())
