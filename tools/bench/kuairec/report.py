"""The numbers from a KuaiRec replay: what each arm showed over the first 10, 30, 100 and 300 cards.

Beside the watched-through share stands "stand": where each shown video's watch ratio stands among
that person's own for videos of about that length (0 to 1, 0.5 for random picks). A short video is
watched through more easily, so bringing short ones raises the watched-through share without knowing
the person; the standing does not move with that (the idea of Kuaishou's D2Q, KDD 2022).

    python -I tools/bench/kuairec/report.py --data <prepared> --out <dir> [--json]

Reads <out>/cards/<arm>/*.json from replay.py and prints the tables; --json also writes
<out>/report.json. Every mean is over people (each person's own mean first), with a 95% bootstrap
interval over people. Variants ran on fewer people are compared with the app on those same people.
"""
from __future__ import annotations

import argparse
import json
import math
import random
from collections import Counter, defaultdict
from pathlib import Path

KS = (10, 30, 100, 300)
BASE = ("random", "popular", "bandit", "oracle")
# References for what a category-only model could reach.
CEIL = ("cat_oracle", "cat_oracle_alt")
ORDER = ("app", "app_pop", "app_greedy", "app_explore", "app_site", "app_author", "app_topics", "app_tags",
         "app_open05", "random", "popular", "bandit", "cat_oracle", "cat_oracle_alt", "oracle")


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def ci(values, reps=1000, seed=0):
    rng = random.Random(seed)
    values = list(values)
    if not values:
        return [float("nan")] * 2
    got = sorted(mean(rng.choice(values) for _ in values) for _ in range(reps))
    return [got[int(0.025 * reps)], got[int(0.975 * reps) - 1]]


def entropy(counts):
    n = sum(counts.values())
    return -sum(c / n * math.log2(c / n) for c in counts.values() if c)


def auc(scores, ys):
    pairs = sorted(zip(scores, ys))
    pos = sum(ys)
    neg = len(ys) - pos
    if not pos or not neg:
        return None
    rank_sum, n = 0.0, 0
    while n < len(pairs):
        end = n
        while end < len(pairs) and pairs[end][0] == pairs[n][0]:
            end += 1
        rank_sum += (n + end + 1) / 2 * sum(y for _, y in pairs[n:end])
        n = end
    return (rank_sum - pos * (pos + 1) / 2) / (pos * neg)


def load(out: Path) -> dict:
    arms = {}
    for d in sorted((out / "cards").iterdir()):
        runs = {}
        for f in d.glob("*.json"):
            got = json.loads(f.read_text(encoding="utf-8"))
            runs[got["uid"]] = got
        arms[d.name] = runs
    return arms


