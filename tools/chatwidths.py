"""How the chat lays out at every width its windows can take: the main window from its smallest to a full
screen, the pet's compact window, and the chat beside a page open in the app's browser.

    python tools/chatwidths.py <scratch home with the app running> --out <folder>

The page is the running app's own, in headless Edge; the conversation is a fixed one put in its place (long
words, an address with no break, a table, code, pictures, steps, sources, a failed message, a card waiting for a
yes), so two runs can be compared. For each width: a picture, and what does not fit, counted. results.json in
<folder> holds the numbers."""
from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path

MAIN_WIDTHS = (400, 480, 560, 640, 760, 900, 1000, 1200, 1440, 1920, 2560)
# The main window with a page open in its browser.
PAGE_WIDTHS = (400, 560, 760, 1000, 1200, 1440, 1700, 1920, 2560)
COMPACT = (380, 520)
LONG = "https://example.com/a-very-long-address/" + "segment_without_any_break_" * 6 + "end.html?utm_source=" + "x" * 60
WORD = "Pneumonoultramicroscopicsilicovolcanoconiosis" * 3
CJK = "这是一段没有任何标点也没有空格的很长的中文文字用来确认换行是否正常" * 3
TABLE = "| 订单 | 金额 | 状态 | 备注 |\n| --- | --- | --- | --- |\n" + "\n".join(
    f"| A-11{n} | ¥{n * 137}.00 | 已发货 | 一段较长的备注文字，说明这个订单的情况 |" for n in range(40, 46))
CODE = "```python\ndef a_function_with_a_long_name(first_argument, second_argument, third_argument, fourth_argument):\n    return first_argument\n```"


def history() -> dict:
    at = "2026-11-20T10:%02d:00-08:00"
    rows = [
        {"role": "user", "text": f"帮我看看这个链接 {LONG}"},
        {"role": "assistant", "text": f"已查看。{CJK}\n\n{WORD}",
         "trace": [{"tool": "search", "what": "一个很长的搜索词 " + "关键词 " * 12},
                   {"tool": "read", "what": "example.com"}, {"tool": "read", "what": "zh.wikipedia.org"},
                   {"tool": "operate", "what": "example.com", "status": "done",
                    "out": "打开 example.com\n点击「登录」\n在「搜索」中输入“猫”\n" + "滚动页面 " * 20},
                   {"tool": "shell", "what": "运行了 dir", "status": "done",
                    "cmd": "Get-ChildItem -Recurse -Force C:\\Users\\someone\\Documents\\a_long_folder_name\\another_long_folder_name",
                    "out": "\n".join(f"file_number_{n}_with_a_long_name_that_goes_on_and_on.txt" for n in range(8))}],
         "took": 42,
         "sources": [{"url": f"https://{host}/a/long/path/of/a/page", "title": f"{host} 上的一篇标题较长的文章，用来确认省略是否正常", "site": host}
                     for host in ("example.com", "zh.wikipedia.org", "www.bilibili.com", "news.ycombinator.com",
                                  "github.com", "www.zhihu.com")]},
        {"role": "user", "text": "这张图里是什么？", "attachments": [{"kind": "picture", "name": "wide.png"},
                                                              {"kind": "picture", "name": "tall.png"},
                                                              {"kind": "file", "name": "a_document_with_a_very_long_file_name_that_does_not_end.md"}]},
        {"role": "assistant", "text": f"图中是一张表格。\n\n{TABLE}\n\n{CODE}"},
        {"role": "user", "text": "在这个网页里搜索 猫", "choices": ["browser"]},
        {"role": "assistant", "text": "已在网页中搜索“猫”，共找到 12 条结果。",
         "trace": [{"tool": "operate", "what": "example.com", "status": "done", "out": "在「搜索」中输入“猫”\n按 Enter"}], "took": 9},
        {"role": "user", "text": WORD, "failed": "network"},
    ]
    for n, row in enumerate(rows):
        row.update(seq=n + 1, at=at % n)
    return {"messages": rows, "chat": "fixture", "last": len(rows), "kept": 50, "trimmed": False}


def picture(wide: int, high: int) -> bytes:
    from PIL import Image, ImageDraw
    image = Image.new("RGB", (wide, high), "#dfe3ea")
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, wide - 8, high - 8), outline="#5b6472", width=6)
    draw.line((8, 8, wide - 8, high - 8), fill="#5b6472", width=4)
    kept = io.BytesIO()
    image.save(kept, "PNG")
    return kept.getvalue()


