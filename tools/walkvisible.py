"""What a person can see and set of the walks in a running app: the "+" menu's walk entry (shown, with its
reason, or missing), Settings' sections and its 外出 section (controls and the walk record), as headless
Edge draws them.

    python tools/walkvisible.py --home <home> [--shot <folder>] [--out run.json]

The app must be running on that home (runtime/desktop/welcome.json). Nothing of the home's .env is read.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--shot", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    url = json.loads((args.home / "runtime" / "desktop" / "welcome.json").read_text(encoding="utf-8"))["url"]
    address = urlsplit(url)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def call(path: str):
        request = urllib.request.Request(f"{address.scheme}://{address.netloc}/api/{path}",
                                         headers={"x-mibo-setup-token": address.fragment.partition("token=")[2]})
        try:
            with opener.open(request, timeout=60) as answer:
                return answer.status, json.loads(answer.read().decode())
        except urllib.error.HTTPError as error:
            return error.code, None

    status, walks = call("walks")
    row = {"compose": call("compose")[1], "walks_api": status,
           "record": len((walks or {}).get("record") or []), "menu": [], "sections": [], "walk_section": None}
    with sync_playwright() as play:
        browser = play.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1240, "height": 900})
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)[:200]))
        page.goto(url)
        page.wait_for_selector("#side-new", timeout=60000)
        time.sleep(2)
        # The main chat's "+": every entry with its hint.
        page.locator("#side-main").click()
        time.sleep(1)
        page.locator(".chat-attach:visible").first.click()
        time.sleep(1)
        row["menu"] = [" | ".join(t.strip() for t in item.inner_text().split("\n") if t.strip())
                       for item in page.locator(".plus-menu:visible .plus-item").all()]
        if args.shot:
            args.shot.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(args.shot / "menu.png"))
        page.keyboard.press("Escape")
        page.locator("#side-settings").click()
        time.sleep(1.5)
        row["sections"] = [n.strip() for n in page.locator(".setup-nav-item").all_inner_texts()]
        part = page.locator(".setup-nav-item[data-part=walks]")
        if part.count():
            part.click()
            time.sleep(2)
            section = page.locator(".setup-section-walks")
            row["walk_section"] = {
                "options": [n.strip() for n in section.locator(".setup-option-name").all_inner_texts()],
                "status": section.locator(".setup-walks-status").inner_text().strip(),
                "entries": [" / ".join(t.strip() for t in n.split("\n") if t.strip())
                            for n in section.locator(".setup-walks-entry").all_inner_texts()],
            }
            if args.shot:
                # The newest walk unfolded: its lists, the pages read and those it could not read.
                if section.locator(".setup-walks-head").count():
                    section.locator(".setup-walks-head").first.click()
                    time.sleep(0.5)
                page.screenshot(path=str(args.shot / "settings.png"))
                section.locator(".setup-card").last.screenshot(path=str(args.shot / "record.png"))
        row["page_errors"] = errors
        browser.close()
    print(json.dumps(row, ensure_ascii=False, indent=1))
    if args.out:
        args.out.write_text(json.dumps(row, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
