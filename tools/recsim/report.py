"""The numbers from the simulated cards: the app beside random, popular and the oracle.

`measures(results, labels, items)` gives {arm: {measure: value}} and per-day rows; `judge` asks the
model whether forty of the app's sentences are true to the item and to what the app knew.
"""
from __future__ import annotations

import asyncio
import json
import random
import re
from collections import Counter
from statistics import mean

from people import PEOPLE, SUBJECTS
from people2 import FRESH

ARMS = ("app", "random", "random_read", "popular", "oracle", "rank1", "rank1_mixed", "rank1_mean", "rank1_tags", "rank1_subject",
        "rank1_clicks")
BY_NAME = {t.name: t for t in PEOPLE + FRESH}


def _avg(values) -> float | None:
    values = [v for v in values if v is not None]
    return round(mean(values), 3) if values else None


def _bigrams(text: str) -> set:
    text = re.sub(r"\s+", "", text.casefold())
    return {text[i:i + 2] for i in range(len(text) - 1)}


def _near(a: dict, b: dict, items: dict, labels: dict) -> bool:
    """Two cards on the same story: the labeller's story words or the titles mostly the same."""
    sa, sb = set(labels[a["id"]]["story"].casefold().split()), set(labels[b["id"]]["story"].casefold().split())
    if sa and sb and len(sa & sb) / len(sa | sb) >= 0.5:
        return True
    ta, tb = _bigrams(items[a["id"]]["title"]), _bigrams(items[b["id"]]["title"])
    return bool(ta and tb) and len(ta & tb) / len(ta | tb) >= 0.5


