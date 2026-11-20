"""Can a person find again what the pet's cards showed them, and what they liked?

    python tools/cardcheck/kept.py show <home> [--cards 12] [--like 4]
    python tools/cardcheck/kept.py look <home> <out dir> [--width 1240]

`show` has a running app's pet bring `--cards` finds one after another as its card does (GET
/api/feed/next?now=true, then a showing and an ending through POST /api/feed/react), likes every third of
the first `--like`'s worth, lets the rest go by themselves, and writes what it showed to <home>/kept.json.
`look` opens the app's page in headless Edge at `--width`, collects the titles of every find card a person
can reach: the main chat, and the page that lists past finds when the sidebar has one (#side-finds), with
its liked tab, scrolled to the end. It prints how many of the shown and of the liked are there, and in
what order, and saves a picture of each place.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright


def caller(home: Path):
    url = json.loads((home / "runtime/desktop/welcome.json").read_text(encoding="utf-8"))["url"]
    parts = urlsplit(url)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def call(path: str, body: dict | None = None) -> dict:
        request = urllib.request.Request(
            f"{parts.scheme}://{parts.netloc}/api/{path}", method="POST" if body is not None else "GET",
            data=None if body is None else json.dumps(body).encode(),
            headers={"Content-Type": "application/json",
                     "x-personagent-setup-token": parts.fragment.partition("token=")[2]})
        with opener.open(request, timeout=120) as answer:
            return json.loads(answer.read())

    return url, call


def show(home: Path, cards: int, like: int) -> None:
    _, call = caller(home)
    shown = []
    for n in range(cards):
        item = call("feed/next?now=true")["item"]
        if not item:
            break
        call("feed/react", {"id": item["id"], "action": "seen", "surface": "card", "rank": 0, "slot": item.get("slot", "")})
        liked = n % 3 == 0 and sum(s["liked"] for s in shown) < like
        if liked:
            call("feed/react", {"id": item["id"], "action": "like", "surface": "card", "rank": 0})
        call("feed/react", {"id": item["id"], "action": "end", "surface": "card", "rank": 0,
                            "end": "like" if liked else "timeout", "shown_s": 45})
        shown.append({"id": item["id"], "title": item["title"], "liked": liked})
        time.sleep(1.1)
    (home / "kept.json").write_text(json.dumps(shown, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"shown {len(shown)}, liked {sum(s['liked'] for s in shown)}")


def titles(page, box: str) -> list[str]:
    return page.evaluate("""sel => [...document.querySelectorAll(sel + ' .find h3')]
        .filter(n => n.offsetParent).map(n => n.textContent.trim())""", box)


def scrolled(page, box: str) -> list[str]:
    """Titles in `box` after scrolling its list to the end until no more come."""
    last = -1
    for _ in range(40):
        got = titles(page, box)
        if len(got) == last:
            return got
        last = len(got)
        page.evaluate("""sel => { const s = document.querySelector(sel + ' .chat-scroll');
            if (s) s.scrollTop = s.scrollHeight; }""", box)
        time.sleep(0.8)
    return titles(page, box)


def look(home: Path, out: Path, width: int) -> None:
    url, _ = caller(home)
    shown = json.loads((home / "kept.json").read_text(encoding="utf-8"))
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": width, "height": 860})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)[:200]))
        page.goto(url)
        page.wait_for_selector("#side-new", timeout=60000)
        time.sleep(3)
        places = {"chat": scrolled(page, "#chat-view .chat-main")}
        page.screenshot(path=str(out / f"chat-{width}.png"))
        entry = page.locator("#side-finds")
        if entry.count():
            if not entry.is_visible():
                page.click("#side-toggle")
                time.sleep(0.5)
            entry.click()
            time.sleep(2)
            page.screenshot(path=str(out / f"finds-{width}.png"))
            places["finds"] = scrolled(page, ".finds")
            page.click(".finds [data-tab=kept]")
            time.sleep(2)
            page.screenshot(path=str(out / f"liked-{width}.png"))
            places["liked"] = scrolled(page, ".finds")
        browser.close()
    reach = set(places["chat"]) | set(places.get("finds", ())) | set(places.get("liked", ()))
    liked = [s for s in shown if s["liked"]]
    report = {
        "width": width,
        "shown": len(shown),
        "shown_findable": sum(s["title"] in reach for s in shown),
        "shown_in_chat": sum(s["title"] in places["chat"] for s in shown),
        "shown_in_list": sum(s["title"] in places.get("finds", ()) for s in shown),
        "liked": len(liked),
        "liked_in_liked_list": sum(s["title"] in places.get("liked", ()) for s in liked),
        # The list's order against the order shown: newest first means the reverse of the showing order.
        "list_newest_first": [t for t in places.get("finds", ()) if t in {s["title"] for s in shown}]
        == [s["title"] for s in reversed(shown)],
        "places": {k: len(v) for k, v in places.items()},
        "page_errors": errors,
    }
    (out / f"kept-{width}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("what", choices=("show", "look"))
    parser.add_argument("home", type=Path)
    parser.add_argument("out", type=Path, nargs="?")
    parser.add_argument("--cards", type=int, default=12)
    parser.add_argument("--like", type=int, default=4)
    parser.add_argument("--width", type=int, default=1240)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    if args.what == "show":
        show(args.home, args.cards, args.like)
    else:
        look(args.home, args.out, args.width)