# What does not fit in the chat on screen: elements reaching past its sides (not those inside a box that scrolls
# sideways by design), text cut with no ellipsis, the page itself scrolling sideways; and where the composer is.
MEASURE = """(() => {
  const view = document.getElementById('chat-view');
  const chat = [...view.querySelectorAll('.chat')].find((n) => !n.hidden);
  const box = view.getBoundingClientRect();
  const scrolls = (n) => { for (let p = n.parentElement; p && p !== view; p = p.parentElement) {
    const o = getComputedStyle(p).overflowX; if ((o === 'auto' || o === 'scroll') && p.scrollWidth > p.clientWidth) return true; } return false; };
  const over = [], cut = [];
  for (const n of chat.querySelectorAll('*')) {
    if (!n.getClientRects().length || n.closest('[hidden]')) continue;
    const r = n.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    if ((r.right > box.right + 1 || r.left < box.left - 1) && !scrolls(n)) over.push(n);
    const s = getComputedStyle(n);
    if (n.children.length === 0 && n.scrollWidth > n.clientWidth + 1 && s.overflowX !== 'visible' && s.textOverflow !== 'ellipsis'
        && !['auto', 'scroll'].includes(s.overflowX) && n.tagName !== 'TEXTAREA' && n.tagName !== 'INPUT') cut.push(n);
  }
  const name = (n) => n.tagName.toLowerCase() + (n.className && n.className.baseVal === undefined ? '.' + String(n.className).trim().split(/\\s+/).join('.') : '');
  const outer = over.filter((n) => !over.includes(n.parentElement));
  const rect = (sel) => { const n = chat.querySelector(sel); if (!n || !n.getClientRects().length) return null;
    const r = n.getBoundingClientRect(); return [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)]; };
  const inView = (sel) => { const n = chat.querySelector(sel); if (!n || !n.getClientRects().length) return false;
    const r = n.getBoundingClientRect(); return r.left >= box.left - 1 && r.right <= Math.min(box.right, innerWidth) + 1 && r.bottom <= innerHeight + 1 && r.top >= 0; };
  const pane = document.querySelector('.browse');
  const area = document.querySelector('.browse-area');
  const a = area && area.getClientRects().length ? area.getBoundingClientRect() : null;
  return { chat: [Math.round(box.left), Math.round(box.width)], shown: view.getClientRects().length > 0 && !view.hidden,
    over: outer.length, overNames: [...new Set(outer.map(name))].slice(0, 8), cut: cut.length, cutNames: [...new Set(cut.map(name))].slice(0, 8),
    sideways: document.documentElement.scrollWidth > innerWidth, composer: rect('.chat-composer'), input: rect('.chat-input'),
    sendInView: inView('.chat-send'), inputInView: inView('.chat-input'), plusInView: inView('.chat-attach'),
    squeezed: [...chat.querySelectorAll('.say-table td, .say-table th')].filter((c) => { const lh = parseFloat(getComputedStyle(c).lineHeight) || 20;
      return c.textContent.trim().length <= 8 && c.clientHeight - 12 > lh * 1.6; }).length,
    pane: pane && !pane.hidden ? pane.className : '', page: a ? [Math.round(a.left), Math.round(a.width)] : null,
    covered: (() => { const i = chat.querySelector('.chat-input'); if (!i || !i.getClientRects().length) return true; const r = i.getBoundingClientRect();
      const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); return !(top && (top === i || i.contains(top) || top.contains(i))); })() };
})()"""
# The chat on screen; and whether a menu of its box, once open, lies within the chat and the window.
NOW = "[...document.querySelectorAll('#chat-view .chat')].find((n) => !n.hidden)"
MENU = """(() => { const view = document.getElementById('chat-view').getBoundingClientRect();
  const menu = [...document.querySelectorAll('%s')].find((n) => !n.hidden && n.getClientRects().length);
  if (!menu) return 'not open';
  const r = menu.getBoundingClientRect();
  return r.left >= view.left - 1 && r.right <= view.right + 1 && r.top >= 0 && r.bottom <= innerHeight + 1 ? 'fits' : 'cut off'; })()"""
# A run of the character's in the page, waiting on a yes: what browser.py tells the page (browse.js).
OPERATING = {"task": "给 Alice 发消息：明天见", "step": 3, "note": "", "held": "", "end": "", "why": "", "wait": None,
             "steps": [{"text": "打开 example.com", "state": "done"}, {"text": "点击「Alice」", "state": "done"},
                       {"text": "在输入框中输入“明天见”", "state": "done"},
                       {"text": "等待确认：发送给 Alice", "state": "waiting", "card": True}],
             "card": {"id": "c1", "kind": "send", "site": "example.com", "to": "Alice", "text": "明天见 " + CJK,
                      "button": "发送", "skippable": True, "ringed": True}}


