"""Whether saying no to a topic on the pet's card is felt in the cards that follow, against a running app.

    python tools/cardcheck/less.py <home> --subject games [--about topic] [--cards 12] [--undo] [--out file.json]

Brings finds the way the card does until one is on `--subject` (a key of persona_agent/subjects.py, read
from the find's own title and words), turns it down as the card's "Not interested" does with `--about`
(thing: this one; topic: this kind of topic), then brings `--cards` more and counts how many are on that
subject again. With `--undo` the no is taken back first (POST /api/feed/undo) and the same count is made.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from persona_agent import subjects  # noqa: E402
from tools.cardcheck.another import App, ask, react  # noqa: E402


def about(found: dict) -> set[str]:
    """The subjects a find's own words name, each with the one it sits under."""
    keys = subjects.of(found["title"], " ".join((found.get("text") or "", found.get("site") or "")))
    return {k for key in keys for k in (key, subjects.SUBJECTS[key][0]) if k}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("home", type=Path)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--about", default="topic", choices=("thing", "topic"))
    parser.add_argument("--cards", type=int, default=12)
    parser.add_argument("--undo", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    app = App(args.home)
    found, _ = ask(app, wait_s=60.0)
    passed = 0
    while found and args.subject not in about(found):
        react(app, found, "seen")
        react(app, found, "end", end="hushed", shown_s=1)
        found, _ = ask(app, skip=found["id"])
        passed += 1
    if not found:
        sys.exit(f"no find on {args.subject} came ({passed} passed)")
    topic = found.get("topic") or {}
    print(f"turned down ({args.about}) after {passed} others: {found['title'][:60]} | topic on the card: {topic.get('name', '-')}")
    react(app, found, "seen")
    react(app, found, "end", end="close", shown_s=8)
    # As the card says it: about the topic, with the feature the card named for it.
    react(app, found, "skip", said={"about": "topic", "key": topic["key"]} if args.about == "topic" else {"about": "thing"})
    if args.undo:
        print("undo:", app.call("/api/feed/undo", {"id": found["id"]}))
    rows, last = [], found
    for _ in range(args.cards):
        after, took = ask(app, skip=last["id"])
        if not after:
            break
        react(app, after, "seen")
        react(app, after, "end", end="hushed", shown_s=1)
        rows.append({"again": args.subject in about(after), "subjects": sorted(about(after)), "title": after["title"][:60],
                     "why": (after.get("why") or {}).get("text", ""), "seconds": round(took, 2)})
        print(("  SAME " if rows[-1]["again"] else "       ") + f"{rows[-1]['title']} | {rows[-1]['why']}")
        last = after
    summary = {"subject": args.subject, "about": args.about, "undone": args.undo, "cards": len(rows),
               "on_it_again": sum(row["again"] for row in rows), "rows": rows}
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, ensure_ascii=False))
    if args.out:
        args.out.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
