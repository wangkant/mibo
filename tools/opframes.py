"""Frames from another site in web/pageops.py and operate.py, with no model: a scripted helper (optruth's) works
pages of tools/opsite whose widgets come from a second site (a second server, under the name localhost, while the
page is at 127.0.0.1), and each check reads the page's lines, what the widget's site got and the cards.

    python tools/opframes.py [--out <folder>] [--port 59642] [--frames 59643] [--only see,chat] [--real]
    python tools/opframes.py --window <scratch home> [--app 59640] [--model 59644] ...   (Windows: the app's pane)

The checks:

    see       the chat widget's box and button and the comment box are on the page's lines, under the frame's
              line, with ids; the payment frame is named and nothing in it is listed
    chat      a message typed into the chat widget and sent: one card, and the widget's site got it
    comment   a comment typed into the comment frame and published: one card, and the widget's site got it
    words     "查看更多" in the comment frame clicked by its words: the comments that came up are on the line
    card      the payment frame's fields are not on the page and cannot be found by their words
    autosave  a field of a frame that saves itself on losing the focus: what was typed is held for a card, and
              on no the frame's site gets nothing
    real      (--real) a real embedded player, signed out (YouTube's no-cookie embed): its controls are listed

With --window the same checks run in the app's own pane (WebView2), its window kept off screen; the home must be a
scratch folder. The exit code is the number of checks that failed.
"""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from optruth import Play, click, done, typed  # noqa: E402

from mibo.web import gate, operate  # noqa: E402

FRAME = r"--- frame localhost[^\n]*\n"


class Framed(Play):
    """A Play over two servers: the page's (`site`) and its widgets' (`frames`); cards answered from a list."""

    def __init__(self, browser, site: str, frames: str, allow: Path, answers: list[bool] | None = None, tab=None):
        super().__init__(browser, site, allow)
        self.frames, self.answers, self.given = frames, list(answers or []), tab

    async def open(self, path: str) -> None:
        urllib.request.urlopen(urllib.request.Request(self.frames + "/__reset", data=b"{}"), timeout=10).read()
        port = self.frames.rsplit(":", 1)[1]
        address = f"{self.site}{path}{'&' if '?' in path else '?'}frames={port}"
        if self.given is not None:
            self.tab = self.given
            await self.tab.goto(address)
        else:
            await super().open(f"{path}{'&' if '?' in path else '?'}frames={port}")
        # The widgets load after the page.
        await asyncio.sleep(2.5)

    def hands(self) -> operate.Hands:
        async def ask(card: dict) -> dict:
            self.cards.append({k: card.get(k, "") for k in ("kind", "button", "to", "text")})
            return {"yes": self.answers.pop(0) if self.answers else True, "never": False}
        return operate.Hands(self.tab, ask=ask, allowed=gate.Allowed(self.allow), attended=lambda: False, lang="zh")

    async def look(self) -> str:
        hands = self.hands()
        try:
            return (await hands.look())["state"]
        finally:
            await hands.close()

    def got(self, path: str) -> list[dict]:
        state = json.loads(urllib.request.urlopen(self.frames + "/api/state", timeout=10).read())
        return [p["body"] for p in state["posts"] if p["path"] == path]


async def see(play: Framed) -> tuple[bool, dict]:
    await play.open("/t/t30-embed.html")
    page = await play.look()
    chat = re.search(FRAME + r"(?:.*\n)*?\*?\[\d+\] textbox \"请输入您的问题\"(?:.*\n)*?\*?\[\d+\] button \"发送\"", page)
    comment = re.search(FRAME + r"(?:.*\n)*?\*?\[\d+\] textbox \"写下你的评论…\"(?:.*\n)*?\*?\[\d+\] button \"发表\"", page)
    pay = re.search(r"--- frame pay\.localhost: [^\n]*person", page)
    return bool(chat and comment and pay and "卡号" not in page), {"status": "looked", "steps": [page]}


