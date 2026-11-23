"""Tabs in the app's browser: a link a site opens in a new tab, a sign-in popup that hands its result back to the
page that opened it, the private page, and the keys. Windows only: the real app window, off screen, with no
figure on the desktop.

    python tools/panetabs.py <scratch home> --out <folder> [--site-port 59647] [--model-port 59649]

A practice site of its own on this computer: page A has a link with target=_blank, a "Sign in with Provider"
button that opens the provider in a popup (window.open), and a half-filled field; the provider page sends its
answer back through window.opener and closes itself. results.json in <folder> holds the numbers."""
from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PAGES = {
    "/a.html": b"""<!doctype html><title>Page A</title><body style="font:16px sans-serif;padding:24px">
<p><input id="q" placeholder="half filled"></p>
<p><a id="blank" href="b.html" target="_blank">B in a new tab</a></p>
<p><button id="signin" onclick="window.open('provider.html', 'signin', 'width=480,height=600')">Sign in with Provider</button></p>
<script>addEventListener('message', (e) => { if (e.data && e.data.user) document.title = 'Signed in: ' + e.data.user; });</script>""",
    "/b.html": b"<!doctype html><title>Page B</title><p>B",
    "/provider.html": b"""<!doctype html><title>Provider</title><p>Signing in ...
<script>setTimeout(() => { if (window.opener) { window.opener.postMessage({user: 'demo'}, '*'); window.close(); }
else document.title = 'Provider: no opener'; }, 800);</script>""",
}
# The tabs the strip shows, and the private page's mark.
STRIP = "document.querySelectorAll('.browse-tab').length"
ACTIVE = ("(() => { const t = document.querySelector('.browse-tab.active'); return t ? t.textContent.trim() : ''; })()")


