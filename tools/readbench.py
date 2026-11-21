"""Thirty chat questions that need a live page, asked of a running Mibo, each reply scored against the page.

    python tools/readbench.py <home> <out.jsonl> [--only H1,S3,...] [--calls <calls.json>]

Ten hot lists and rankings (asked without an address), ten pages a script draws (asked with the address)
and ten ordinary articles (asked with the address). Each question goes to a new chat of the app running in
<home> (POST /api/chat); the seconds, the model calls and their cost (from --calls, a file a counting hook
in the app's process keeps as {"calls", "cost"}; else the cost from /api/usage) and the reply are kept.
The page as a person sees it is read right after, in headless Edge (Playwright, a profile under the out
file's folder), or from the list's own public API; a reply is "full" when it names
at least half of the page's first ten rows (at least 5) or, for an article, most of the facts listed here.
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

HEADERS = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/126.0 Safari/537.36"), "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}

# (id, question, where the page is, how the truth is read: "page" rendered rows, "api:<name>", or facts).
QUESTIONS = [
    ("H1", "今天的微博热点", "https://s.weibo.com/top/summary", "page"),
    ("H2", "知乎热榜现在前几是什么", "https://www.zhihu.com/hot", "api:zhihu"),
    ("H3", "B站排行榜今天前几名是什么视频", "https://www.bilibili.com/v/popular/rank/all", "api:bili"),
    ("H4", "百度热搜前十是什么", "https://top.baidu.com/board?tab=realtime", "api:baidu"),
    ("H5", "今日头条热榜上现在有什么", "https://www.toutiao.com/", "api:toutiao"),
    ("H6", "What's trending on GitHub today?", "https://github.com/trending", "page"),
    ("H7", "What are the top stories on Hacker News right now?", "https://news.ycombinator.com/", "api:hn"),
    ("H8", "V2EX 今天最热的帖子有哪些", "https://www.v2ex.com/?tab=hot", "api:v2ex"),
    ("H9", "What's on the Product Hunt leaderboard today?", "https://www.producthunt.com/", "page"),
    ("H10", "掘金热榜今天有哪些文章", "https://juejin.cn/hot/articles", "page"),
    ("S1", "这个页面上现在有哪些热门视频？https://www.bilibili.com/v/popular/all",
     "https://www.bilibili.com/v/popular/all", "page"),
    ("S2", "What new crates are listed on the front page of https://crates.io/ right now?", "https://crates.io/", "page"),
    ("S3", "掘金热门文章这页都有啥 https://juejin.cn/hot/articles", "https://juejin.cn/hot/articles", "page"),
    ("S4", "36氪快讯最新几条是什么 https://36kr.com/newsflashes", "https://36kr.com/newsflashes", "page"),
    ("S5", "B站每周必看这期有哪些视频 https://www.bilibili.com/v/popular/weekly",
     "https://www.bilibili.com/v/popular/weekly", "page"),
    ("S6", "抖音热点页现在有什么 https://www.douyin.com/hot", "https://www.douyin.com/hot", "page"),
    ("S7", "Which categories are at the top of https://www.twitch.tv/directory now?",
     "https://www.twitch.tv/directory", "page"),
    ("S8", "今日头条首页现在推荐了哪些新闻 https://www.toutiao.com/", "https://www.toutiao.com/", "page"),
    ("S9", "What does https://crates.io/crates/serde say about this crate (what it is, latest version, downloads)?",
     "https://crates.io/crates/serde", ["serialization", "framework", "download"]),
    ("S10", "What is trending in the US on Google Trends right now? https://trends.google.com/trending?geo=US",
     "https://trends.google.com/trending?geo=US", "page"),
    ("A1", "这个页面列了 Python 3.14 哪些主要新特性？https://www.python.org/downloads/release/python-3140/",
     "https://www.python.org/downloads/release/python-3140/",
     ["free-thread", "t-string", "zstd", "649", "734", "uuid"]),
    ("A2", "What does this page say about the new interactive interpreter? https://docs.python.org/3/whatsnew/3.13.html",
     "https://docs.python.org/3/whatsnew/3.13.html", ["multi-line", "color", "PyPy", "F1", "F2", "F3"]),
    ("A3", "这篇文章的核心观点是什么？https://paulgraham.com/greatwork.html", "https://paulgraham.com/greatwork.html",
     ["好奇", "兴趣", "努力", "选择"]),
    ("A4", "According to this page, who started Hacker News and when? https://en.wikipedia.org/wiki/Hacker_News",
     "https://en.wikipedia.org/wiki/Hacker_News", ["Paul Graham", "2007", "Y Combinator"]),
    ("A5", "这页面说野外大熊猫大概有多少只？https://zh.wikipedia.org/wiki/大熊猫",
     "https://zh.wikipedia.org/wiki/%E5%A4%A7%E7%86%8A%E7%8C%AB", ["1864", "易危"]),
    ("A6", "这个项目支持哪些浏览器，能用哪些语言写？https://github.com/microsoft/playwright",
     "https://github.com/microsoft/playwright", ["Chromium", "WebKit", "Firefox", "Python", "Java", ".NET"]),
    ("A7", "React 19 这篇博客里说了哪些新功能？https://react.dev/blog/2024/12/05/react-19",
     "https://react.dev/blog/2024/12/05/react-19", ["Action", "useActionState", "useOptimistic", "use"]),
    ("A8", "这期周刊开头那篇讲了什么？https://www.ruanyifeng.com/blog/2026/11/weekly-issue-420.html",
     "https://www.ruanyifeng.com/blog/2026/11/weekly-issue-420.html", ["分心", "Hugging Face", "Agent", "专注"]),
    ("A9", "这篇推荐了哪些作品？https://sspai.com/post/119337", "https://sspai.com/post/119337",
     ["茫然女王", "行走之人", "紧急呼救", "狐狸女士", "罗梅莉亚"]),
    ("A10", "Summarize the history section of https://en.wikipedia.org/wiki/Large_language_model in a few points",
     "https://en.wikipedia.org/wiki/Large_language_model", ["transformer", "GPT", "BERT", "2017"]),
]


def _api(home: Path, path: str, body=None, timeout: float = 300):
    url = json.loads((home / "runtime" / "desktop" / "welcome.json").read_text(encoding="utf-8"))["url"]
    parts = urlsplit(url)
    request = urllib.request.Request(f"{parts.scheme}://{parts.netloc}/api/{path}",
                                     data=json.dumps(body).encode() if body is not None else None,
                                     method="POST" if body is not None else "GET",
                                     headers={"Content-Type": "application/json",
                                              "x-mibo-setup-token": parts.fragment.partition("token=")[2]})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as answer:
        return json.loads(answer.read().decode())


def _usage(home: Path, calls: Path | None) -> dict:
    if calls is not None:
        try:
            return json.loads(calls.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"calls": 0, "cost": 0.0}
    today = (_api(home, "usage").get("usage") or {}).get("today") or {}
    return {"calls": 0, "cost": today.get("cost") or 0.0}


def _api_titles(name: str) -> list[str]:
    with httpx.Client(headers=HEADERS, timeout=15, follow_redirects=True) as http:
        if name == "zhihu":
            data = http.get("https://api.zhihu.com/topstory/hot-list", params={"limit": 20}).json()
            return [c["target"]["title"] for c in data["data"]]
        if name == "bili":
            data = http.get("https://api.bilibili.com/x/web-interface/ranking/v2", params={"rid": 0, "type": "all"}).json()
            return [v["title"] for v in data["data"]["list"]]
        if name == "baidu":
            card = http.get("https://top.baidu.com/api/board", params={"platform": "pc", "tab": "realtime"}).json()
            card = card["data"]["cards"][0]
            return [e["word"] for e in card.get("topContent", []) + card["content"]]
        if name == "toutiao":
            data = http.get("https://www.toutiao.com/hot-event/hot-board/", params={"origin": "toutiao_pc"}).json()
            return [e["Title"] for e in data["data"]]
        if name == "hn":
            ids = http.get("https://hacker-news.firebaseio.com/v0/topstories.json").json()[:10]
            return [http.get(f"https://hacker-news.firebaseio.com/v0/item/{i}.json").json().get("title", "") for i in ids]
        if name == "v2ex":
            return [t["title"] for t in http.get("https://www.v2ex.com/api/topics/hot.json").json()]
    return []


async def _page(context, url: str) -> dict:
    """The page as a person sees it: reader.js's rows and text after a settle and two screens."""
    from mibo.web import read as reading
    page = await context.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)
        rows: dict = {}
        data = {}
        for _ in range(3):
            data = await asyncio.wait_for(page.evaluate(reading.READER, {}), 30)
            reading.merge(rows, data.get("rows") or [])
            await page.mouse.wheel(0, 1600)
            await page.wait_for_timeout(1200)
        return {"rows": [r.get("title") or "" for r in rows.values()], "text": data.get("text") or "",
                "wall": (data.get("wall") or {}).get("kind") or ""}
    finally:
        await page.close()


