"""How well the page judge (mibo/web/pagejudge.py) tells what a page asks of the person, against the code's own
reading (WALL_JS and CHECK_JS, as a run's look decides today), on real pages.

    python tools/pagejudge_check.py capture <pages.jsonl> [--set tools/pagejudge_set.jsonl]
    python tools/pagejudge_check.py score <pages.jsonl> --env <.env with LLM_API_KEY and LLM_BASE_URL> [--model M]

`capture` opens each address of the set signed out in Edge through Playwright (a fresh profile each; headless,
or a window off screen for a row marked "headed"), and keeps what a run's look prints of it, its hints and the
code's reading. Addresses written local:/... are a practice site of this script's own (a sign-in form, a code,
a page just after a sign-in, an article under a sign-up box). Each row's "expect" is what a person sees on it;
check a capture by eye before scoring, since sites change. `score` asks the model once per page (and a second
time over the same pages, which the judge must answer without a call) and prints each page and the totals; the
key is read from the file, never printed."""
from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PRACTICE = {
    "/login": "<title>Sign in - Practice Mail</title><h1>Sign in to Practice Mail</h1><form method=post>"
              "<label>Email <input name=email type=email></label><label>Password <input name=pw type=password>"
              "</label><button>Sign in</button></form><p><a href=#>Forgot password?</a> · <a href=#>Create account</a>",
    "/code": "<title>Verify - Practice Mail</title><h1>Enter the code</h1><p>We sent a 6-digit code to your phone."
             "<form><input name=otp autocomplete=one-time-code placeholder='6-digit code'><button>Verify</button></form>",
    "/inbox": "<title>Inbox - Practice Mail</title><header>Practice Mail <img class=avatar alt='demo avatar' "
              "src='data:image/gif;base64,R0lGODlhAQABAAAAACw='> demo@example.com · <a href=#>Sign out</a></header>"
              "<h1>Inbox</h1><ul>" + "".join(f"<li><b>Alice {n}</b> Lunch on Friday? Shall we meet at noon near the "
                                             f"station, message {n}</li>" for n in range(12)) + "</ul>",
    "/home": "<title>首页 - 练习站</title><header>练习站 <span class=user-info>你好，demo</span> <a href=#>退出登录</a>"
             "</header><h1>为你推荐</h1>" + "".join(f"<article><h2>第 {n} 篇：城市里的慢生活</h2><p>周末去河边走走，"
                                               f"看看书，喝杯咖啡，这一篇讲的是怎样在城市里放慢节奏。</p></article>"
                                               for n in range(10)),
    "/story": "<title>Why cities need trees - Practice Stories</title><article><h1>Why cities need trees</h1>"
              + "".join(f"<p>Paragraph {n}: trees cool the streets, hold the rain and make a walk pleasant; a city "
                        f"that plants them gains shade, cleaner air and quieter roads over the years.</p>"
                        for n in range(25))
              + "</article><div style='position:fixed;inset:20% 30%;background:#fff;border:1px solid #888;"
                "padding:20px'><button aria-label=Close>×</button><h2>Sign up to keep reading</h2>"
                "<button>Continue with Google</button> <button>Continue with email</button>"
                "<p>Already have an account? <a href=#>Sign in</a></p></div>",
}