def standing(data: Path) -> dict:
    """{uid: {vid: q}}: where each watch ratio stands among that person's own for the library videos in
    the same tenth by length, ties counted half."""
    videos = json.loads((data / "videos.json").read_text(encoding="utf-8"))
    library = json.loads((data / "library.json").read_text(encoding="utf-8"))
    by_length = sorted(library, key=lambda v: videos[v]["dur_s"])
    band = {vid: n * 10 // len(by_length) for n, vid in enumerate(by_length)}
    out = {}
    for uid, seen in json.loads((data / "reactions.json").read_text(encoding="utf-8")).items():
        bands = defaultdict(list)
        for vid, (wr, _) in seen.items():
            if vid in band:
                bands[band[vid]].append(wr)
        out[uid] = {vid: (sum(w < wr for w in bands[band[vid]]) + 0.5 * sum(w == wr for w in bands[band[vid]]))
                    / len(bands[band[vid]]) for vid, (wr, _) in seen.items() if vid in band}
    return out


_standing: dict = {}


def per_person(run: dict, k: int) -> dict:
    cards = run["cards"][:k]
    wr = [c[1] for c in cards]
    stand = _standing.get(run["uid"])
    return {"wr": mean(wr), "through": mean(c[1] >= 1 for c in cards), "cats": len({c[3] for c in cards}),
            "entropy": entropy(Counter(c[3] for c in cards)), "n": len(cards),
            "stand": mean(stand[c[0]] for c in cards) if stand else 0.0}


def table(arms: dict, uids: list, names: list) -> dict:
    rows = {}
    for name in names:
        runs = arms.get(name, {})
        have = [u for u in uids if u in runs]
        if not have:
            continue
        rows[name] = {"people": len(have)}
        for k in KS:
            pp = [per_person(runs[u], k) for u in have]
            rows[name][k] = {m: mean(p[m] for p in pp) for m in ("wr", "through", "cats", "entropy", "stand")}
            rows[name][k]["through_ci"] = ci([p["through"] for p in pp])
            rows[name][k]["wr_ci"] = ci([p["wr"] for p in pp])
    return rows


def curve(runs: dict, uids: list, n: int = 300) -> list:
    """Mean watched-through share at each card position over people."""
    out = []
    for t in range(n):
        vals = [runs[u]["cards"][t][1] >= 1 for u in uids if u in runs and len(runs[u]["cards"]) > t]
        out.append(mean(vals))
    return out


def beats(a: list, b: list, window: int = 20):
    """The first card from which a's running mean over the cards so far stays at or above b's, and the
    first window of `window` cards where a's mean is above b's."""
    ca = cb = 0.0
    first_stay = None
    for t in range(len(a)):
        ca += a[t]
        cb += b[t]
        if ca >= cb:
            first_stay = first_stay or t + 1
        else:
            first_stay = None
    first_window = next((t + window for t in range(0, len(a) - window + 1, window)
                         if mean(a[t:t + window]) > mean(b[t:t + window])), None)
    return first_stay, first_window


def fmt_row(name, row):
    cells = [f"{name:12}", f"{row['people']:>4}"]
    for k in KS:
        r = row[k]
        cells.append(f"{r['wr']:.3f} {r['through']:.3f} {r['cats']:4.1f} {r['stand']:.3f}")
    return "  ".join(cells)


def print_table(title, rows):
    print(f"\n{title}")
    print(f"{'arm':12}  {'n':>4}  " + "  ".join(f"{'first ' + str(k) + ': wr thru cats stand':>28}" for k in KS))
    for name in ORDER:
        if name in rows:
            print(fmt_row(name, rows[name]))


def gaps(rows: dict) -> dict:
    """Per arm and k: the gap to the oracle and the share of the random-to-oracle distance covered."""
    out = {}
    for name, row in rows.items():
        out[name] = {}
        for k in KS:
            o, r, a = rows["oracle"][k], rows["random"][k], row[k]
            out[name][k] = {"wr_gap": o["wr"] - a["wr"], "through_gap": o["through"] - a["through"],
                            "share_of_possible": (a["through"] - r["through"]) / (o["through"] - r["through"])}
    return out


def diagnostics(arms: dict, data: Path) -> dict:
    """What the app learned from, and from what it did not."""
    videos = json.loads((data / "videos.json").read_text(encoding="utf-8"))
    reactions = json.loads((data / "reactions.json").read_text(encoding="utf-8"))
    popularity = json.loads((data / "popularity.json").read_text(encoding="utf-8"))
    library = json.loads((data / "library.json").read_text(encoding="utf-8"))
    app = arms["app"]
    d = {}
    cards = [c for run in app.values() for c in run["cards"]]
    d["events"] = dict(Counter(c[4] for c in cards))
    opened = [c for c in cards if c[4] == "open"]
    d["opened_played_60s_share"] = mean(c[2] >= 60 for c in opened)
    d["library_duration_over_240s_share"] = mean(videos[v]["dur_s"] >= 240 for v in library)
    d["library_without_caption_share"] = mean(not videos[v]["caption"] for v in library)
    d["slots"] = {s: {"cards": n, "through": mean(c[1] >= 1 for c in cards if c[5] == s)}
                  for s, n in Counter(c[5] for c in cards).items()}
    d["reasons"] = dict(Counter(c[6] for c in cards))

    # After a card of category c ended one way, the share of the next 10 cards on c, against c's share of
    # what the person still had to see.
    after, moved = defaultdict(list), defaultdict(list)
    for uid, run in app.items():
        cs = run["cards"]
        pool = Counter(videos[v]["c1"] for v in library if v in reactions[uid])
        shown = Counter()
        for t, c in enumerate(cs[:-10]):
            shown[c[3]] += 1
            nxt = cs[t + 1:t + 11]
            left = sum(pool.values()) - (t + 1)
            base = (pool[c[3]] - shown[c[3]]) / left if left else 0
            after[c[4]].append(mean(x[3] == c[3] for x in nxt) - base)
            if t >= 10:
                # The same category's share of the 10 cards after against the 10 before.
                moved[c[4]].append(mean(x[3] == c[3] for x in nxt) - mean(x[3] == c[3] for x in cs[t - 10:t]))
    d["same_category_next10_minus_base"] = {e: {"n": len(v), "mean": mean(v)} for e, v in after.items()}
    d["same_category_next10_minus_previous10"] = {e: {"n": len(v), "mean": mean(v), "ci": ci(v)}
                                                  for e, v in moved.items()}

    # Which signals a person's watched-through carries, in the data itself: per person, the AUC of
    # watched-through on the library by (a) their own category rate, leave-one-out, (b) the crowd's
    # popularity, (c) their own uploader rate, leave-one-out, (d) shortness.
    sig = defaultdict(list)
    learned_vs_true = []
    for uid in app:
        r = reactions[uid]
        vids = [v for v in library if v in r]
        ys = [int(r[v][0] >= 1) for v in vids]
        for key, field in (("category", "c1"), ("uploader", "author")):
            tot = defaultdict(lambda: [0, 0])
            for v, y in zip(vids, ys):
                tot[videos[v][field]][0] += 1
                tot[videos[v][field]][1] += y
            p = mean(ys)
            score = [((tot[videos[v][field]][1] - y) + p) / (tot[videos[v][field]][0] - 1 + 1) for v, y in zip(vids, ys)]
            sig[key].append(auc(score, ys))
        sig["popularity"].append(auc([popularity.get(v, {"mean_wr": 0})["mean_wr"] for v in vids], ys))
        sig["shortness"].append(auc([-videos[v]["dur_s"] for v in vids], ys))
        # The app's learned origin weights against the person's true category rates.
        model = app[uid].get("model", {})
        rates = {}
        for v, y in zip(vids, ys):
            rates.setdefault(videos[v]["c1"] or "其他", []).append(y)
        pairs = [(w, mean(rates[k[len("origin:src:ks-"):]])) for k, w in model.items()
                 if k.startswith("origin:src:ks-") and k[len("origin:src:ks-"):] in rates]
        if len(pairs) >= 5:
            learned_vs_true.append(spearman(*zip(*pairs)))
    d["signal_auc"] = {k: {"mean": mean(x for x in v if x is not None), "ci": ci([x for x in v if x is not None])}
                       for k, v in sig.items()}
    d["learned_origin_vs_true_category_spearman"] = {"people": len(learned_vs_true), "mean": mean(learned_vs_true)}
    return d


def spearman(a, b):
    def ranks(x):
        order = sorted(range(len(x)), key=lambda i: x[i])
        r = [0.0] * len(x)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and x[order[j + 1]] == x[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2
            i = j + 1
        return r
    ra, rb = ranks(a), ranks(b)
    ma, mb = mean(ra), mean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
    return num / den if den else 0.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    people = {p["uid"]: p for p in json.loads((args.data / "people.json").read_text(encoding="utf-8"))}
    arms = load(args.out)
    _standing.update(standing(args.data))
    everyone = [u for u in people if u in arms.get("app", {})]
    report = {"main": table(arms, everyone, ["app", *BASE, *CEIL])}
    print_table("All sampled people (app and baselines): mean watch ratio, watched-through share, "
                "distinct categories", report["main"])
    report["main_gaps"] = gaps(report["main"])
    print("\nShare of the random-to-oracle distance in watched-through covered (app / popular / bandit):")
    for k in KS:
        g = report["main_gaps"]
        print(f"  first {k:>3}: app {g['app'][k]['share_of_possible']:+.3f}  popular "
              f"{g['popular'][k]['share_of_possible']:+.3f}  bandit {g['bandit'][k]['share_of_possible']:+.3f}"
              f"   gap to oracle in watch ratio: app {g['app'][k]['wr_gap']:.3f}")
    curves = {name: curve(arms[name], everyone) for name in ("app", *BASE) if name in arms}
    report["beats"] = {}
    for other in ("popular", "random", "bandit"):
        stay, window = beats(curves["app"], curves[other])
        report["beats"][other] = {"running_mean_stays_ahead_from": stay, "first_20_card_window_ahead": window}
        print(f"app vs {other}: running mean ahead from card {stay}; first 20-card window ahead ends at {window}")
    report["blocks"] = {name: {f"{a + 1}-{b}": mean(c[a:b]) for a, b in ((0, 10), (10, 30), (30, 100), (100, 300))}
                        for name, c in curves.items()}
    print("watched-through by block of cards: " + json.dumps({n: {k: round(v, 3) for k, v in b.items()}
                                                            for n, b in report["blocks"].items()}))
    for label, test in (("narrow tastes (top fifth by how much category explains)", lambda p: p["narrow_q"] == 4),
                        ("people who like little (bottom fifth by watched-through share)", lambda p: p["through_q"] == 0),
                        ("people who like a lot (top fifth by watched-through share)", lambda p: p["through_q"] == 4)):
        uids = [u for u in everyone if test(people[u])]
        key = label.split(" (")[0]
        report.setdefault("segments", {})[key] = table(arms, uids, ["app", *BASE, *CEIL])
        print_table(label, report["segments"][key])
    variants = [n for n in ORDER if n.startswith("app_") and n in arms]
    if variants:
        uids = [u for u in everyone if all(u in arms[v] for v in variants)]
        report["variants"] = table(arms, uids, ["app", *variants, *BASE])
        print_table("Variants, on the people they all ran on", report["variants"])
        diffs = {}
        for v in variants:
            d = [per_person(arms[v][u], 300)["through"] - per_person(arms["app"][u], 300)["through"] for u in uids]
            d100 = [per_person(arms[v][u], 100)["through"] - per_person(arms["app"][u], 100)["through"] for u in uids]
            diffs[v] = {"through_300_minus_app": mean(d), "ci": ci(d), "through_100_minus_app": mean(d100),
                        "ci100": ci(d100)}
            print(f"  {v:12} watched-through minus app, paired: first 100 {mean(d100):+.3f} "
                  f"[{ci(d100)[0]:+.3f}, {ci(d100)[1]:+.3f}]  first 300 {mean(d):+.3f} [{ci(d)[0]:+.3f}, {ci(d)[1]:+.3f}]")
        report["variant_diffs"] = diffs
    report["diagnostics"] = diagnostics(arms, args.data)
    print("\nDiagnostics:\n" + json.dumps(report["diagnostics"], ensure_ascii=False, indent=1))
    if args.json:
        (args.out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    main()
