"""What Settings › 推荐 does to what is shown, offline: simulated people (people.py) through the app's own
path (sim.py's rank1 arm, no model call), once as they are and once per setting.

    python tools/recsim/settings.py --snapshot <dir> --work <dir> [--people zhou,ling,chen,mia] [--days 14]

Scenarios, each set the way the page sets it (profile.edit, POST /api/profile/taste) or the chat says it
(profile.like, as memory._tell_profile passes it on):
- base: nothing set;
- less, more: the pace;
- quiet: quiet hours QUIET (cards inside them are counted);
- topic_more, topic_less: a lean on the first picked topic the person cares least about (its share of cards);
- wish, like: on the first chat evening from day WISH_DAY, "这周想多看点 X" or "喜欢 X" about a subject the person
  is indifferent to (its share while a wish lasts and after);
- remove: on the first chat evening from day REMOVE_DAY, the strongest source the reactions taught is taken out
  (its share before and after).
Prints one table, averaged over the people; every card goes to <work>/<scenario>/<person>.json.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import sim  # noqa: E402
from people import OFFERED, SUBJECTS  # noqa: E402
from persona_agent import profile, taste  # noqa: E402

SCENARIOS = ("base", "less", "more", "quiet", "topic_more", "topic_less", "wish", "like", "remove")
QUIET = {"from": "19:00", "to": "23:00"}
WISH_DAY, REMOVE_DAY = 2, 7


def hours(text: str) -> float:
    return int(text[:2]) + int(text[3:]) / 60


def in_quiet(hour: float) -> bool:
    start, end = hours(QUIET["from"]), hours(QUIET["to"])
    return start <= hour < end if start < end else hour >= start or hour < end


async def one(scenario: str, truth, labels: dict, items: dict, at: dict, pop: dict, work: Path, days: int) -> dict:
    seed = sim.EVERYONE.index(truth) + 1
    who = sim.person(truth, labels, seed * 100 + 1)
    arm = sim.Arm("rank1", who, items, at, work / scenario / truth.name, {}, pop)
    sim.features("rank1", labels)
    rt = arm.runtime
    topics = arm.topics()
    # The picked topic whose subjects the person cares least about, and a subject they are indifferent to.
    # Someone who picked no topics has none to lean on: its share stays 0.
    subjects_of = {t: {s for s, o in OFFERED.items() if o == t} for t in topics}
    subjects_of[""] = set()
    lean_topic = min(topics, key=lambda t: max((truth.interests.get(s, 0) for s in subjects_of[t]), default=0),
                     default="")
    wish_subject = min(s for s in SUBJECTS if s not in truth.interests)
    note = {"topic": lean_topic, "wish": wish_subject, "removed": "", "said_at": None}
    if scenario in ("less", "more"):
        profile.edit(rt, {"pace": scenario})
    elif scenario == "quiet":
        profile.edit(rt, {"quiet_hours": QUIET})
    elif scenario in ("topic_more", "topic_less"):
        profile.edit(rt, {"leans": {"topic:" + lean_topic.casefold(): 1 if scenario == "topic_more" else -1}})
    says = who.says

    def said(day: float, cards: list) -> list:
        out = says(day, cards)
        if scenario in ("wish", "like") and day >= WISH_DAY and note["said_at"] is None:
            note["said_at"] = day
            word = SUBJECTS[wish_subject][2]
            out.append(("like", f"这周想多看点{word}" if scenario == "wish" else f"喜欢{word}"))
        if scenario == "remove" and day >= REMOVE_DAY and note["said_at"] is None:
            note["said_at"] = day
            taste.train(rt)
            takes = [row for row in taste.taught(rt, "zh")["takes"] if row["key"].startswith("origin:")]
            if takes:
                note["removed"] = takes[0]["key"]
                profile.edit(rt, {"leans": {takes[0]["key"]: 0}})
        return out
    who.says = said
    got = await sim.run(arm, days, seed * 100 + 2)
    cards = got["cards"]
    out = {"cards_a_day": len(cards) / days, "worth": sum(c["worth"] for c in cards) / max(1, len(cards)),
           "opened": sum(c["open"] for c in cards) / max(1, len(cards)),
           "in_quiet": sum(in_quiet(c["hour"]) for c in cards) / days, **note}

    def share(rows: list, test) -> float | None:
        return sum(map(test, rows)) / len(rows) if rows else None

    def when(c: dict) -> float:
        return c["day"] + c["hour"] / 24

    def origin(c: dict) -> str:
        return "origin:" + (c["origin"] if c["origin"].startswith("site:") else "src:" + c["origin"])

    out["topic_share"] = share(cards, lambda c: c["subject"] in subjects_of[lean_topic])
    start = note["said_at"]
    if start is not None:
        def wished(c: dict) -> bool:
            return c["subject"] == wish_subject
        out["wish_during"] = share([c for c in cards if start <= when(c) < start + 3], wished)
        out["wish_after"] = share([c for c in cards if when(c) >= start + 3], wished)
        if note["removed"]:
            out["removed_before"] = share([c for c in cards if when(c) < start], lambda c: origin(c) == note["removed"])
            out["removed_after"] = share([c for c in cards if when(c) >= start + 1],
                                         lambda c: origin(c) == note["removed"])
    out["takes"] = [row["name"] for row in taste.taught(rt, "zh")["takes"]]
    (work / scenario).mkdir(parents=True, exist_ok=True)
    (work / scenario / f"{truth.name}.json").write_text(json.dumps({"summary": out, "cards": cards},
                                                                   ensure_ascii=False), encoding="utf-8")
    return out


def mean(rows: list, key: str) -> str:
    values = [r[key] for r in rows if r.get(key) is not None]
    return f"{sum(values) / len(values):.3f}" if values else "-"


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--people", default="zhou,ling,chen,mia")
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--scenarios", default=",".join(SCENARIOS))
    args = parser.parse_args()
    labels = json.loads((args.snapshot / "labels.json").read_text(encoding="utf-8"))
    items = {}
    for line in (args.snapshot / "items.jsonl").read_text(encoding="utf-8").splitlines():
        it = json.loads(line)
        if it["id"] in labels:
            items[it["id"]] = it
    at = sim.arrivals(list(items.values()))
    pop = sim.popularity(items, labels)
    table = {}
    for scenario in args.scenarios.split(","):
        rows = [await one(scenario, next(t for t in sim.EVERYONE if t.name == name), labels, items, at, pop,
                          args.work, args.days) for name in args.people.split(",")]
        table[scenario] = rows
        print(scenario, {k: mean(rows, k) for k in ("cards_a_day", "worth", "opened", "in_quiet", "topic_share",
                                                    "wish_during", "wish_after", "removed_before", "removed_after")},
              flush=True)
        if scenario in ("base", "remove"):
            print("   ", {r["topic"]: r["takes"] for r in rows}, [r["removed"] for r in rows], flush=True)
    (args.work / "settings.json").write_text(json.dumps(table, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
