"""The pet suite: the figure on the desktop with the runner's own pointer and keys. Its dial with all eight buttons
whole at rest and under the pointer, each button's effect, a click and a second click on the figure, a drag, tucked
at the screen's side, a find's card, the line over its head while it works, its menu, and 退出 from that menu.

    python tools/sandbox/pet.py --out <folder>

Windows only: the pet is built on Windows' own windows (mibo/window.py, `pet and sys.platform == "win32"`); on Linux
and macOS the suite says so and checks that the app starts as the window alone. Real input (SendInput) goes to the
runner's screen; the pages are read through the windows' own bridge. Finds, the screenshot and a busy turn are
stand-ins inside the pet's page, so nothing leaves the runner.
"""
from __future__ import annotations

import json
import sys
import time

from _suite import Suite, Window, api, scratch_home, scrub_env, stand_in_model
from package_smoke import REPLY

NAMES = ["chat", "find", "quiet", "shot", "wonder", "browser", "today", "settings"]
FIND = {"id": "sandbox-1", "url": "http://127.0.0.1:9/find", "site": "127.0.0.1", "title": "一篇用来验证卡片的文章",
        "line": "你最近在看桌面伴侣，这篇讲得很细。", "slot": "model", "liked": False,  # copy: voice
        "why": {"text": "你常看的话题：桌面伴侣", "key": "topic:desk", "lean": None}}
PIXEL = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
# The pet page's fetch, answered here for the dial's find and screenshot and a find's card.
STUB = """(() => {
  const real = (window.__real = window.__real || window.fetch);
  window.__calls = []; window.__given = 0; window.__item = null; window.__stopped = null; window.__busy = false;
  window.fetch = (url, opts) => {
    const u = String(url); window.__calls.push(u);
    const answer = (v) => Promise.resolve(new Response(JSON.stringify(v)));
    if (u.startsWith('/api/compose/capture')) return answer({ picture: '%s' });
    if (u.startsWith('/api/compose/recent')) return answer({ pages: [] });
    if (u.startsWith('/api/feed/next') && window.__item) { window.__given++; return answer({ item: window.__given === 1 ? window.__item : null }); }
    if (u.startsWith('/api/feed/react') || u.startsWith('/api/feed/end')) return answer({ ok: true });
    if (u.startsWith('/api/chat/stop')) { window.__stopped = JSON.parse(opts.body); window.__busy = false; return answer({ ok: true }); }
    if (u.startsWith('/api/chat/doing') && window.__busy) return answer({ busy: true, doing: { tool: 'search', what: '桌面宠物 设计' }, last: 0 });
    return real(url, opts);
  };
  return true;
})()""" % PIXEL


