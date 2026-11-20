"""What web/operate.py says of a run against what happened, with no model and no window: a scripted helper works
pages of tools/opsite in headless Edge the way a model errs (it names one control and gives another's id, presses
a button already pressed, sends the same words again, says done with nothing sent), and each check reads what the
loop wrote, what the site got and how the run ended.

    python tools/optruth.py [--out <folder>] [--port 59630] [--only name,repeat]

One line a check, then the loop's own lines; <out>/truth.json keeps them. The exit code is the number of checks
that failed. The checks:

    plain    an ordinary send goes through: one card, one message, no step refused, no judge call
    name     an id whose control is not the one named is refused, nothing clicked
    line     a click's line names an icon with no words and says what changed on it
    hover    a hover's line lists what came up under the pointer
    repeat   pressing again what was confirmed and pressed ends the run as done
    resend   the same words to the same person are not sent twice
    unsent   done with what was typed never sent is not taken as done
    expect   done with words the page does not show is not taken; with words it shows, taken with no judge call
    go_on    after a handover, done with nothing saved is not taken, and the save still gets its card
    why      a press that cannot land is not put on a card, and fails with the reason in the person's words
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
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE / "opsite"))

from persona_agent.web import gate, operate  # noqa: E402
from persona_agent.web.tabs import PlaywrightTab  # noqa: E402

STOP = {"do": "done", "success": False, "result": "(the script ended)"}


def ident(page: str, pattern: str) -> int:
    """The id the pattern's first group finds in the page's lines."""
    return int(re.search(pattern, page).group(1))


class Play:
    """One page of the site and a script for it: `run` is operate.run with the script's replies as the model's."""

    def __init__(self, browser, site: str, allow: Path):
        self.browser, self.site, self.allow = browser, site, allow
        self.cards: list[dict] = []
        self.judged = 0
        self.page = None

    async def open(self, path: str) -> None:
        urllib.request.urlopen(urllib.request.Request(self.site + "/__reset", data=b"{}"), timeout=10).read()
        context = await self.browser.new_context(viewport={"width": 1100, "height": 760}, locale="zh-CN")
        self.page = await context.new_page()
        self.tab = PlaywrightTab(self.page)
        await self.tab.goto(self.site + path)

    def hands(self) -> operate.Hands:
        async def ask(card: dict) -> dict:
            self.cards.append({k: card.get(k, "") for k in ("kind", "button", "to", "text")})
            return {"yes": True, "never": False}
        return operate.Hands(self.tab, ask=ask, allowed=gate.Allowed(self.allow), attended=lambda: False, lang="zh")

    async def run(self, task: str, plan: list, *, judge: dict | None = None, before: list[str] | None = None) -> dict:
        """`plan`: one entry a model call, each a function of the page's lines and the whole prompt that gives
        the reply's actions. `judge`: what the judge of a done with no proof answers."""
        plan = list(plan)

        async def model(system: str, messages: list[dict]) -> str:
            prompt = messages[-1]["content"]
            if not system.startswith("You operate a web page"):
                self.judged += 1
                return json.dumps(judge or {"done": True}, ensure_ascii=False)
            page = prompt.split("The page now:", 1)[-1]
            try:
                actions = plan.pop(0)(page, prompt) if plan else STOP
            except AttributeError:
                # What the script looks for is not on the page.
                actions = STOP
            return json.dumps({"note": "按脚本操作", "keep": "",
                               "actions": actions if isinstance(actions, list) else [actions]}, ensure_ascii=False)

        hands = self.hands()
        try:
            return await asyncio.wait_for(operate.run(model, hands, task, before=before, said=task), 120)
        finally:
            await hands.close()

    def got(self, path: str) -> list[dict]:
        state = json.loads(urllib.request.urlopen(self.site + "/api/state", timeout=10).read())
        return [p["body"] for p in state["posts"] if p["path"] == path]


def click(pattern: str, element: str):
    return lambda page, prompt: {"do": "click", "id": ident(page, pattern), "element": element}


