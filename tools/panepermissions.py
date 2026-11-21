"""Site permissions in the app's browser: what a person sees when a page asks for the camera, the microphone,
the location, the clipboard and the rest, when a link opens a program of this computer (mailto:), and when a page
opens a popup by itself. Windows only: the real app window, off screen, with no figure on the desktop.

    python tools/panepermissions.py <scratch home> --out <folder> [--site-port 59660] [--model-port 59661]

A practice page of its own on this computer asks for each permission; nothing is ever allowed that reads the
camera, the microphone, the location or the clipboard (those are refused on the strip). MIDI and window placement
are what is allowed. The program a mailto: link would open is recorded, not started. results.json in <folder>
holds the numbers."""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PAGE = b"""<!doctype html><title>Permissions</title><body style="font:15px sans-serif;padding:20px;line-height:2.4">
<button id="cammic">Camera and microphone</button> <button id="geo">Location</button> <button id="clip">Clipboard</button>
<button id="midi">MIDI</button> <button id="screens">Window placement</button> <button id="note">Notifications</button>
<a id="mail" href="mailto:someone@example.com">Write an email</a>
<script>
window.res = {};
const put = (key) => (value) => { window.res[key] = value; };
const why = (error) => error && error.name || String(error);
cammic.onclick = () => navigator.mediaDevices.getUserMedia({video: true, audio: true})
  .then((s) => { s.getTracks().forEach((t) => t.stop()); return 'granted'; }, why).then(put('cammic'));
geo.onclick = () => navigator.geolocation.getCurrentPosition(() => put('geo')('granted'), (e) => put('geo')(e.code === 1 ? 'denied' : 'error'));
clip.onclick = () => navigator.clipboard.readText().then(() => 'granted', why).then(put('clip'));
midi.onclick = () => navigator.requestMIDIAccess({sysex: true}).then(() => 'granted', why).then(put('midi'));
screens.onclick = () => window.getScreenDetails().then(() => 'granted', why).then(put('screens'));
note.onclick = () => Notification.requestPermission().then(put('note'));
if (location.search.includes('pop')) put('pop')(window.open('popped.html') ? 'opened' : 'blocked');
if (location.search.includes('midi')) navigator.requestMIDIAccess({sysex: true}).then(() => 'granted', why).then(put('midi'));
</script>"""
PAGES = {"/p.html": PAGE, "/popped.html": b"<!doctype html><title>Popped</title><p>Popped"}
PROMPT = ".browse-prompt"
PRIVACY = ".setup-nav-item[data-part=privacy]"


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


def evaluate(d, expression: str):
    """`expression` in the page in front; its value."""
    answer = d.app._browser.cdp("Runtime.evaluate", {"expression": expression, "returnByValue": True})
    return (answer.get("result") or {}).get("value")


def click_in_page(d, selector: str) -> bool:
    """A real click (DevTools input, a user gesture) on an element of the page in front."""
    at = evaluate(d, f"(() => {{ const r = document.querySelector({json.dumps(selector)}).getBoundingClientRect();"
                     " return [r.x + r.width / 2, r.y + r.height / 2]; })()")
    if not at:
        return False
    for kind in ("mouseMoved", "mousePressed", "mouseReleased"):
        d.app._browser.cdp("Input.dispatchMouseEvent", {"type": kind, "x": at[0], "y": at[1], "button": "left",
                                                        "buttons": 1 if kind == "mousePressed" else 0, "clickCount": 1})
    return True


def result(d, key: str, seconds: float = 4.0):
    """What the practice page heard for `key`, once it heard something (None when nothing came)."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        value = evaluate(d, f"window.res && window.res[{json.dumps(key)}]")
        if value:
            return value
        time.sleep(0.25)
    return None


def prompt(d) -> str:
    """The strip's words when it is on screen, else ""."""
    return d.text(PROMPT) if d.shown(PROMPT) else ""


def press(d, act: str) -> bool:
    return d.shown(f"{PROMPT} [data-act={act}]") and d.click(f"{PROMPT} [data-act={act}]")


def load(d, url: str) -> None:
    d.app._browser.go(url)
    deadline = time.time() + 15
    while time.time() < deadline:
        time.sleep(0.4)
        try:
            if d.app._browser.address() == url and evaluate(d, "document.readyState") == "complete" \
                    and evaluate(d, "!!window.res"):
                break
        except RuntimeError:
            pass
    time.sleep(0.6)


def ask(d, key: str, answer: str = "", shot: str = "") -> dict:
    """Press the page's button for `key`, see whether the strip names it, answer it with `answer`, and what the
    page heard."""
    evaluate(d, f"delete window.res[{json.dumps(key)}]")
    click_in_page(d, f"#{key}")
    time.sleep(1.5)
    said = prompt(d)
    if shot:
        d.shot(shot)
    pressed = press(d, answer) if answer and said else False
    return {"strip": said, "pressed": answer if pressed else "", "page": result(d, key)}


def privacy_list(d) -> list[str]:
    """Settings › 隐私, the site permissions unfolded: each row's words."""
    d.click("#side-settings")
    d.until(f"!!document.querySelector('{PRIVACY}')", 20)
    d.click(PRIVACY)
    time.sleep(1.5)
    d.js("(() => { const f = document.querySelector('.setup-pane .setup-permits'); if (f && !f.open) f.open = true; })()")
    time.sleep(1.5)
    return d.js("[...document.querySelectorAll('.setup-pane .setup-permit')].map((r) => r.textContent.trim().replace(/\\s+/g, ' '))") or []


def back_to_page(d) -> None:
    d.js("document.querySelector('.browse-return-go')?.click()")
    time.sleep(1.5)