class Desk:
    """The runner's screen, pointer and keys (Windows)."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self.c, self.wt = ctypes, wintypes
        self.u = ctypes.windll.user32
        self.u.WindowFromPoint.argtypes = [wintypes.POINT]
        self.u.WindowFromPoint.restype = wintypes.HWND
        self.u.GetAncestor.argtypes = [wintypes.HWND, ctypes.c_uint]
        self.u.GetAncestor.restype = wintypes.HWND
        self.u.GetForegroundWindow.restype = wintypes.HWND
        self.vx, self.vy, self.vw, self.vh = (self.u.GetSystemMetrics(i) for i in (76, 77, 78, 79))

    def rect(self, hwnd: int) -> tuple[int, int, int, int]:
        r = self.wt.RECT()
        self.u.GetWindowRect(self.wt.HWND(hwnd), self.c.byref(r))
        return r.left, r.top, r.right, r.bottom

    def work_area(self) -> tuple[int, int, int, int]:
        r = self.wt.RECT()
        self.u.SystemParametersInfoW(0x0030, 0, self.c.byref(r), 0)
        return r.left, r.top, r.right, r.bottom

    def under(self, x: int, y: int) -> int:
        return self.u.GetAncestor(self.u.WindowFromPoint(self.wt.POINT(x, y)), 2) or 0

    def visible(self, hwnd: int) -> bool:
        return bool(hwnd and self.u.IsWindowVisible(self.wt.HWND(hwnd)))

    def front(self) -> int:
        return self.u.GetForegroundWindow() or 0

    def cursor(self) -> tuple[int, int]:
        p = self.wt.POINT()
        self.u.GetCursorPos(self.c.byref(p))
        return p.x, p.y

    def _move(self, x: int, y: int) -> None:
        self.u.mouse_event(0x0001 | 0x8000 | 0x4000, round((x - self.vx) * 65535 / (self.vw - 1)),
                           round((y - self.vy) * 65535 / (self.vh - 1)), 0, 0)

    def glide(self, to, ms: int = 200) -> None:
        x0, y0 = self.cursor()
        n = max(1, round(ms / 16))
        for i in range(1, n + 1):
            self._move(round(x0 + (to[0] - x0) * i / n), round(y0 + (to[1] - y0) * i / n))
            time.sleep(0.016)

    def click(self, at, right: bool = False, hold: float = 0.05) -> None:
        self.glide(at, 150)
        down, up = (0x0008, 0x0010) if right else (0x0002, 0x0004)
        self.u.mouse_event(down, 0, 0, 0, 0)
        time.sleep(hold)
        self.u.mouse_event(up, 0, 0, 0, 0)

    def drag(self, a, b, ms: int = 700) -> None:
        self.glide(a, 150)
        self.u.mouse_event(0x0002, 0, 0, 0, 0)
        time.sleep(0.12)
        self.glide((a[0] + 12, a[1] + 4), 80)
        self.glide(b, ms)
        time.sleep(0.3)
        self.u.mouse_event(0x0004, 0, 0, 0, 0)

    def key(self, code: int) -> None:
        self.u.keybd_event(code, 0, 0, 0)
        time.sleep(0.04)
        self.u.keybd_event(code, 0, 2, 0)


def wait_for(fn, secs: float = 3.0, step: float = 0.05):
    began = time.time()
    while time.time() - began < secs:
        value = fn()
        if value:
            return value, round(time.time() - began, 2)
        time.sleep(step)
    return fn(), None


def walk(w: Window, suite: Suite, desk: Desk, ended: dict) -> None:
    app = w.app
    pet_js = lambda code: w.js(code, window=app._pet)
    main_js = lambda code: w.js(code)
    ready = "typeof pose !== 'undefined' && pose === 'standing' && Boolean(rig) && typeof quick === 'object'"
    suite.check("figure", "the figure stands on the desktop", w.until(ready, 60, window=app._pet) is True)
    hwnd = app._pet_hwnd
    left, top, right, bottom = desk.work_area()
    spot = (right - 420, bottom - 330)

    def stand() -> None:
        def go():
            app._pet.native.Left, app._pet.native.Top = spot
            app._ground = (app._pet.native.Left, app._pet.native.Bottom)
        app._on_pet(go)
        time.sleep(0.4)

    def css_to_screen(x, y):
        l, t, r, _ = desk.rect(hwnd)
        d = (r - l) / pet_js("innerWidth")
        return round(l + x * d), round(t + y * d)

    def box(selector):
        return pet_js(f"(() => {{ const e = document.querySelector({json.dumps(selector)}); if (!e) return null;"
                      " const r = e.getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom]; })()")

    def middle(selector):
        b = box(selector)
        return css_to_screen((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)

    def body_point(dx: float = 0.0):
        x, y = pet_js("(() => { const b = figureBox.getBoundingClientRect(); const s = rig.layout ? rig.layout.shape"
                      " : {top: 20, bottom: 186, left: 30, right: 130}; return [b.left + (s.left + s.right) / 2,"
                      " b.top + s.top + (s.bottom - s.top) * 0.6]; })()")
        return css_to_screen(x + dx, y)

    def whole(selector) -> dict:
        """Inside the page, and every corner (2 px in) reaches the pet's window through its region."""
        b = box(selector)
        width, height = pet_js("[innerWidth, innerHeight]")
        inside = b[0] >= 0 and b[1] >= 0 and b[2] <= width and b[3] <= height
        corners = [css_to_screen(x, y) for x in (b[0] + 2, b[2] - 2) for y in (b[1] + 2, b[3] - 2)]
        reached = all(desk.under(*c) == hwnd for c in corners)
        return {"inside": inside, "reached": reached, "box": [round(v) for v in b]}

    def compact():
        c = app._compact
        return None if c is None or not c.hwnd else {"out": c.out, "visible": desk.visible(c.hwnd),
                                                     "front": desk.front() == c.hwnd, "hwnd": c.hwnd}

    def chat_js(code):
        return w.js(code, window=app._compact.window)

    def out_now() -> bool:
        s = compact()
        return bool(s and s["out"] and s["visible"])

    def away_now() -> bool:
        s = compact()
        return bool(s is None or (not s["out"] and not s["visible"]))

    def home_again() -> None:
        if app._attached:
            import threading
            threading.Thread(target=app._go_out, args=("hide",), daemon=True).start()
            wait_for(lambda: pet_js("pose") == "standing" and not app._attached, 6)
            time.sleep(0.6)

    def reset() -> None:
        if out_now():
            chat_js("pywebview.api.away()")
            wait_for(away_now, 2)
        pet_js("card.close('seen'); hideQuick(); true")
        home_again()
        stand()
        desk.glide((left + 80, top + 80), 120)
        time.sleep(0.5)

    stand()
    time.sleep(1.5)
    # It walks and blinks by itself: held still so a press lands where it was aimed.
    pet_js("clearTimeout(idleTimer); clearTimeout(blinkTimer); true")
    pet_js(STUB)
    suite.log("pet window", desk.rect(hwnd), "scale", app._pet_scale, "work area", (left, top, right, bottom))

    # ---- the dial
    def open_dial():
        desk.glide((left + 80, top + 80), 100)
        time.sleep(0.6)
        # A pointer that arrives while it plays a scene (a wave) gets no dial until it leaves and comes again.
        wait_for(lambda: pet_js("watching()"), 10)
        desk.glide(body_point(), 250)
        return wait_for(lambda: pet_js("quick.classList.contains('on')"), 3)

    pet_js("window.__ev = []; for (const t of ['pointerenter', 'pointerleave']) pet.addEventListener(t, () => __ev.length < 30"
           " && __ev.push([t, watching(), scene && scene.name || '', press, pose, hovering]), true); true")
    v, took = open_dial()
    suite.check("dial", "the dial comes out while the pointer stays on the figure", v,
                {"took": took, "seen": pet_js("__ev"), "now": pet_js("[watching(), scene && scene.name || '', hovering]")})
    time.sleep(0.5)
    rest = {n: whole(f".quick-{n}") for n in NAMES}
    suite.check("dial", "all 8 buttons whole at rest: inside the window and each corner takes the pointer",
                all(r["inside"] and r["reached"] for r in rest.values()), rest)
    labels = pet_js("[...quick.querySelectorAll('button')].map((b) => b.getAttribute('aria-label'))")
    suite.check("dial", "each button has a name", len(labels) == 8 and all(labels), labels)
    suite.shot("dial-rest")
    hovered, named = {}, {}
    for n in NAMES:
        desk.glide(middle(f".quick-{n}"), 120)
        time.sleep(0.3)
        hovered[n] = whole(f".quick-{n}")
        named[n] = pet_js("document.querySelector('.dial-name').textContent") == pet_js(
            f"document.querySelector('.quick-{n}').getAttribute('aria-label')")
        if n == "settings":
            suite.shot("dial-hover")
    suite.check("dial", "all 8 buttons whole under the pointer", all(r["inside"] and r["reached"] for r in hovered.values()),
                hovered)
    suite.check("dial", "the pill names the button under the pointer", all(named.values()), named)

    def press(name: str) -> None:
        for _ in range(3):
            if pet_js("quick.classList.contains('on')"):
                break
            open_dial()
        desk.glide(middle(f".quick-{name}"), 150)
        desk.click(middle(f".quick-{name}"))

    shown_main = lambda: bool(app._attached and app._shown())
    press("chat")
    suite.check("dial", "聊天 brings the compact chat", wait_for(out_now, 4)[0])
    chat_js("pywebview.api.away()")
    wait_for(away_now, 2)
    press("find")
    time.sleep(1.5)
    suite.check("dial", "推荐一条 asks for a find now",
                any("/api/feed/next" in u and "now=true" in u for u in pet_js("window.__calls")))
    pet_js("card.close('seen'); true")
    press("quiet")
    suite.check("dial", "勿扰 turns do-not-disturb on, kept by the service",
                wait_for(lambda: pet_js("petSnoozed()") and api(w.home, "feed/snooze").get("left", 0) > 0, 3)[0])
    press("quiet")
    suite.check("dial", "勿扰 again turns it off",
                wait_for(lambda: not pet_js("petSnoozed()") and not api(w.home, "feed/snooze").get("left", 0), 3)[0])
    press("shot")
    suite.check("dial", "截图提问 puts the picture in the compact chat's box",
                wait_for(lambda: out_now() and chat_js("document.querySelectorAll('.chat-main .chat-tray > *').length") >= 1, 6)[0])
    chat_js("document.querySelectorAll('.chat-main .chat-tray button[aria-label]').forEach((b) => /移除|Remove/.test("
            "b.getAttribute('aria-label')) && b.click()); pywebview.api.away(); true")
    wait_for(away_now, 2)
    press("wonder")
    suite.check("dial", "外出浏览 says it is off where walks are off",
                wait_for(lambda: pet_js("card.open && card.kind === 'panel' && cardBox.textContent.includes('外出浏览')"), 3)[0],
                pet_js("[card.kind, cardBox.textContent.slice(0, 40)]"))
    pet_js("card.close('seen'); true")
    time.sleep(0.5)
    press("browser")
    suite.check("dial", "打开浏览器 brings the app window", wait_for(shown_main, 8)[0])
    home_again()
    press("today")
    v, _ = wait_for(shown_main, 8)
    time.sleep(1.0)
    view = main_js("document.getElementById('side-finds').classList.contains('active')")
    suite.check("dial", "推荐记录 opens the app window on the find history", v and view is True, view)
    home_again()
    press("settings")
    v, _ = wait_for(shown_main, 8)
    time.sleep(1.0)
    suite.check("dial", "设置 opens the app window on Settings", v and "setup-view" in w.views(), w.views())
    home_again()

    # ---- a click, and a second click (petclick.js: the second click takes the chat as already out)
    reset()
    desk.click(body_point())
    v, took = wait_for(out_now, 4)
    suite.check("click", "one click brings the compact chat out", v, took)
    s = compact()
    suite.check("click", "the compact chat is in front", bool(s and s["front"]), s)
    focus = chat_js("[document.hasFocus(), document.activeElement && document.activeElement.className]")
    suite.check("click", "its box takes the keyboard", bool(focus and focus[0] and "chat-input" in (focus[1] or "")), focus)
    suite.shot("compact-chat")
    count = "document.querySelectorAll('.chat-main [data-seq]').length"
    before = chat_js(count)
    chat_js("(() => { const i = document.querySelector('.chat-main .chat-input'); i.value = '你好，宠物';"  # copy: voice
            " i.dispatchEvent(new Event('input')); return true; })()")
    desk.key(0x0D)
    v, took = wait_for(lambda: chat_js(count) >= before + 2 and REPLY in chat_js(
        "document.querySelector('.chat-main').innerText"), 20, 0.3)
    suite.check("click", "Enter sends and the reply shows in the compact chat", v, took)
    desk.key(0x1B)
    suite.check("click", "Esc puts it away", wait_for(away_now, 3)[0])
    desk.click(body_point())
    wait_for(out_now, 4)
    chat_js("(() => { const i = document.querySelector('.chat-main .chat-input'); i.value = '草稿一句';"  # copy: voice
            " i.dispatchEvent(new Event('input')); return true; })()")
    desk.click((left + 120, top + 120))
    suite.check("click", "a click elsewhere puts it away", wait_for(away_now, 3)[0])
    desk.click(body_point())
    wait_for(out_now, 4)
    draft = chat_js("document.querySelector('.chat-main .chat-input').value")
    suite.check("click", "the draft is kept", draft == "草稿一句", draft)
    chat_js("(() => { const i = document.querySelector('.chat-main .chat-input'); i.value = ''; i.dispatchEvent(new Event('input')); return true; })()")
    cl, ct, _, _ = desk.rect(app._compact.hwnd)
    b = chat_js("(() => { const r = document.querySelector('.compact-away').getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2, innerWidth]; })()")
    d = (desk.rect(app._compact.hwnd)[2] - cl) / b[2]
    desk.click((round(cl + b[0] * d), round(ct + b[1] * d)))
    suite.check("click", "its close button puts it away", wait_for(away_now, 3)[0])
    for gap in (350, 700):
        ok = 0
        for rep in range(3):
            reset()
            desk.click(body_point())
            time.sleep(gap / 1000)
            # A little aside of the first press, so the two are never one double-click.
            desk.click(body_point(10 if rep % 2 else -10))
            time.sleep(1.2)
            ok += away_now()
        suite.check("click", f"a second click {gap} ms after the first puts the chat away", ok == 3, f"{ok}/3")

    # ---- a drag
    reset()
    moves = []
    for rep in range(2):
        stand()
        time.sleep(1.0)
        was = desk.rect(hwnd)
        a = body_point()
        desk.drag(a, (a[0] - 300, a[1] - 120))
        time.sleep(1.0)
        now = desk.rect(hwnd)
        moves.append((now[0] - was[0], now[1] - was[1]))
    suite.check("drag", "the window follows the hand", all(abs(x + 300) < 30 and abs(y + 120) < 30 for x, y in moves), moves)
    suite.check("drag", "no compact chat and no app window after a drag", away_now() and not app._shown(), compact())
    time.sleep(1.5)
    state = pet_js("[pose, dragging, press, Boolean(carry)]")
    suite.check("drag", "standing after it is let go, nothing pressed left over",
                state[0] == "standing" and not state[1] and state[2] is None and not state[3], state)

    # ---- tucked at the side
    reset()
    a = body_point()
    desk.drag(a, (right - 6, a[1]), 900)
    v, took = wait_for(lambda: pet_js("'edge' in pet.dataset && pet.dataset.edge"), 4)
    suite.check("tuck", "let go at the screen's right side, it tucks into it", v == "right", {"edge": v, "took": took})
    suite.check("tuck", "its window is flush with the side", desk.rect(hwnd)[2] == right, {"window": desk.rect(hwnd), "right": right})
    time.sleep(0.8)
    suite.shot("tucked")
    head = pet_js("(() => { const r = figureBox.getBoundingClientRect(); return [Math.min(innerWidth - 6, r.right - 10), r.top + r.height / 2]; })()")
    desk.click(css_to_screen(*head))
    suite.check("tuck", "a press on the tucked head brings it out", wait_for(lambda: not pet_js("'edge' in pet.dataset"), 4)[0])
    if out_now():
        chat_js("pywebview.api.away()")
        wait_for(away_now, 2)

    # ---- a find's card
    reset()
    pet_js(f"window.__item = {json.dumps(FIND, ensure_ascii=False)}; window.__given = 0; true")
    desk.click(body_point())
    wait_for(out_now, 4)
    pet_js("petLook(); true")
    time.sleep(2.0)
    suite.check("card", "a find waits while the compact chat is out", not pet_js("card.open"))
    chat_js("pywebview.api.away()")
    wait_for(away_now, 2)
    pet_js("petLook(); true")
    v, took = wait_for(lambda: pet_js("card.open && card.kind !== 'said' && card.kind !== 'panel'"), 5)
    suite.check("card", "it comes once the chat is put away", v, took)
    if v:
        time.sleep(1.2)
        parts = {s: whole(s) for s in (".card-why", ".card-like", ".card-nope", ".card-next")}
        suite.check("card", "its reason, like, not interested and another are whole and take the pointer",
                    all(p["inside"] and p["reached"] for p in parts.values()), parts)
        suite.shot("card")
        desk.click(middle(".card-nope"))
        suite.check("card", "不感兴趣 asks what about it",
                    wait_for(lambda: pet_js("Boolean(cardBox.querySelector('.card-reasons, .card-ask, .card-undo'))"), 3)[0],
                    pet_js("cardBox.textContent.slice(0, 80)"))
        if not pet_js("Boolean(cardBox.querySelector('.card-undo'))"):
            reason = pet_js("Boolean(cardBox.querySelector('.card-reasons button, .card-ask button'))")
            if reason:
                desk.click(middle(".card-reasons button, .card-ask button"))
        v, _ = wait_for(lambda: pet_js("Boolean(cardBox.querySelector('.card-undo'))"), 3)
        undo = whole(".card-undo") if v else None
        suite.check("card", "the no can be taken back, and its undo takes the pointer",
                    bool(v and undo["reached"]), undo or pet_js("cardBox.textContent.slice(0, 80)"))
        pet_js("card.close('seen'); true")
    pet_js("window.__item = null; true")

    # ---- the line over its head while a turn works (petline.js: drawn again only when the step changes)
    reset()
    pet_js("""(() => { window.__busy = true; window.__asks = 0; const chat = window.pywebview.api.chat;
      window.pywebview.api.chat = (how, p) => { if (how === 'show') { __asks++; return Promise.resolve(); } return chat(how, p); };
      petActivity('searching'); return true; })()""")
    v, took = wait_for(lambda: pet_js("document.querySelector('.pet-line').classList.contains('on')"), 5)
    suite.check("line", "the live line shows while it works", v, took)
    time.sleep(1.0)
    suite.shot("line")
    presses = 20
    for i in range(presses):
        at = middle(".line-open .doing")
        desk.click(at, hold=0.12)
        desk.glide((at[0] - 260, at[1] + 120), 40)
        time.sleep(0.15 + (i % 7) * 0.05)
    asks = pet_js("__asks")
    suite.check("line", f"each of {presses} presses on the line's words opens the chat", asks == presses, f"{asks}/{presses}")
    stops = 0
    for _ in range(3):
        pet_js("window.__busy = true; window.__stopped = null; petActivity('searching'); true")
        wait_for(lambda: pet_js("document.querySelector('.pet-line').classList.contains('on')"), 4)
        time.sleep(1.0)
        at = middle(".line-stop")
        desk.glide(at, 250)
        time.sleep(0.8)
        desk.click(at, hold=0.1)
        time.sleep(0.6)
        stopped = pet_js("window.__stopped") is not None
        stops += stopped
        if not stopped:
            suite.log("  停止 not taken:", pet_js("[document.querySelector('.pet-line').className, quick.className,"
                                                 " document.elementFromPoint(...(() => { const r = document.querySelector('.line-stop')"
                                                 ".getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; })())?.className]"),
                      desk.under(*at) == hwnd)
    suite.check("line", "停止, pointed at and pressed, stops the turn", stops == 3, f"{stops}/3")
    pet_js("window.__busy = false; petActivity(''); true")

    # ---- its menu, and 退出 from it
    reset()
    desk.click(body_point(), right=True)
    v, _ = wait_for(lambda: bool(app._pet_strip is not None and app._pet_strip.Visible), 3)
    items = [str(i.Text) for i in app._pet_strip.Items] if app._pet_strip is not None else []
    suite.check("menu", "a right click opens its menu with 退出 last", v and items and items[-1] == "退出", items)
    suite.shot("menu")
    strip = app._pet_strip
    last = [i for i in strip.Items if i.GetType().Name == "ToolStripMenuItem"][-1]
    desk.click((strip.Left + last.Bounds.X + last.Bounds.Width // 2, strip.Top + last.Bounds.Y + last.Bounds.Height // 2))
    ended["at"] = time.time()


def main() -> int:
    suite = Suite("pet", __doc__.split("\n\n")[0])
    scrub_env()
    home = scratch_home(stand_in_model(), lang="zh")
    if sys.platform != "win32":
        suite.not_built("figure", "the pet is built on Windows' own windows (mibo/window.py)")
        for feature in ("dial", "click", "drag", "tuck", "card", "line", "menu", "quit"):
            suite.not_built(feature, "no pet on this system")

        def alone(w: Window) -> None:
            suite.check("window", "the app starts as its window alone, with no figure", w.app.pet is False and not w.app._pet)

        Window(suite, home).run(alone)
        return suite.finish()
    from mibo.welcome import save_app_settings

    # The first run walked already: the app window the dial opens shows the app, not the first run.
    desktop = home / "runtime" / "desktop"
    desktop.mkdir(parents=True)
    save_app_settings(desktop, toured=True)
    ended: dict = {}
    code = Window(suite, home).run(lambda w: walk(w, suite, Desk(), ended))
    took = round(time.time() - ended["at"], 1) if "at" in ended else None
    suite.check("quit", "退出 from the menu ends the app, every window with it", code == 0 and took is not None and took < 25,
                {"code": code, "seconds": took})
    return suite.finish()


if __name__ == "__main__":
    sys.exit(main())
