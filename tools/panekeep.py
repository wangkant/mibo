"""Whether a page in the app's browser survives leaving it: a sidebar click, a reload of the app page and a
restart of the app, with its playback, its back history and its zoom. Windows only: the real app window,
off screen, with no figure on the desktop.

    python tools/panekeep.py <scratch home> --out <folder>

It opens a page of its own (a second page with a quiet tone, the pane muted first), then counts what is left
after each way of leaving and how many presses bring the page back. The app is started twice on the same home;
the second start checks the restart. results.json in <folder> holds the numbers."""
from __future__ import annotations

import json
import math
import struct
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SITE_PORT = 59402
SITE = f"http://127.0.0.1:{SITE_PORT}"
# A tone at -66 dBFS: over the browser's -72 dBFS line for "playing", too faint to hear.
TONE_RATE, TONE_S, TONE_LEVEL = 8000, 30, 0.0005
# Any control in the bar or the chip that is about sound.
SOUND = ("[...document.querySelectorAll('.browse-bar *, .browse-return, .browse-return *')]"
         ".filter((e) => /声音|静音|sound|mute/i.test((e.title || '') + ' ' + (e.getAttribute('aria-label') || ''))"
         " && e.getClientRects().length && !e.closest('[hidden]')).length")
CHIP = ("(() => { const c = document.querySelector('.browse-return'); return c && !c.hidden && c.getClientRects().length"
        " ? c.textContent.trim() : ''; })()")
CHIP_GO = ".browse-return .browse-return-go, .browse-return"


def tone() -> bytes:
    frames = b"".join(struct.pack("<h", int(32767 * TONE_LEVEL * math.sin(2 * math.pi * 440 * n / TONE_RATE)))
                      for n in range(TONE_RATE * TONE_S))
    return (b"RIFF" + struct.pack("<I", 36 + len(frames)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, TONE_RATE,
            TONE_RATE * 2, 2, 16) + b"data" + struct.pack("<I", len(frames)) + frames)


PAGES = {"/a.html": b"<!doctype html><title>Page A</title><p>A <a href='b.html'>to B</a>",
         "/b.html": b"<!doctype html><title>Page B</title><p>B<audio src='tone.wav' loop></audio>"}