async def chat(play: Framed) -> tuple[bool, dict]:
    await play.open("/t/t30-embed.html")
    out = await play.run("在客服窗口里发一句：我的订单 8812 还没到", [
        lambda page, prompt: [typed(r'\[(\d+)\] textbox "请输入您的问题"', "我的订单 8812 还没到", "客服输入框")(page, prompt),
                              click(r'\[(\d+)\] button "发送"', "发送")(page, prompt)],
        done("已在客服窗口发送。")])
    sent = play.got("/api/support")
    return (len(sent) == 1 and "8812" in sent[0].get("text", "") and len(play.cards) == 1
            and play.cards[0]["kind"] == "send"), out


async def comment(play: Framed) -> tuple[bool, dict]:
    await play.open("/t/t30-embed.html")
    out = await play.run("评论：写得很清楚，谢谢", [
        lambda page, prompt: [typed(r'\[(\d+)\] textbox "写下你的评论…"', "写得很清楚，谢谢", "评论框")(page, prompt),
                              click(r'\[(\d+)\] button "发表"', "发表")(page, prompt)],
        done("评论已发表。")])
    sent = play.got("/api/comment")
    return len(sent) == 1 and sent[0].get("text") == "写得很清楚，谢谢" and len(play.cards) == 1, out


async def words(play: Framed) -> tuple[bool, dict]:
    await play.open("/t/t30-embed.html")
    hands = play.hands()
    try:
        await hands.look()
        result = await hands.act({"do": "click", "text": "查看更多", "element": "查看更多"})
    finally:
        await hands.close()
    line = str(result.get("line", ""))
    return line.startswith("[ok]") and "猫砂盆" in line and not play.cards, {"status": result.get("status"),
                                                                          "steps": [line]}


async def card(play: Framed) -> tuple[bool, dict]:
    await play.open("/t/t30-embed.html")
    hands = play.hands()
    try:
        page = (await hands.look())["state"]
        result = await hands.act({"do": "click", "text": "卡号", "element": "卡号"})
    finally:
        await hands.close()
    return (result.get("status") == "missing" and "卡号" not in page and not play.got("/api/pay"),
            {"status": result.get("status"), "steps": [str(result.get("line", ""))]})


async def autosave(play: Framed) -> tuple[bool, dict]:
    play.answers = [False]
    await play.open("/t/t31-embed.html")
    out = await play.run("把昵称改成 Mibo", [
        typed(r'\[(\d+)\] textbox "昵称"', "Mibo", "昵称"),
        lambda page, prompt: {"do": "press", "key": "Tab"},
        done("昵称已改为 Mibo。")])
    saved = [b for b in play.got("/api/autosave") if "Mibo" in json.dumps(b, ensure_ascii=False)]
    return not saved and len(play.cards) >= 1 and out["status"] == "declined", out


async def real(play: Framed) -> tuple[bool, dict]:
    await play.open("/t/t32-video.html")
    await asyncio.sleep(3)
    page = await play.look()
    shown = re.search(r"--- frame www\.youtube-nocookie\.com[^\n]*\n(?:.*\n)*?\*?\[\d+\] (button|link)", page)
    return bool(shown), {"status": "looked", "steps": [page]}


CHECKS = {"see": see, "chat": chat, "comment": comment, "words": words, "card": card, "autosave": autosave}


def report(rows: list, label: str, ok: bool, seen: dict, play: Framed) -> None:
    rows.append({"check": label, "ok": bool(ok), "status": seen.get("status"), "cards": play.cards,
                 "steps": seen.get("steps", [])})
    print(f"{'PASS' if ok else 'FAIL'}  {label}: ended {seen.get('status')}, {len(play.cards)} cards")
    for step in seen.get("steps", []):
        print("      " + step.replace("\n", "\n      ")[:3000])