def main() -> int:
    from playwright.sync_api import sync_playwright
    home, out = Path(sys.argv[1]), Path(sys.argv[sys.argv.index("--out") + 1])
    out.mkdir(parents=True, exist_ok=True)
    url = json.loads((home / "runtime" / "desktop" / "welcome.json").read_text(encoding="utf-8"))["url"]
    base, _, fragment = url.partition("#")
    base = base.rstrip("/")
    fixture, pictures = json.dumps(history(), ensure_ascii=False), {"wide.png": picture(2400, 600), "tall.png": picture(500, 1800)}
    results: dict = {}

    def routes(page) -> None:
        def chat_history(route) -> None:
            after = "after=" in route.request.url
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"messages": [], "chat": "fixture", "last": 7, "kept": 50, "trimmed": False}) if after else fixture)
        page.route("**/api/chat/history*", chat_history)
        page.route("**/api/chat/picture/*", lambda route: route.fulfill(
            status=200, content_type="image/png", body=pictures[route.request.url.rsplit("/", 1)[-1]]))

    def look(page, key: str, name: str, more: bool = True) -> None:
        time.sleep(0.8)
        row = page.evaluate(MEASURE)
        page.screenshot(path=str(out / f"{name}.png"))
        if more and not row["covered"]:
            # The table in view, the top of the thread, then the two menus of the box, each opened and measured.
            page.evaluate(NOW + ".querySelector('.say-table').scrollIntoView({ block: 'center' })")
            time.sleep(0.3)
            page.screenshot(path=str(out / f"{name}-table.png"))
            page.evaluate(NOW + ".querySelector('.chat-scroll').scrollTop = 0")
            time.sleep(0.3)
            page.screenshot(path=str(out / f"{name}-top.png"))
            for menu, opener, shown in (("plus", ".chat-attach", ".plus-menu"), ("model", ".mb-pill", ".mb-menu")):
                page.evaluate(f"{NOW}.querySelector('{opener}').click()")
                time.sleep(0.5)
                row[f"{menu}Menu"] = page.evaluate(MENU % shown)
                page.screenshot(path=str(out / f"{name}-{menu}.png"))
                page.keyboard.press("Escape")
                time.sleep(0.2)
        results[key] = row
        print(key, json.dumps({k: row.get(k) for k in ("chat", "over", "cut", "squeezed", "sideways", "sendInView", "covered",
                                                       "plusMenu", "modelMenu", "pane", "page")}, ensure_ascii=False))

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        for wide in MAIN_WIDTHS:
            page = browser.new_page(viewport={"width": wide, "height": 820 if wide < 1900 else 1040})
            routes(page)
            page.goto(f"{base}/#{fragment}")
            page.wait_for_selector(".chat-main .chat-input", timeout=60000)
            page.wait_for_selector(".chat-main .me", timeout=20000)
            look(page, f"main-{wide}", f"main-{wide:04d}")
            page.close()
        page = browser.new_page(viewport={"width": COMPACT[0], "height": COMPACT[1]})
        routes(page)
        page.goto(f"{base}/compact#{fragment}")
        page.wait_for_selector(".chat-main .me", timeout=60000)
        look(page, "compact", "compact-0380")
        page.close()
        # A page open in the app's browser: the page is told as window.py tells it (the frame key makes it the
        # app window's own page; there is no WebView here, only the place kept for it).
        for wide in PAGE_WIDTHS:
            page = browser.new_page(viewport={"width": wide, "height": 820 if wide < 1900 else 1040})
            routes(page)
            page.goto(f"{base}/#{fragment}&frame=measure")
            page.wait_for_selector(".chat-main .me", timeout=60000)
            page.evaluate("paBrowse(%s)" % json.dumps({"open": True, "url": "https://example.com/shop/list", "host": "example.com",
                                                      "title": "示例商店 - 商品列表", "back": False, "forward": False,
                                                      "loading": False, "private": False}))
            look(page, f"page-{wide}", f"page-{wide:04d}")
            # The chat asked for from the bar while the page is open: the button that brings it, pressed where the
            # chat is not in sight already.
            if results[f"page-{wide}"]["covered"]:
                page.evaluate("(document.querySelector('.browse-beside') || document.querySelector('.browse-ask')).click()")
            look(page, f"chat-{wide}", f"chat-{wide:04d}")
            page.evaluate("paBrowse(%s)" % json.dumps({"operating": OPERATING}))
            look(page, f"run-{wide}", f"run-{wide:04d}", more=False)
            page.close()
        browser.close()
    (out / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    worst = [key for key, row in results.items() if row["over"] or row["cut"] or row["sideways"] or row["squeezed"]
             or any(row.get(menu, "fits") != "fits" for menu in ("plusMenu", "modelMenu"))]
    together = [key for key, row in results.items() if key.startswith("chat-") and row["pane"] and not row["covered"]]
    print(f"{len(results)} looks; with something that does not fit: {len(worst)} {worst}")
    print(f"page and chat on screen together: {len(together)} of {len(PAGE_WIDTHS)} widths")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