class Site(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        body = Site.wav if path == "/tone.wav" else PAGES.get(path, b"")
        self.send_response(200 if body else 404)
        self.send_header("Content-Type", "audio/wav" if path.endswith(".wav") else "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass


def core_facts(d) -> dict:
    """What the pane's WebView is now, read on the window's thread."""
    pane, box = d.app._browser, {}

    def read() -> None:
        view, core = pane._view, pane._core
        box.update(alive=view is not None and core is not None)
        if box["alive"]:
            box.update(url=str(core.Source), back=bool(core.CanGoBack), shown=bool(view.Visible),
                       playing=bool(core.IsDocumentPlayingAudio), muted=bool(core.IsMuted),
                       zoom=round(float(view.ZoomFactor), 3))
    d._ui(read)
    return box


def played(d) -> float | None:
    """Seconds the tone played over two seconds, None with no page."""
    def at():
        try:
            answer = d.app._browser.cdp("Runtime.evaluate", {"expression": "document.querySelector('audio')?.currentTime ?? -1",
                                                             "returnByValue": True}, timeout=5)
            return float(answer["result"]["value"])
        except RuntimeError:
            return None
    first = at()
    time.sleep(2)
    second = at()
    return None if first is None or second is None or first < 0 else round(second - first, 2)


def back_with_chip(d, row: dict) -> None:
    """One press on the chip, if there is one, and what the pane is after it."""
    row["chip"] = d.js(CHIP) or ""
    if not row["chip"]:
        row["presses_back"] = None
        return
    d.click(CHIP_GO)
    time.sleep(3)
    after = core_facts(d)
    row["presses_back"] = 1 if after.get("alive") and after.get("shown") and after.get("url", "").endswith("/b.html") else None
    row["after_press"] = after
    row["pane_shown"] = bool(d.js("!document.querySelector('.browse').hidden"))


def open_b(d) -> None:
    """Page A, then its link to page B (so B has a page behind it), muted, its tone playing."""
    d.app.open_link(SITE + "/a.html")
    d.until("document.querySelector('.browse') && !document.querySelector('.browse').hidden", 20)
    time.sleep(3)
    pane = d.app._browser
    pane.cdp("Runtime.evaluate", {"expression": "location.href = 'b.html'"})
    time.sleep(3)
    d._ui(lambda: setattr(pane._core, "IsMuted", True))
    pane.cdp("Runtime.evaluate", {"expression": "document.querySelector('audio').play()", "userGesture": True,
                                  "awaitPromise": True}, timeout=10)
    time.sleep(2)


def first_run(d, results: dict) -> None:
    open_b(d)
    pane = d.app._browser
    # Zoom of the person's own for this site: one step in, as Ctrl + does (a zoom set from here raises no
    # ZoomFactorChanged, so the pane's handler is called as that event would call it).
    d._ui(lambda: (setattr(pane._view, "ZoomFactor", float(pane._view.ZoomFactor) * 1.1), pane._zoomed(None, None)))
    time.sleep(1.5)
    open_row = {**core_facts(d), "sound_controls": d.js(SOUND), "played_s": played(d)}
    results["open"] = open_row
    d.log("open: " + json.dumps(open_row))

    # A sidebar click: 新对话.
    d.click("#side-new")
    time.sleep(2.5)
    row = {**core_facts(d), "played_s": played(d), "sound_controls": d.js(SOUND)}
    # The chip's sound switch, where there is one: two presses, back as it was.
    switch = ".browse-return .browse-sound"
    if d.shown(switch):
        d.click(switch)
        time.sleep(0.6)
        row["muted_after_one_press"] = core_facts(d).get("muted")
        d.click(switch)
        time.sleep(0.6)
        row["muted_after_two_presses"] = core_facts(d).get("muted")
    back_with_chip(d, row)
    results["sidebar"] = row
    d.log("sidebar: " + json.dumps(row, ensure_ascii=False))

    # The app page reloaded, with the page open in front (opened again where the sidebar click closed it).
    if not core_facts(d).get("alive"):
        open_b(d)
    d.js("location.reload()")
    time.sleep(7)
    row = {**core_facts(d), "played_s": played(d)}
    back_with_chip(d, row)
    results["reload"] = row
    d.log("reload: " + json.dumps(row, ensure_ascii=False))
    d.shot("after-reload")


def second_run(d, results: dict) -> None:
    time.sleep(4)
    row = {"chip": d.js(CHIP) or ""}
    d.shot("restart")
    if row["chip"]:
        back_with_chip(d, row)
    else:
        row["presses_back"] = None
        d.app.open_link(SITE + "/b.html")
    deadline = time.time() + 15
    while time.time() < deadline and not core_facts(d).get("url", "").endswith("/b.html"):
        time.sleep(0.5)
    time.sleep(1.5)
    row.update(core_facts(d))
    results["restart"] = row
    d.log("restart: " + json.dumps(row, ensure_ascii=False))


def main() -> int:
    home, out = Path(sys.argv[1]), Path(sys.argv[sys.argv.index("--out") + 1])
    again = "--again" in sys.argv
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

    Site.wav = tone()
    site = ThreadingHTTPServer(("127.0.0.1", SITE_PORT), Site)
    threading.Thread(target=site.serve_forever, daemon=True).start()
    path = out / "results.json"
    results = json.loads(path.read_text(encoding="utf-8")) if again and path.exists() else {}
    run_out = out / ("restart" if again else "first")
    failed = window_driver.run(home, lambda d: (second_run if again else first_run)(d, results), out=run_out, lang="zh")
    path.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    site.shutdown()
    site.server_close()
    if not again:
        subprocess.run([sys.executable, __file__, str(home), "--out", str(out), "--again"], check=False, timeout=240)
        final = json.loads(path.read_text(encoding="utf-8"))
        final["zoom_kept"] = (final.get("restart", {}).get("zoom") == final.get("open", {}).get("zoom"))
        path.write_text(json.dumps(final, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps(final, ensure_ascii=False, indent=1))
    return failed


if __name__ == "__main__":
    raise SystemExit(main())
