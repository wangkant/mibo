"""How many of today's Chinese finds open to a sign-in or a check for a person signed out, before and after the
recommender holds a site's finds of a kind back (feed.walled).

Fetches the zh sources, takes up to 40 finds (a few from each source in turn), opens each in a fresh signed-out
headless Edge, reads the page as the app does (web/signin.PAGE_JS) and asks the model (web/pagejudge.py).
"Before": every find shown, so every walled one is opened. "After": the finds opened in order, and once one of a
site and kind opened to a wall its site's others of that kind are held back, so only the first is met.

    python tools/wallcount.py <out.json> <.env with LLM_BASE_URL and LLM_API_KEY> [model]
"""
import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mibo.review import endpoint
from mibo.sources import base, china
from mibo.web import pagejudge, signin

FINDS, PER_SOURCE, PAGE_S = 40, 3, 30


async def finds() -> list:
    picked = []
    async with base.client() as http:
        got = await asyncio.gather(*(s.fetch(http) for s in china.SOURCES if s.lang == "zh"), return_exceptions=True)
    lists = [[f.item for f in found[:PER_SOURCE]] for found in got if isinstance(found, list) and found]
    while len(picked) < FINDS and any(lists):
        for row in lists:
            if row and len(picked) < FINDS:
                picked.append(row.pop(0))
    return picked


async def read(browser, url: str) -> dict:
    """The page as the app reads it, signed out in a fresh context; at most PAGE_S seconds."""
    context = await browser.new_context(viewport={"width": 1280, "height": 860}, locale="zh-CN")
    try:
        page = await context.new_page()

        async def go() -> dict:
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            await page.wait_for_timeout(2000)
            return await page.evaluate(signin.PAGE_JS)
        return await asyncio.wait_for(go(), PAGE_S)
    except Exception as error:
        return {"url": url, "title": "", "text": f"(the page did not load: {type(error).__name__})", "chars": 0,
                "password": False}
    finally:
        # A page that will not close (a video still loading) is left to the browser's own close at the end.
        await asyncio.wait([asyncio.ensure_future(context.close())], timeout=10)


async def main(out: Path, env: Path, model: str) -> None:
    config = dict(line.split("=", 1) for line in env.read_text(encoding="utf-8").splitlines()
                  if "=" in line and not line.startswith("#"))
    ask = endpoint(config["LLM_BASE_URL"].strip(), config["LLM_API_KEY"].strip(), model, max_tokens=300)
    items = await finds()
    rows, held, met = [], set(), 0
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="msedge", headless=True)
        seen = [await read(browser, item.url) for item in items]
        await asyncio.wait([asyncio.ensure_future(browser.close())], timeout=20)
    for item, page in zip(items, seen):
        plain = page["chars"] >= 2500 and not page["password"] and not signin.in_flow(page["url"])
        verdict = pagejudge.Verdict("readable", "", "plain") if plain else \
            await pagejudge.judge(page, {"password": page["password"], "flow": signin.in_flow(page["url"])}, ask, "zh")
        walled = verdict.asks in ("account", "check")
        place = (item.site, item.kind)
        if walled and place not in held:
            met += 1
            held.add(place)
        rows.append({"url": item.url, "site": item.site, "kind": item.kind, "source": item.source,
                     "landed": page["url"], "asks": verdict.asks, "by": verdict.source, "say": verdict.say})
        print(len(rows), item.site, verdict.asks, item.url, flush=True)
    walls = sum(1 for row in rows if row["asks"] in ("account", "check"))
    result = {"finds": len(rows), "walls_before": walls, "walls_after": met,
              "walled_places": sorted(f"{s} {k}" for s, k in held), "rows": rows}
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print("finds", len(rows), "walls before", walls, "after", met)


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1]), Path(sys.argv[2]),
                     sys.argv[3] if len(sys.argv) > 3 else "deepseek/deepseek-v4.1-flash"))