def typed(pattern: str, text: str, element: str):
    return lambda page, prompt: {"do": "type", "id": ident(page, pattern), "text": text, "element": element}


def done(result: str, expect: str = ""):
    return lambda page, prompt: {"do": "done", "success": True, "result": result, **({"expect": expect} if expect else {})}


STAR = r'购物清单[^\n]*\n\*?\[(\d+)\] button'
ALICE = [click(r'\[(\d+)\] link "Alice"', "Alice"),
         lambda page, prompt: [typed(r'\[(\d+)\] textbox', "明天见", "输入框")(page, prompt),
                               click(r'\[(\d+)\] button "发送"', "发送按钮")(page, prompt)]]


async def plain(play: Play) -> tuple[bool, dict]:
    await play.open("/messages.html")
    out = await play.run("给 Alice 发消息：明天见", [*ALICE, done("已向 Alice 发送“明天见”。")])
    sent = play.got("/api/send")
    return (out["status"] == "done" and len(sent) == 1 and len(play.cards) == 1 and play.judged == 0
            and not any(line.startswith("[failed]") for line in out["steps"])), out


async def name(play: Play) -> tuple[bool, dict]:
    await play.open("/t/t23-shop.html")
    out = await play.run("在这个商城找到帮助中心", [click(r'\[(\d+)\] link "优惠券"', "更多 ▾ 菜单")])
    lines = "\n".join(out["steps"])
    return "[ok] click" not in lines and 'not "更多 ▾ 菜单"' in lines, out


async def line(play: Play) -> tuple[bool, dict]:
    await play.open("/t/t10-notes.html")
    out = await play.run("把“购物清单”这条笔记收藏一下", [click(STAR, "收藏")])
    pressed = next((x for x in out["steps"] if x.startswith("[ok] click")), "")
    return "收藏" in pressed and bool(re.search(r"now (on|pressed)", pressed)), out


async def hover(play: Play) -> tuple[bool, dict]:
    await play.open("/t/t23-shop.html")
    out = await play.run("在这个商城找到帮助中心", [lambda page, prompt: {"do": "hover", "text": "更多 ▾"}])
    over = next((x for x in out["steps"] if x.startswith("[ok] hover")), "")
    return "帮助中心" in over, out


async def repeat(play: Play) -> tuple[bool, dict]:
    await play.open("/t/t10-notes.html")
    out = await play.run("把“购物清单”这条笔记收藏一下", [click(STAR, "收藏")] * 7)
    stars = play.got("/api/star")
    return out["status"] == "done" and len(stars) == 1 and stars[0].get("on") is True, out


async def resend(play: Play) -> tuple[bool, dict]:
    await play.open("/messages.html")
    out = await play.run("给 Alice 发消息：明天见", [*ALICE, ALICE[1], done("已向 Alice 发送“明天见”。")])
    return out["status"] == "done" and len(play.got("/api/send")) == 1, out


async def unsent(play: Play) -> tuple[bool, dict]:
    await play.open("/messages.html")
    out = await play.run("给 Alice 发消息：明天见",
                         [ALICE[0], typed(r'\[(\d+)\] textbox', "明天见", "输入框"), *[done("已向 Alice 发送“明天见”。")] * 4],
                         judge={"done": False, "missing": "消息还没有发送给 Alice。"})
    return out["status"] != "done" and not play.got("/api/send") and play.judged == 1, out


async def expect(play: Play) -> tuple[bool, dict]:
    await play.open("/t/t14-orders.html")

    def read(page: str, prompt: str) -> dict:
        row = re.search(r"A-1143 [^\n]*?([\d.]+)\n", prompt.split("Found on the page:", 1)[-1]).group(0).strip()
        return done(f"订单 A-1143：{row}", row.split()[-1])(page, prompt)

    find = lambda page, prompt: {"do": "find", "text": "A-1143"}  # noqa: E731
    out = await play.run("查一下订单 A-1143 的金额是多少", [find, done("订单 A-1143 的金额是 0.01 元。", "A-1143 的金额 0.01"),
                                                 find, read])
    amount = 268.5 + 7 * (json.loads(urllib.request.urlopen(play.site + "/api/state", timeout=10).read()).get("round", 0) % 9)
    return out["status"] == "done" and f"{amount:.2f}" in out["result"] and play.judged == 0, out