def per_person(run: dict, items: dict, labels: dict, days: int) -> dict:
    cards = run["cards"]
    truth = BY_NAME[run["person"]]
    out = {}
    n = len(cards) or 1
    out["cards_per_day"] = len(cards) / days
    out["open"] = sum(c["open"] for c in cards) / n
    out["like"] = sum(c["liked"] for c in cards) / n
    out["quick"] = sum(c["end"] == "quick" for c in cards) / n
    out["timeout"] = sum(c["end"] == "timeout" for c in cards) / n
    out["worth"] = _avg(c["worth"] for c in cards)
    out["regret"] = _avg(c["best"] - c["worth"] for c in cards)
    # The interests they had on day 0 that a card on that subject was opened for, by day 3, 10 and 30.
    start = [s for s, w in truth.interests.items() if w >= 0.4]
    for d in (3, 10, 30):
        opened = {c["subject"] for c in cards if c["open"] and c["day"] < d}
        shown = {c["subject"] for c in cards if c["day"] < d}
        # Someone with no interest that strong has none to serve.
        out[f"served_{d}"] = sum(s in opened for s in start) / len(start) if start else None
        out[f"shown_{d}"] = sum(s in shown for s in start) / len(start) if start else None
    count = Counter(c["subject"] for c in cards)
    out["top_share"] = count.most_common(1)[0][1] / n if cards else None
    ranked = sorted(start, key=lambda s: -truth.interests[s])
    out["first_interest_share"] = count[ranked[0]] / n if cards and ranked else None
    out["other_interests_share"] = sum(count[s] for s in ranked[1:]) / n if cards and ranked else None
    out["disliked_share"] = sum(count[s] for s, w in truth.interests.items() if w <= -0.4) / n
    weeks = [[c for c in cards if w * 7 <= c["day"] < w * 7 + 7] for w in range(days // 7)]
    out["subjects_week"] = _avg(len({c["subject"] for c in wk}) for wk in weeks if wk)
    out["origins_week"] = _avg(len({c["origin"] for c in wk}) for wk in weeks if wk)
    near = 0
    for i, c in enumerate(cards):
        if any(c["at"] - b["at"] < 7 * 86400 and _near(c, b, items, labels) for b in cards[:i]):
            near += 1
    out["near_repeats_per_100"] = 100 * near / n
    out["exact_repeats"] = len(cards) - len({c["id"] for c in cards})
    if truth.new:
        after = [c for c in cards if c["day"] >= 10]
        hit = next((k for k, c in enumerate(after, 1) if c["subject"] == truth.new and c["open"]), None)
        out["cards_to_new"] = hit if hit is not None else len(after) + 1
        out["new_share_10_19"] = _avg([c["subject"] == truth.new for c in after if c["day"] < 20])
        out["new_share_20_29"] = _avg([c["subject"] == truth.new for c in after if c["day"] >= 20])
        out["faded_share_0_9"] = _avg([c["subject"] == truth.fades for c in cards if c["day"] < 10])
        out["faded_share_20_29"] = _avg([c["subject"] == truth.fades for c in cards if c["day"] >= 20])
    ten = cards[:10]
    out["first10_open"] = _avg(c["open"] for c in ten)
    out["first10_worth"] = _avg(c["worth"] for c in ten)
    out["first_round_like"] = _avg(f["like"] for f in run["first"])
    out["first_round_worth"] = _avg(f["worth"] for f in run["first"])
    out["bad_moment"] = sum(c["doing"] in WORK_KINDS and not c["pause"] for c in cards) / n
    by_day = Counter(c["day"] for c in cards)
    out["silent_days"] = sum(1 for d in run["present"] if not by_day[d])
    out["video_share"] = sum(c["kind"] == "video" for c in cards) / n
    six = [c for c in cards if len(c["six"]) > 1]
    if six:
        out["six_best_vs_pool_best"] = _avg(c["best"] - max(c["six"]) for c in six)
        out["pick_vs_six_best"] = _avg(max(c["six"]) - c["worth"] for c in six)
        out["pick_vs_rank1"] = _avg(c["six"][0] - c["worth"] for c in six)
        out["picked_rank1"] = _avg(c["offered"][0] == c["id"] for c in six)
        out["line_share"] = _avg(bool(c["line"]) for c in cards)
    return out


WORK_KINDS = ("coding", "writing", "reading", "studying", "designing", "spreadsheet", "homework")


def measures(results: list[dict], items: dict, labels: dict, days: int) -> dict:
    """{arm: {measure: mean over people}}, {arm: {person: {...}}} and {arm: [per-day rows]}."""
    arms = [a for a in ARMS if any(run["arm"] == a for run in results)]
    arms += sorted({run["arm"] for run in results} - set(arms))
    people: dict = {a: {} for a in arms}
    daily: dict = {a: [] for a in arms}
    for run in results:
        people[run["arm"]][run["person"]] = per_person(run, items, labels, days)
    overall = {}
    for arm in arms:
        rows = list(people[arm].values())
        keys = {k for r in rows for k in r}
        overall[arm] = {k: _avg(r.get(k) for r in rows) for k in sorted(keys)}
        cards = [c for run in results if run["arm"] == arm for c in run["cards"]]
        for d in range(days):
            today = [c for c in cards if c["day"] == d]
            n = len(today) or 1
            daily[arm].append({"day": d, "cards": len(today), "open": round(sum(c["open"] for c in today) / n, 3),
                               "like": round(sum(c["liked"] for c in today) / n, 3),
                               "quick": round(sum(c["end"] == "quick" for c in today) / n, 3),
                               "regret": _avg(c["best"] - c["worth"] for c in today)})
    return {"overall": overall, "people": people, "daily": daily}


_JUDGE = """You check sentences a desktop companion wrote to recommend one thing to its person.
For each numbered case you get the thing (title, site, kind, summary), what the companion knew about the
person (topics they picked on the first run and what they said in the chat; nothing else), and the sentence.
Answer for each:
- "item": "true" when what the sentence says of the thing is in its title or summary; "stretch" when it
  adds details that may be so but are not given; "false" when it misstates the thing.
- "person": "none" when it claims nothing about the person; "supported" when every claim about the person
  (an interest, a habit, what they are doing) follows from what was known; "made_up" when it claims one
  that does not.
- "generic": true when the sentence would fit almost any thing (bare praise, no concrete detail).
Answer JSON only: {"cases": [{"n": 1, "item": "true", "person": "supported", "generic": false}]}"""


async def judge(results: list[dict], items: dict, model, sample: int = 40, seed: int = 3) -> dict:
    cards = [(run["person"], c) for run in results if run["arm"] == "app" for c in run["cards"] if c["line"]]
    rng = random.Random(seed)
    picked = rng.sample(cards, min(sample, len(cards)))
    verdicts = []
    for start in range(0, len(picked), 10):
        batch = picked[start:start + 10]
        text = []
        for n, (who, c) in enumerate(batch, 1):
            it = items[c["id"]]
            summary = " ".join((it.get("description") or it.get("text") or "").split())[:300]
            knew = "; ".join(c["knew"]) or "(nothing)"
            text.append(f"{n}. thing: {it['title']} | {it['site']} | {it['kind']}\nsummary: {summary}\n"
                        f"known about the person: {knew}\nsentence: {c['line']}")
        answer = await model.ask(_JUDGE, "\n\n".join(text), max_tokens=900)
        try:
            rows = {r["n"]: r for r in json.loads(answer)["cases"] if isinstance(r, dict)}
        except (ValueError, KeyError, TypeError):
            rows = {}
        for n, (who, c) in enumerate(batch, 1):
            r = rows.get(n, {})
            verdicts.append({"person": who, "id": c["id"], "line": c["line"], "item": r.get("item"),
                             "about_person": r.get("person"), "generic": r.get("generic"),
                             "truth_interests": [SUBJECTS[s][1] for s in c["interests"]], "subject": c["subject"]})
    judged = [v for v in verdicts if v["item"]]
    n = len(judged) or 1
    return {"judged": len(judged),
            "item_true": sum(v["item"] == "true" for v in judged) / n,
            "item_stretch": sum(v["item"] == "stretch" for v in judged) / n,
            "item_false": sum(v["item"] == "false" for v in judged) / n,
            "person_none": sum(v["about_person"] == "none" for v in judged) / n,
            "person_supported": sum(v["about_person"] == "supported" for v in judged) / n,
            "person_made_up": sum(v["about_person"] == "made_up" for v in judged) / n,
            "generic": sum(v["generic"] is True for v in judged) / n,
            "cases": verdicts}


ROWS = [
    ("cards_per_day", "cards a day", ""),
    ("open", "opened", "share of cards"),
    ("like", "liked", ""),
    ("quick", "closed at once (<3 s)", ""),
    ("timeout", "left to time out", ""),
    ("worth", "true worth of what was shown", "chance of an open at a calm moment, 0-1"),
    ("regret", "regret", "best worth available that moment minus shown"),
    ("served_3", "interests served by day 3", "day-0 interests with an opened card on them"),
    ("served_10", "interests served by day 10", ""),
    ("served_30", "interests served by day 30", ""),
    ("top_share", "share of cards on the most shown subject", "crowding"),
    ("first_interest_share", "share on their strongest interest", ""),
    ("other_interests_share", "share on their other interests", ""),
    ("disliked_share", "share on subjects they dislike", ""),
    ("subjects_week", "subjects in a week", "distinct"),
    ("origins_week", "sources in a week", "distinct"),
    ("near_repeats_per_100", "near-repeats per 100 cards", "same story within 7 days"),
    ("exact_repeats", "exact repeats", ""),
    ("cards_to_new", "cards after day 10 to an opened card on the new interest", "6 people with a change"),
    ("new_share_20_29", "share on the new interest, days 20-29", ""),
    ("faded_share_0_9", "share on the fading interest, days 0-9", ""),
    ("faded_share_20_29", "share on the fading interest, days 20-29", ""),
    ("first_round_like", "first run's round: liked", "10 sample finds"),
    ("first10_open", "first 10 cards: opened", ""),
    ("first10_worth", "first 10 cards: worth", ""),
    ("bad_moment", "cards at a bad moment", "in focused work, not a pause"),
    ("silent_days", "days at the computer with no card", "per person, of 30"),
    ("video_share", "share of video", ""),
]


def table(overall: dict, cold: dict) -> str:
    arms = list(overall)

    def cell(v):
        return "-" if v is None else f"{v:.3f}" if isinstance(v, float) else str(v)
    lines = [f"{'measure':58}" + "".join(f"{a:>12}" for a in arms) + "  note"]
    for key, name, note in ROWS:
        lines.append(f"{name:58}" + "".join(f"{cell(overall[a].get(key)):>12}" for a in arms) + f"  {note}")
    lines.append(f"{'cold person (no topics): first 10 cards opened':58}"
                 + "".join(f"{cell(cold[a].get('first10_open')):>12}" for a in arms))
    lines.append(f"{'cold person (no topics): first 10 cards worth':58}"
                 + "".join(f"{cell(cold[a].get('first10_worth')):>12}" for a in arms))
    app = overall.get("app", {})
    lines.append("")
    lines.append("app only: best of the six against best of the pool "
                 f"{cell(app.get('six_best_vs_pool_best'))}, the pick against the best of the six "
                 f"{cell(app.get('pick_vs_six_best'))}, against the ranking's first {cell(app.get('pick_vs_rank1'))}, "
                 f"picked the ranking's first {cell(app.get('picked_rank1'))}, cards with a sentence "
                 f"{cell(app.get('line_share'))}")
    return "\n".join(lines)


def daily_table(daily: dict) -> str:
    arms = [a for a in ("app", "random", "random_read", "popular", "oracle") if a in daily] or list(daily)
    lines = ["day  " + "".join(f"{a + ' open/like/regret':>27}" for a in arms)]
    for d in range(len(daily[arms[0]])):
        cells = []
        for a in arms:
            r = daily[a][d]
            cells.append(f"{r['open']:.2f}/{r['like']:.2f}/{(r['regret'] or 0):.2f} ({r['cards']:>3})")
        lines.append(f"{d:>3}  " + "".join(f"{c:>27}" for c in cells))
    return "\n".join(lines)


def run_judge(results, items, model):
    return asyncio.run(judge(results, items, model))
