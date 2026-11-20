"""Open the real app window on a scratch home and check that the page runs in it.

    python tools/window_smoke.py [--home DIR]

For the platforms tools/window_driver.py cannot reach (macOS, and Linux with
`mibo[app]`), and for Windows too: it runs `mibo start` in this
process against a stand-in model, walks the first run, chats and opens
Settings through the window's own JavaScript bridge, then closes the window. The exit status is the
number of failed checks. Nothing leaves this machine.

On Qt and Cocoa the bridge runs its script with eval, which the page's own
policy forbids. The page is first seen working under that policy (it loads and
calls the local API with its token); the policy is then widened for this run
only, so that the bridge can press what is on the page.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import threading
import time
import webbrowser
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from package_smoke import _SCRUBBED_PREFIXES, REPLY, FakeModel  # noqa: E402

# A window that never opens must not hold a CI job until its own timeout.
LIMIT_S = 300
VISIBLE = "(id => { const s = document.getElementById(id); return !!s && !s.hidden && s.getClientRects().length > 0; })"
SET = ("((selector, value) => { const e = document.querySelector(selector); e.value = value;"
       " e.dispatchEvent(new Event('input', {bubbles: true}));"
       " e.dispatchEvent(new Event('change', {bubbles: true})); return true; })")
# The model is connected through the page's own API: the bridge cannot wait for a promise.
CONNECT = ("(body => { window.smokeConnected = null; fetch('/api/config', {method: 'POST', headers: {"
           " 'Content-Type': 'application/json', 'X-Mibo-Setup-Token':"
           " sessionStorage.getItem('mibo-setup-token') || ''}, body: JSON.stringify(body)})"
           ".then(r => r.json()).then(v => { window.smokeConnected = v; }); return true; })")
SKIP = "(() => { const b = document.querySelector('#onboard-view .onboard-skip'); if (b && !b.disabled) b.click(); return true; })()"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--home", help="a scratch folder to use as the mibo home (default: a new temporary one)")
    parser.add_argument("--offscreen", action="store_true", help="open the window off screen, for a desk someone is using")
    args = parser.parse_args(argv)
    home = Path(args.home or tempfile.mkdtemp(prefix="mibo-window-")).resolve()
    home.mkdir(parents=True, exist_ok=True)
    for name in [k for k in os.environ if k.startswith(_SCRUBBED_PREFIXES)]:
        del os.environ[name]
    os.environ["AGENT_HOME"] = str(home)
    os.environ["AGENT_LANG"] = "en"

    model = ThreadingHTTPServer(("127.0.0.1", 0), FakeModel)
    threading.Thread(target=model.serve_forever, daemon=True).start()
    model_url = f"http://127.0.0.1:{model.server_address[1]}/v1"
    sent_to_browser: list[str] = []
    webbrowser.open = lambda url, *a, **k: sent_to_browser.append(str(url)) or True

    from mibo import welcome
    from mibo import window as appwindow

    if args.offscreen:
        import webview
        create = webview.create_window
        webview.create_window = lambda *a, **k: create(*a, **{**k, "x": -4000, "y": 60})

    seen: dict = {}

    class Watched(appwindow.AppWindow):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            seen["app"] = self

    welcome.appwindow.AppWindow = Watched
    results: list[bool] = []
    served: list[str] = []
    policy = {"widened": False}

    class Watch:
        """Notes what the page asked the local API for, and widens the policy when told."""

        def __init__(self, app) -> None:
            self.app = app

        async def __call__(self, scope, receive, send) -> None:
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return

            async def relay(message) -> None:
                if message["type"] == "http.response.start":
                    if message["status"] == 200 and scope["path"].startswith("/api/"):
                        served.append(scope["path"])
                    if policy["widened"]:
                        message = {**message, "headers": [
                            (k, v.replace(b"script-src 'self'", b"script-src 'self' 'unsafe-eval'"))
                            if k == b"content-security-policy" else (k, v)
                            for k, v in message["headers"]]}
                await send(message)

            await self.app(scope, receive, relay)

    serve_in_window = welcome._serve_in_window

    def watched_serve(app, *a, **k):
        app.add_middleware(Watch)
        return serve_in_window(app, *a, **k)

    welcome._serve_in_window = watched_serve

    def check(name: str, ok, detail="") -> bool:
        results.append(bool(ok))
        print(("ok    " if ok else "FAIL  ") + name + (f"  ({detail})" if detail and not ok else ""), flush=True)
        return bool(ok)

    def js(expression: str, timeout: float = 20):
        box: dict = {}

        def ask() -> None:
            try:
                box["value"] = seen["app"]._window.evaluate_js(expression)
            except Exception as error:
                box["value"] = f"<<error: {error!r}>>"

        worker = threading.Thread(target=ask, daemon=True)
        worker.start()
        worker.join(timeout)
        return "<<no answer>>" if worker.is_alive() else box.get("value")

    def until(expression: str, seconds: float):
        deadline, value = time.time() + seconds, None
        while time.time() < deadline:
            value = js(expression)
            if value is True:
                return True
            time.sleep(0.5)
        return value

    def give_up(why: str) -> None:
        check(why, False, getattr(seen.get("app"), "error", "") or f"sent to the browser: {sent_to_browser}")
        print(f"== {results.count(True)} passed, {results.count(False)} failed", flush=True)
        os._exit(1)

    def walk() -> None:
        deadline = time.time() + 120
        while time.time() < deadline and not (seen.get("app") and seen["app"].opened):
            if sent_to_browser:
                give_up("a window opened")
            time.sleep(0.2)
        if not (seen.get("app") and seen["app"].opened):
            give_up("a window opened")
        check("a window opened", True)
        try:
            deadline = time.time() + 60
            while time.time() < deadline and not served:
                time.sleep(0.3)
            check("the page in the window called the local API under its own policy", bool(served), served)
            if "unsafe-eval" in str(js("1 + 1")):
                policy["widened"] = True
                # A new query makes this a real load; the same address would only move within the page.
                seen["app"]._window.load_url(seen["app"].page_url.replace("#", "?policy=widened#", 1))
                print("      (the bridge needs eval here: policy widened for this run)", flush=True)
                time.sleep(2)
            loaded = until("document.readyState === 'complete' && typeof window.paOnboard === 'object'"
                           " && typeof window.paSetup === 'object'", 60)
            check("the page loaded in the window and its own script ran", loaded is True, loaded)
            check("a new home opens on the first run", until(f"{VISIBLE}('onboard-view')", 30) is True)
            bar = "document.body.classList.contains('frameless') && !document.getElementById('window-controls').hidden"
            if sys.platform == "win32":
                # On Windows the window has no title bar: the page is the bar and holds its buttons.
                check("the window has no title bar and the page draws the bar",
                      seen["app"].frameless is True and until(bar, 20) is True, js(bar))
                js("document.getElementById('window-maximize').click()")
                check("Maximize in the page's bar maximizes the window",
                      until("document.body.classList.contains('maximized')", 20) is True and seen["app"].maximized)
                js("document.getElementById('window-maximize').click()")
                check("and Restore brings it back",
                      until("!document.body.classList.contains('maximized')", 20) is True and not seen["app"].maximized)
            else:
                check("elsewhere the window keeps the system's title bar",
                      seen["app"].frameless is False and js(bar) is False, js(bar))
            body = {"provider": "other", "apiKey": "fake-local-key", "baseUrl": model_url, "model": "fake-model",
                    "lang": "en"}
            js(f"{CONNECT}({json.dumps(body)})")
            connected = until("!!window.smokeConnected && window.smokeConnected.configured === true", 90)
            check("the page connects the stand-in model", connected is True, js("JSON.stringify(window.smokeConnected)"))
            deadline = time.time() + 120
            while time.time() < deadline and js(f"{VISIBLE}('onboard-view')") is True:
                js(SKIP)
                time.sleep(1)
            chat = until(f"!{VISIBLE}('onboard-view') && {VISIBLE}('chat-view')", 60)
            check("walking the first run opens the chat", chat is True, chat)
            until("!!document.querySelector('#chat-view .chat-input')", 30)
            js(f"{SET}('#chat-view .chat-input', 'hello')")
            js("document.querySelector('#chat-view .chat-composer').requestSubmit()")
            messages = "document.querySelector('#chat-view .chat-messages').innerText"
            answered = until(f"{messages}.includes({json.dumps(REPLY)})", 90)
            check("the character answers in the window", answered is True, js(f"{messages}.slice(-300)"))
            js("document.getElementById('side-settings').click()")
            check("Settings opens", until(f"{VISIBLE}('setup-view')", 20) is True)
            check("nothing was sent to the system browser", not sent_to_browser, sent_to_browser)
        except Exception as error:
            check("the walk ran to its end", False, repr(error))
        finally:
            seen["app"].close()

    def watchdog() -> None:
        time.sleep(LIMIT_S)
        give_up(f"finished within {LIMIT_S} seconds")

    threading.Thread(target=watchdog, daemon=True).start()
    threading.Thread(target=walk, daemon=True).start()
    code = welcome.main([])
    check("mibo start returned 0 once the window closed", code == 0, code)
    failed = results.count(False)
    print(f"== {len(results) - failed} passed, {failed} failed", flush=True)
    return failed


if __name__ == "__main__":
    sys.exit(main())