async def go_on(play: Play) -> tuple[bool, dict]:
    await play.open("/profile.html")
    task = "把我的昵称改成 Mibo"
    save = click(r'\[(\d+)\] button "保存"', "保存")
    first = await play.run(task, [lambda page, prompt: [typed(r'\[(\d+)\] textbox "昵称"', "Mibo", "昵称")(page, prompt),
                                                         save(page, prompt)]])
    # The person types their own password where the focus was left (a test value), and says go on.
    await play.page.fill("#current", "bench-Pw-4471")
    said = done("昵称已改为 Mibo。", "Mibo")
    out = await play.run(task, [said, said, save, done("昵称已改为 Mibo，页面显示“已保存。”", "已保存")],
                         judge={"done": False, "missing": "还没有点击保存。"}, before=first["steps"])
    saved = play.got("/api/profile")
    return (first["status"] == "handover" and out["status"] == "done" and len(saved) == 1
            and saved[0].get("nickname") == "Mibo" and len(play.cards) == 1), {**out, "steps": first["steps"] + out["steps"]}


async def why(play: Play) -> tuple[bool, dict]:
    await play.open("/t/t09-article.html")
    hands = play.hands()
    try:
        look = await hands.look()
        result = await hands.act({"do": "click", "id": ident(look["state"], r'\[(\d+)\] button "赞'), "element": "赞"})
    finally:
        await hands.close()
    return result.get("status") == "failed" and "遮挡" in str(result.get("why") or "") and not play.cards, {
        "status": result.get("status"), "result": str(result.get("why") or ""), "steps": [result.get("line", "")]}


CHECKS = {"plain": plain, "name": name, "line": line, "hover": hover, "repeat": repeat, "resend": resend,
          "unsent": unsent, "expect": expect, "go_on": go_on, "why": why}


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="")
    parser.add_argument("--port", type=int, default=59630)
    parser.add_argument("--only", default="")
    args = parser.parse_args(argv)
    out = Path(args.out or tempfile.mkdtemp(prefix="optruth-")).resolve()
    out.mkdir(parents=True, exist_ok=True)
    site = f"http://127.0.0.1:{args.port}"
    server = subprocess.Popen([sys.executable, "-B", str(HERE / "opsite" / "serve.py"), str(args.port),
                               str(out / "site.log")])
    rows = []
    try:
        for _ in range(40):
            try:
                urllib.request.urlopen(site + "/api/state", timeout=2).read()
                break
            except OSError:
                time.sleep(0.25)
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(channel="msedge", headless=True)
            for label, check in CHECKS.items():
                if args.only and label not in args.only.split(","):
                    continue
                play = Play(browser, site, out / "allow")
                try:
                    ok, seen = await check(play)
                except Exception as error:
                    ok, seen = False, {"status": "error", "result": f"{type(error).__name__}: {error}"[:300], "steps": []}
                rows.append({"check": label, "ok": bool(ok), "status": seen.get("status"), "result": seen.get("result", ""),
                             "judged": play.judged, "cards": play.cards, "steps": seen.get("steps", [])})
                print(f"{'PASS' if ok else 'FAIL'}  {label}: ended {seen.get('status')} {seen.get('result', '')[:80]!r}, "
                      f"{len(play.cards)} cards, {play.judged} judge calls")
                for step in seen.get("steps", []):
                    print("      " + step.replace("\n", "\n      ")[:400])
                await play.page.context.close()
            await browser.close()
    finally:
        server.terminate()
        (out / "truth.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    failed = sum(not row["ok"] for row in rows)
    print(f"\n{len(rows) - failed}/{len(rows)} checks passed; kept in {out / 'truth.json'}")
    return failed


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