class Practice(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = ("<!doctype html><meta charset=utf-8>" + PRACTICE.get(self.path, "")).encode()
        self.send_response(200 if self.path in PRACTICE else 404)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass


def code_reading(wall: dict, layer: dict) -> str:
    """What a run's look decides today, in the judge's four words."""
    from mibo.web import signin
    seen = signin.judge(wall or {}, layer or {}, None, False)
    kind = seen.get("kind") or ""
    return ("check" if kind == "verification" else "account" if kind in ("sign_in", "sign_in_overlay")
            else "box" if seen.get("prompt") else "readable")


async def capture_one(browser, row: dict, base: str) -> dict:
    from mibo.web import operate, signin
    from mibo.web.pageops import Page
    from mibo.web.tabs import PlaywrightTab
    url = row["url"].replace("local:", base)
    context = await browser.new_context(viewport={"width": 1280, "height": 860}, locale="zh-CN")
    page = await context.new_page()
    out = {**row, "opened": url}
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(5)
        state = await Page(PlaywrightTab(page)).state()
        wall = await page.evaluate(operate.WALL_JS)
        layer = await page.evaluate(f"({signin.CHECK_JS})({{}})")
        final = page.url
        out.update(final=final, title=await page.title(), text=state,
                   hints={**{k: layer.get(k) for k in ("kind", "evidence", "password", "form", "prompt", "account")},
                          "flow": signin.in_flow(final)},
                   code=code_reading(wall, layer))
        await page.screenshot(path=str(SHOTS / f"{len(list(SHOTS.glob('*.png'))):02d}.png"))
    except Exception as error:
        out["error"] = " ".join(str(error).split())[:200]
    await context.close()
    return out


async def capture(out: Path, rows: list[dict]) -> None:
    from playwright.async_api import async_playwright
    site = ThreadingHTTPServer(("127.0.0.1", 0), Practice)
    threading.Thread(target=site.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{site.server_address[1]}"
    got = []
    async with async_playwright() as p:
        quiet = await p.chromium.launch(channel="msedge", headless=True)
        shown = None
        for row in rows:
            if row.get("headed") and shown is None:
                # A real window, off screen: some sites refuse a headless visitor outright.
                shown = await p.chromium.launch(channel="msedge", headless=False,
                                                args=["--window-position=-4000,0", "--window-size=1280,860"])
            got.append(await capture_one(shown if row.get("headed") else quiet, row, base))
            print(json.dumps({k: got[-1].get(k) for k in ("url", "final", "title", "code", "error")}, ensure_ascii=False))
        await quiet.close()
        if shown is not None:
            await shown.close()
    site.shutdown()
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in got), encoding="utf-8")


def env_value(path: Path, name: str) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith(name + "="):
            return line.split("=", 1)[1].strip().strip('"')
    return ""


async def score(rows: list[dict], ask, lang: str) -> dict:
    from mibo.web import pagejudge
    rows = [r for r in rows if not r.get("error")]
    table, right, code_right = [], 0, 0
    began = time.monotonic()
    for row in rows:
        page = {"url": row["final"], "title": row["title"], "text": row["text"]}
        verdict = await pagejudge.judge(page, row["hints"], ask, lang)
        right += verdict.asks == row["expect"]
        code_right += row["code"] == row["expect"]
        table.append({"url": row["url"], "expect": row["expect"], "code": row["code"], "judge": verdict.asks,
                      "source": verdict.source, "say": verdict.say})
        print(f"{'ok ' if verdict.asks == row['expect'] else 'NO '} {row['expect']:9} code={row['code']:9} "
              f"judge={verdict.asks:9} {verdict.source:5} {row['url'][:60]}  {verdict.say}")
    took = time.monotonic() - began
    again = [await pagejudge.judge({"url": r["final"], "title": r["title"], "text": r["text"]}, r["hints"], ask, lang)
             for r in rows]
    by = {}
    for want in pagejudge.ASKS:
        mine = [t for t in table if t["expect"] == want]
        by[want] = {"pages": len(mine), "judge": sum(t["judge"] == want for t in mine),
                    "code": sum(t["code"] == want for t in mine)}
    return {"pages": len(rows), "judge_right": right, "code_right": code_right, "by_kind": by,
            "seconds_per_page": round(took / max(1, len(rows)), 2),
            "second_pass_calls": sum(v.source == "model" for v in again), "rows": table}


def main(argv: list[str]) -> int:
    global SHOTS
    what, path = argv[0], Path(argv[1])
    flag = lambda name, default="": argv[argv.index(name) + 1] if name in argv else default  # noqa: E731
    if what == "capture":
        rows = [json.loads(line) for line in Path(flag("--set", str(ROOT / "tools/pagejudge_set.jsonl")))
                .read_text(encoding="utf-8").splitlines() if line.strip()]
        SHOTS = path.parent / (path.stem + "-shots")
        SHOTS.mkdir(parents=True, exist_ok=True)
        asyncio.run(capture(path, rows))
        return 0
    from mibo.review import endpoint
    from mibo.web import pagejudge
    env = Path(flag("--env"))
    usage: dict = {}
    ask = endpoint(env_value(env, "LLM_BASE_URL"), env_value(env, "LLM_API_KEY"),
                   flag("--model", "deepseek/deepseek-v4.1-flash"), usage=usage, max_tokens=pagejudge.MAX_TOKENS)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    result = asyncio.run(score(rows, ask, flag("--lang", "zh")))
    result["usage"] = usage
    (path.parent / (path.stem + "-score.json")).write_text(json.dumps(result, ensure_ascii=False, indent=1),
                                                           encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, ensure_ascii=False, indent=1))
    return 0


SHOTS = Path(".")

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