def serve(port: int, log: Path) -> subprocess.Popen:
    server = subprocess.Popen([sys.executable, "-B", str(HERE / "opsite" / "serve.py"), str(port), str(log)])
    for _ in range(40):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=2).read()
            break
        except OSError:
            time.sleep(0.25)
    return server


async def headless(args, checks: dict, out: Path, site: str, frames: str) -> list:
    from playwright.async_api import async_playwright
    rows: list = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(channel="msedge", headless=True)
        for label, check in checks.items():
            play = Framed(browser, site, frames, out / "allow")
            try:
                ok, seen = await check(play)
            except Exception as error:
                ok, seen = False, {"status": "error", "steps": [f"{type(error).__name__}: {error}"[:300]]}
            report(rows, label, ok, seen, play)
            if play.page is not None:
                await play.page.context.close()
        await browser.close()
    return rows


def window(args, checks: dict, out: Path, site: str, frames: str) -> list:
    """The checks in the app's pane: the app opened on the scratch home, its window far off every screen."""
    from http.server import ThreadingHTTPServer

    import webview
    import window_driver

    from mibo import window as appwindow
    from mibo.web.tabs import PaneTab
    from mibo.welcome import save_app_settings
    home = Path(args.window).resolve()
    desktop = home / "runtime" / "desktop"
    desktop.mkdir(parents=True, exist_ok=True)
    save_app_settings(desktop, toured=True, pet_shown=False)
    made = appwindow.AppWindow.__init__

    def no_figure(self, *a, **k):
        made(self, *a, **k)
        self.pet = False
    appwindow.AppWindow.__init__ = no_figure
    create = webview.create_window
    webview.create_window = lambda *a, **k: create(*a, **{**k, "x": -9000, "y": 60})
    window_driver.ThreadingHTTPServer = lambda address, handler: ThreadingHTTPServer((address[0], args.model), handler)
    rows: list = []

    def walk(d) -> None:
        d.app.open_link(site + "/t/t30-embed.html")
        d.until("document.querySelector('.browse') && !document.querySelector('.browse').hidden", 20)
        time.sleep(3)
        for label, check in checks.items():
            play = Framed(None, site, frames, out / "allow", tab=PaneTab(d.app._browser))
            try:
                ok, seen = asyncio.run(check(play))
            except Exception as error:
                ok, seen = False, {"status": "error", "steps": [f"{type(error).__name__}: {error}"[:300]]}
            report(rows, label, ok, seen, play)
            d.check(label, ok)
            if label == "see":
                d.shot("see")
        d.click(".browse-close")
        time.sleep(1)
    window_driver.run(home, walk, out=out, offscreen=False, lang="zh")
    return rows


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="")
    parser.add_argument("--port", type=int, default=59642)
    parser.add_argument("--frames", type=int, default=59643)
    parser.add_argument("--only", default="")
    parser.add_argument("--real", action="store_true")
    parser.add_argument("--window", default="")
    parser.add_argument("--model", type=int, default=59644)
    args = parser.parse_args(argv)
    out = Path(args.out or tempfile.mkdtemp(prefix="opframes-")).resolve()
    out.mkdir(parents=True, exist_ok=True)
    checks = {**CHECKS, **({"real": real} if args.real else {})}
    checks = {k: v for k, v in checks.items() if not args.only or k in args.only.split(",")}
    servers = [serve(args.port, out / "site.log"), serve(args.frames, out / "frames.log")]
    try:
        site, frames = f"http://127.0.0.1:{args.port}", f"http://127.0.0.1:{args.frames}"
        rows = (window(args, checks, out, site, frames) if args.window
                else asyncio.run(headless(args, checks, out, site, frames)))
    finally:
        for server in servers:
            server.terminate()
    (out / "frames.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    failed = sum(not row["ok"] for row in rows) + len(checks) - len(rows)
    print(f"\n{len(checks) - failed}/{len(checks)} checks passed; kept in {out / 'frames.json'}")
    return failed


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    raise SystemExit(main(sys.argv[1:]))