def walk(d, results: dict) -> None:
    pane = d.app._browser
    page = SITE + "/p.html"
    d.app.open_link(page)
    d.until("document.querySelector('.browse') && !document.querySelector('.browse').hidden", 20)
    load(d, page)

    # 1. Each permission, asked by the person's click. The camera, microphone, location and clipboard are refused.
    asked = {"cammic": ask(d, "cammic", "no", shot="camera-microphone")}
    asked["geo"] = ask(d, "geo", "no")
    asked["clip"] = ask(d, "clip", "no")
    asked["midi"] = ask(d, "midi", "once")
    asked["midi_again"] = ask(d, "midi")
    asked["screens"] = ask(d, "screens", "always")
    asked["note"] = ask(d, "note")
    results["asked"] = asked
    results["shown"] = sum(bool(asked[k]["strip"]) for k in ("cammic", "geo", "clip", "midi", "screens"))
    d.log("asked: " + json.dumps(asked, ensure_ascii=False))

    # 2. Kept: the page again, and each asked once more.
    load(d, page)
    again = {key: ask(d, key) for key in ("cammic", "screens", "midi")}
    # The once of MIDI is gone with the page: it asks again; refused here.
    if again["midi"]["strip"]:
        press(d, "no")
    results["kept"] = again
    d.log("kept: " + json.dumps(again, ensure_ascii=False))

    # 3. A program of this computer: a mailto: link. What would be started is recorded.
    started: list = []
    real = os.startfile
    os.startfile = lambda target, *a, **k: started.append(str(target))
    try:
        evaluate(d, "0")
        click_in_page(d, "#mail")
        time.sleep(1.5)
        said = prompt(d)
        d.shot("outside-app")
        pressed = press(d, "open")
        time.sleep(1)
    finally:
        os.startfile = real
    results["outside_app"] = {"strip": said, "opened": pressed, "started": started, "page": pane.address()}
    d.log("outside_app: " + json.dumps(results["outside_app"], ensure_ascii=False))

    # 4. A popup the page opens on its own, as it loads (no click of the person's).
    tabs = len(pane._tabs)
    load(d, SITE + "/p.html?pop")
    time.sleep(1)
    said = prompt(d)
    d.shot("popup")
    pressed = press(d, "open")
    time.sleep(2.5)
    results["popup"] = {"strip": said, "page": result(d, "pop", 1), "opened": pressed, "tabs_added": len(pane._tabs) - tabs,
                        "front": pane.address()}
    if len(pane._tabs) > tabs:
        pane.do("tab_close", pane._tab.id)
        time.sleep(1.5)
    d.log("popup: " + json.dumps(results["popup"], ensure_ascii=False))

    # 5. A tab behind asks as it loads: nothing shows until it comes to the front. Another origin of the practice
    # site (localhost), so the MIDI refused above does not answer for it.
    behind = SITE.replace("127.0.0.1", "localhost") + "/p.html?midi"
    d._ui(lambda: pane._picked("tab", behind))
    time.sleep(3)
    while_behind = prompt(d)
    back_tab = next((t.id for t in pane._tabs if t.url == behind), 0)
    if back_tab:
        pane.do("tab_select", back_tab)
        time.sleep(1.5)
    in_front = prompt(d)
    press(d, "no")
    results["background_tab"] = {"strip_while_behind": while_behind, "strip_in_front": in_front,
                                 "page": result(d, "midi", 2)}
    if back_tab:
        pane.do("tab_close", back_tab)
        time.sleep(1.5)
    d.log("background_tab: " + json.dumps(results["background_tab"], ensure_ascii=False))

    # 6. While the character operates the page: nothing is asked, everything is refused, even what was kept.
    pane.operate("practice run")
    time.sleep(0.5)
    operating = {key: ask(d, key) for key in ("geo", "screens")}
    pane.op_end("stopped", "")
    results["operating"] = operating
    d.log("operating: " + json.dumps(operating, ensure_ascii=False))

    # 7. The list in Settings, and taking an answer back there.
    rows = privacy_list(d)
    d.js("document.querySelector('.setup-pane .setup-permits')?.scrollIntoView({block: 'start'})")
    time.sleep(0.5)
    d.shot("settings-list")
    taken = bool(d.js("(() => { const r = [...document.querySelectorAll('.setup-pane .setup-permit')]"
                      ".find((n) => /\\u7a97\\u53e3|window/i.test(n.textContent)); const b = r && r.querySelector('.setup-permit-off');"
                      " if (b) b.id = 'pp-off'; return !!b; })()"))
    if taken:
        d.click("#pp-off")
        time.sleep(1.5)
    rows_after = d.js("[...document.querySelectorAll('.setup-pane .setup-permit')].map((r) => r.textContent.trim().replace(/\\s+/g, ' '))") or []
    back_to_page(d)
    load(d, page)
    asked_again = ask(d, "screens", "no")
    results["settings"] = {"rows": rows, "revoked": taken, "rows_after": rows_after, "asks_again": asked_again}
    d.log("settings: " + json.dumps(results["settings"], ensure_ascii=False))

    total = 5 + 3
    seen = results["shown"] + bool(results["outside_app"]["strip"]) + bool(results["popup"]["strip"]) \
        + bool(results["background_tab"]["strip_in_front"])
    results["told"] = f"{seen}/{total}"


def main() -> int:
    global SITE
    home, out = Path(sys.argv[1]), Path(sys.argv[sys.argv.index("--out") + 1])
    site_port = int(sys.argv[sys.argv.index("--site-port") + 1]) if "--site-port" in sys.argv else 59660
    model_port = int(sys.argv[sys.argv.index("--model-port") + 1]) if "--model-port" in sys.argv else 59661
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