def _norm(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", text.lower())


def _named(title: str, reply: str) -> bool:
    """Whether the reply names this row: a run of its words (6 characters of Chinese, 12 of Latin) is in it."""
    t = _norm(title)
    if not t:
        return False
    size = 6 if re.search(r"[㐀-鿿]", t) else 12
    if len(t) <= size:
        return t in reply
    return any(t[i:i + size] in reply for i in range(len(t) - size + 1))


def score(record: dict) -> None:
    reply = _norm(record.get("reply", ""))
    if record.get("facts"):
        hit = [f for f in record["facts"] if _norm(f) in reply]
        record["hit"], record["of"] = len(hit), len(record["facts"])
        record["full"] = len(hit) >= max(1, round(0.6 * len(record["facts"])))
        return
    first = [t for t in record.get("truth", []) if t.strip()][:10]
    hit = [t for t in first if _named(t, reply)]
    record["hit"], record["of"] = len(hit), len(first)
    record["full"] = bool(first) and len(hit) >= min(5, max(1, len(first) // 2))


async def main(home: Path, out: Path, only: set, calls: Path | None) -> None:
    from playwright.async_api import async_playwright

    from mibo.installed_browser import find_browser
    sys.stdout.reconfigure(encoding="utf-8")
    async with async_playwright() as driver:
        context = await driver.chromium.launch_persistent_context(
            str(out.parent / "truth-profile"), executable_path=str(find_browser()), headless=True,
            viewport={"width": 1280, "height": 900}, locale="zh-CN")
        try:
            for ident, question, where, how in QUESTIONS:
                if only and ident not in only:
                    continue
                chat = _api(home, "chats", {}).get("id")
                before = _usage(home, calls)
                start = time.monotonic()
                try:
                    answer = await asyncio.to_thread(_api, home, "chat", {"text": question, "chat": chat})
                except Exception as exc:
                    answer = {"error": f"{type(exc).__name__}: {exc}"[:200]}
                seconds = round(time.monotonic() - start, 1)
                await asyncio.sleep(1.0)
                after = _usage(home, calls)
                said = [m for m in answer.get("messages", []) if m.get("role") == "assistant"]
                record = {"id": ident, "q": question, "s": seconds,
                          "calls": after["calls"] - before["calls"],
                          "cost": round((after["cost"] or 0) - (before["cost"] or 0), 6),
                          "reply": "\n".join(m.get("text") or "" for m in said),
                          "trace": [t for m in said for t in m.get("trace") or []],
                          "sources": [s.get("url") for m in said for s in m.get("sources") or []],
                          "error": answer.get("error", "")}
                if isinstance(how, list):
                    record["facts"] = how
                else:
                    try:
                        record["truth"] = (_api_titles(how[4:]) if how.startswith("api:")
                                           else (await _page(context, where))["rows"])
                    except Exception as exc:
                        record["truth"], record["truth_error"] = [], type(exc).__name__
                score(record)
                with out.open("a", encoding="utf-8") as kept:
                    kept.write(json.dumps(record, ensure_ascii=False) + "\n")
                print(f"{ident:4} {'FULL' if record['full'] else 'part'} {record['hit']}/{record['of']} "
                      f"{seconds:5.1f}s calls={record['calls']} cost={record['cost']} "
                      f"steps={' > '.join(t.get('tool', '') + ' ' + str(t.get('what', ''))[:30] for t in record['trace'])}",
                      flush=True)
        finally:
            await context.close()


if __name__ == "__main__":
    picked = set()
    if "--only" in sys.argv:
        picked = set(sys.argv[sys.argv.index("--only") + 1].split(","))
    counted = Path(sys.argv[sys.argv.index("--calls") + 1]) if "--calls" in sys.argv else None
    asyncio.run(main(Path(sys.argv[1]), Path(sys.argv[2]), picked, counted))
