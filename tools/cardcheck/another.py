"""How long "Another" on the pet's card takes, against a running app.

    python tools/cardcheck/another.py <home> [--presses 5] [--pause 6] [--old-card] [--out file.json]

Plays the card's own part over the app's API (static/welcome/card.js): asks for a find as the pet's menu
does, says it was seen, waits `--pause` seconds as a person reading it would, then presses "Another":
the card out is ended as passed over and the next asked for the way the card asks (`--old-card`: the way it
asked before the app kept a choice ready, first after 0.3 s and then every 1.2 s). Prints, per press,
the seconds from the press to the next find in hand and whether it came with the character's sentence;
for a find that came without one, the seconds until the sentence followed (where the app has that).
No window is opened and no model is called from here: the app's own model setting decides.
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

# The card before a choice was kept ready: the first ask this long after a press, then this often, for
# this long (seconds). The card now asks once, at once.
FIRST, EVERY, FOR = 0.3, 1.2, 25.0


class App:
    def __init__(self, home: Path):
        url = json.loads((home / "runtime" / "desktop" / "welcome.json").read_text(encoding="utf-8"))["url"]
        address = urlsplit(url)
        self.base = f"{address.scheme}://{address.netloc}"
        self.token = address.fragment.partition("token=")[2]
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def call(self, path: str, body: dict | None = None):
        request = urllib.request.Request(
            self.base + path, data=None if body is None else json.dumps(body).encode(),
            method="GET" if body is None else "POST",
            headers={"Content-Type": "application/json", "x-personagent-setup-token": self.token})
        try:
            with self.opener.open(request, timeout=60) as answer:
                return json.loads(answer.read().decode() or "null")
        except urllib.error.HTTPError as error:
            return {"error": error.code, "body": error.read().decode()[:300]}


def react(app: App, found: dict, action: str, **more) -> None:
    app.call("/api/feed/react", {"id": found["id"], "action": action, "surface": "card", "rank": 0,
                                 "slot": found.get("slot") or "", **more})


def ask(app: App, wait_s: float = FOR, first: float = 0.0, skip: str = "", once: bool = False) -> tuple[dict | None, float]:
    """The next find the way the card asks for it, and the seconds it took; `once`: a single ask."""
    began = time.monotonic()
    wait = first
    while time.monotonic() - began < wait_s:
        time.sleep(wait)
        wait = EVERY
        found = (app.call("/api/feed/next?now=true&lang=zh") or {}).get("item")
        if found and found["id"] != skip:
            return found, time.monotonic() - began
        if once:
            break
    return None, time.monotonic() - began


def sentence(app: App, found: dict, wait_s: float = 20.0) -> tuple[str, float]:
    """The sentence that follows a find shown without one (GET /api/feed/line), and after how long."""
    began = time.monotonic()
    while time.monotonic() - began < wait_s:
        answer = app.call(f"/api/feed/line?id={found['id']}")
        if not isinstance(answer, dict) or "error" in answer:
            return "", 0.0
        if answer.get("line") or not answer.get("wait"):
            return answer.get("line") or "", time.monotonic() - began
        time.sleep(1.0)
    return "", time.monotonic() - began


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("home", type=Path)
    parser.add_argument("--presses", type=int, default=5)
    parser.add_argument("--pause", type=float, default=6.0, help="seconds a find is out before the press")
    parser.add_argument("--old-card", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    app = App(args.home)
    found, took = ask(app, wait_s=60.0)
    if not found:
        sys.exit("no find came within a minute")
    print(f"first find after {took:.1f}s: {found['title'][:50]}")
    react(app, found, "seen")
    rows = []
    for press in range(args.presses):
        time.sleep(args.pause)
        began = time.monotonic()
        react(app, found, "end", end="next", shown_s=args.pause)
        after, took = ask(app, first=FIRST, skip=found["id"]) if args.old_card else ask(app, skip=found["id"], once=True)
        if not after:
            rows.append({"press": press + 1, "seconds": round(took, 2), "found": False})
            print(f"press {press + 1}: nothing after {took:.1f}s")
            break
        whole = time.monotonic() - began
        react(app, after, "seen")
        row = {"press": press + 1, "seconds": round(whole, 2), "found": True, "with_sentence": bool(after.get("line")),
               "why": (after.get("why") or {}).get("text", ""), "title": after["title"][:60]}
        if not after.get("line"):
            line, later = sentence(app, after)
            row.update(sentence_after=round(later, 2) if line else None)
        rows.append(row)
        print(f"press {press + 1}: {whole:.2f}s, sentence {'with it' if row['with_sentence'] else row.get('sentence_after')}"
              f" | {row['why']} | {row['title']}")
        found = after
    react(app, found, "end", end="hushed", shown_s=1)
    got = [row["seconds"] for row in rows if row["found"]]
    summary = {"presses": len(rows), "median_s": sorted(got)[len(got) // 2] if got else None,
               "worst_s": max(got) if got else None,
               "with_sentence": sum(1 for row in rows if row.get("with_sentence")),
               "sentence_later": sum(1 for row in rows if row.get("sentence_after")), "rows": rows}
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, ensure_ascii=False))
    if args.out:
        args.out.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