class Site(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = PAGES.get(self.path.split("?")[0], b"")
        self.send_response(200 if body else 404)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass


def views(d) -> list:
    """Every site view in the window (the app page's own left out): [WebView2, CoreWebView2 or None]."""
    from Microsoft.Web.WebView2.WinForms import WebView2
    found: list = []

    def read() -> None:
        form = d.app._window.native
        found.extend((control, control.CoreWebView2) for control in form.Controls
                     if isinstance(control, WebView2) and not control.Equals(form.browser.webview))
    d._ui(read)
    return found


def ask(d, core, script: str):
    """`script` run in the page of `core`; its JSON answer, None when it gave none."""
    from mibo import webview2
    asked: list = []
    d._ui(lambda: asked.append(webview2.run_script(core, script)))
    raw = webview2.script_answer(asked[0] if asked else None, 8)
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return None


def pages(d) -> list[dict]:
    """What each site view holds: its address, title, whether it is shown, and page A's mark and field."""
    rows = []
    for view, core in views(d):
        if core is None:
            rows.append({"url": "", "shown": False})
            continue
        box: dict = {}
        d._ui(lambda core=core, view=view, box=box: box.update(url=str(core.Source), title=str(core.DocumentTitle),
                                                      shown=bool(view.Visible)))
        facts = ask(d, core, "({mark: window.__mark || 0, field: document.getElementById('q')?.value || ''})") or {}
        rows.append({**box, **facts})
    return rows


def kept_a(rows: list) -> dict | None:
    """Page A as it was left: the same document (its mark) with the field still filled."""
    return next((r for r in rows if r.get("url", "").endswith("/a.html") and r.get("mark") == 1), None)


def click_in_page(d, selector: str) -> bool:
    """A real click (DevTools input, a user gesture) on an element of the page in front."""
    pane = d.app._browser
    answer = pane.cdp("Runtime.evaluate", {"expression": f"(() => {{ const r = document.querySelector({json.dumps(selector)})"
                                           ".getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()",
                                           "returnByValue": True})
    at = (answer.get("result") or {}).get("value")
    if not at:
        return False
    for kind in ("mouseMoved", "mousePressed", "mouseReleased"):
        pane.cdp("Input.dispatchMouseEvent", {"type": kind, "x": at[0], "y": at[1], "button": "left",
                                              "buttons": 1 if kind == "mousePressed" else 0, "clickCount": 1})
    return True


def press(d, key: str, shift: bool = False) -> None:
    """Ctrl+<key> in the site, as WebView2 hands the browser's own keys on (AcceleratorKeyPressed -> KeyDown)."""
    from System.Windows.Forms import Keys
    args = SimpleNamespace(Control=True, Alt=False, Shift=shift, KeyCode=getattr(Keys, key), Handled=False,
                           SuppressKeyPress=False)
    d._ui(lambda: d.app._browser._key(None, args))


def open_a(d) -> None:
    d.app.open_link(SITE + "/a.html")
    d.until("document.querySelector('.browse') && !document.querySelector('.browse').hidden", 20)
    deadline = time.time() + 15
    while time.time() < deadline and not any(r.get("url", "").endswith("/a.html") and r.get("title") for r in pages(d)):
        time.sleep(0.5)
    # The mark is this document's own: a page loaded again has none.
    d.app._browser.cdp("Runtime.evaluate", {"expression": "window.__mark = 1; document.getElementById('q').value = 'half typed'"})


def to_a(d) -> None:
    """Back to page A: its tab in the strip where there is one, else page A opened again (as before tabs)."""
    tab = ("(() => { const t = [...document.querySelectorAll('.browse-tab-go')].find((n) => /Page A|Signed in/.test(n.title));"
           " if (!t) return false; t.click(); return true; })()")
    if not (kept_a(pages(d)) and d.js(tab)):
        open_a(d)
    time.sleep(1.5)


def walk(d, results: dict) -> None:
    open_a(d)
    results["start"] = {"views": len(views(d)), "strip": d.js(STRIP)}

    # 1. A link with target=_blank.
    click_in_page(d, "#blank")
    time.sleep(3)
    rows = pages(d)
    results["blank_link"] = {"views": len(rows), "strip": d.js(STRIP), "active": d.app._browser.address(),
                             "a_kept": bool(kept_a(rows)), "b_open": any(r.get("url", "").endswith("/b.html") for r in rows)}
    d.shot("blank-link")
    d.log("blank_link: " + json.dumps(results["blank_link"]))

    # 2. Sign in with a provider's popup.
    to_a(d)
    before = len(views(d))
    click_in_page(d, "#signin")
    time.sleep(0.4)
    during = pages(d)
    time.sleep(4)
    rows = pages(d)
    a = kept_a(rows) or {}
    results["popup_signin"] = {"views_before": before, "views_during": len(during), "views_after": len(rows),
                               "provider_had_opener": not any("no opener" in r.get("title", "") for r in rows),
                               "a_title": a.get("title", ""), "finished": a.get("title") == "Signed in: demo",
                               "popup_closed": not any(r.get("url", "").endswith("/provider.html") for r in rows),
                               "active": d.app._browser.address()}
    d.log("popup_signin: " + json.dumps(results["popup_signin"]))

    # 3. Private: the page in front, its field half filled, and the ··· menu's private tab.
    to_a(d)
    d.app._browser.cdp("Runtime.evaluate", {"expression": "document.getElementById('q').value = 'half typed'"})
    d.click(".browse-more")
    d.click(".browse-menu [data-act=private]")
    time.sleep(3)
    rows = pages(d)
    a = kept_a(rows) or {}
    results["private"] = {"views": len(rows), "a_kept": bool(a), "field_kept": a.get("field") == "half typed",
                          "private_now": bool(d.app._browser.private), "active": d.app._browser.address(),
                          "strip": d.js(STRIP)}
    d.shot("private")
    d.log("private: " + json.dumps(results["private"]))
    # The private tab with nothing in it goes again (Ctrl+W), where one was opened for it.
    if results["private"]["strip"]:
        press(d, "W")
        time.sleep(1.5)

    # 4. The keys: Ctrl+T, Ctrl+W, Ctrl+Shift+T.
    to_a(d)
    n0 = d.js(STRIP) or 0
    press(d, "T")
    time.sleep(1.2)
    n1 = d.js(STRIP) or 0
    focused = bool(d.js("document.activeElement?.classList.contains('browse-address') || false"))
    d.key("Escape", 27)
    press(d, "W")
    time.sleep(1.2)
    n2 = d.js(STRIP) or 0
    to_a(d)
    press(d, "W")
    time.sleep(1.5)
    after_close = pages(d)
    press(d, "T", shift=True)
    time.sleep(3)
    reopened = pages(d)
    results["keys"] = {"strip_before": n0, "after_ctrl_t": n1, "address_focused": focused, "after_ctrl_w": n2,
                       "a_closed": not any(r.get("url", "").endswith("/a.html") for r in after_close),
                       "a_reopened": any(r.get("url", "").endswith("/a.html") for r in reopened),
                       "reopened_private": bool(d.app._browser.private)}
    d.log("keys: " + json.dumps(results["keys"]))

    # 5. Reading and operating follow the tab in front.
    from mibo.web.tabs import PaneTab
    pane = d.app._browser
    rows = pages(d)
    reading = (pane._reading or {}).get("url", "")
    results["bound"] = {"tabs": len(rows), "front": pane.address(), "reading": reading,
                        "pane_tab": PaneTab(pane).url, "shown": [r.get("url") for r in rows if r.get("shown")]}
    results["bound"]["ok"] = (results["bound"]["front"] == results["bound"]["reading"] == results["bound"]["pane_tab"]
                              and results["bound"]["shown"] == [results["bound"]["front"]])
    # A run under way pauses when another tab comes to the front (the person's press on it in the strip).
    if d.js(STRIP) and d.js(STRIP) > 1:
        pane.operate("practice run")
        d.js("document.querySelector('.browse-tab:not(.active) .browse-tab-go').click()")
        time.sleep(1.2)
        results["bound"]["run_paused_on_switch"] = (pane.op or {}).get("held") == "paused"
        pane.op_end("stopped", "")
    d.shot("tabs")
    d.log("bound: " + json.dumps(results["bound"]))


def main() -> int:
    global SITE
    home, out = Path(sys.argv[1]), Path(sys.argv[sys.argv.index("--out") + 1])
    site_port = int(sys.argv[sys.argv.index("--site-port") + 1]) if "--site-port" in sys.argv else 59647
    model_port = int(sys.argv[sys.argv.index("--model-port") + 1]) if "--model-port" in sys.argv else 59649
    SITE = f"http://127.0.0.1:{site_port}"
    out.mkdir(parents=True, exist_ok=True)
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
    # The driver's stand-in model on a port of this run's own.
    window_driver.ThreadingHTTPServer = lambda address, handler: ThreadingHTTPServer((address[0], model_port), handler)

    site = ThreadingHTTPServer(("127.0.0.1", site_port), Site)
    threading.Thread(target=site.serve_forever, daemon=True).start()
    results: dict = {}
    failed = window_driver.run(home, lambda d: walk(d, results), out=out, lang="zh")
    site.shutdown()
    site.server_close()
    (out / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=1))
    return failed


SITE = ""

if __name__ == "__main__":
    raise SystemExit(main())
