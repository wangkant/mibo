"""The taste model replayed over the person's own reactions, day by day, against the old point sum.

    python -m mibo.taste_replay replay [--runtime DIR]
"""
from __future__ import annotations

import argparse
import json
import math
import random
from datetime import datetime
from pathlib import Path

from . import taste


def auc(pairs: list[tuple[float, int]]) -> float | None:
    """The chance a random positive outscores a random negative, ties counted half."""
    pos = sum(y for _, y in pairs)
    neg = len(pairs) - pos
    if not pos or not neg:
        return None
    ordered = sorted(pairs, key=lambda p: p[0])
    rank_sum, n = 0.0, 0
    while n < len(ordered):
        end = n
        while end < len(ordered) and ordered[end][0] == ordered[n][0]:
            end += 1
        rank_sum += (n + end + 1) / 2 * sum(y for _, y in ordered[n:end])
        n = end
    return (rank_sum - pos * (pos + 1) / 2) / (pos * neg)


def _logloss(p: float, y: int) -> float:
    p = min(1 - 1e-6, max(1e-6, p))
    return -math.log(p if y else 1 - p)


def _metrics(days: list[list[dict]], name: str) -> dict:
    flat = [row for day in days for row in day]
    top = [row["y"] for day in days for row in sorted(day, key=lambda r: -r[name + "_s"])[:5]]
    return {"auc": auc([(row[name + "_s"], row["y"]) for row in flat]),
            "logloss": sum(_logloss(row[name + "_p"], row["y"]) for row in flat) / len(flat) if flat else None,
            "top5": sum(top) / len(top) if top else None}


def _ci(values: list[float]) -> list[float | None]:
    values = sorted(v for v in values if v is not None)
    if not values:
        return [None, None]
    return [round(values[int(0.025 * (len(values) - 1))], 4), round(values[int(0.975 * (len(values) - 1))], 4)]


def _day_start(at: float) -> float:
    return datetime.combine(datetime.fromtimestamp(at).date(), datetime.min.time()).timestamp()


def replay(runtime: Path, resamples: int = 1000, seed: int = 0, families: tuple = ("tags",)) -> dict:
    """Prequential replay over the person's own reactions in time order: each day is predicted by models fit
    only on what was known when it began: the old point sum against this model's posterior mean, and this
    model with each family still waiting on the replay. AUC (opened, played or liked against skipped or
    hidden), log loss (each score calibrated on the days before) and the top-5 positive rate, each with a
    day-block bootstrap 95% CI."""
    runtime = Path(runtime)
    feed = taste._feed()
    events = sorted(feed.events(runtime), key=lambda e: e[0])
    reader = taste.Reader(runtime)
    rebuild = taste._Rebuild(runtime, reader)
    read = taste.readable(runtime)
    by_source = {}
    for ident, h in taste.history(events).items():
        snap = h["f"] or rebuild(ident, h["at"])
        if snap and snap["origin"].startswith("src:"):
            by_source[ident] = snap["origin"][4:]
    starts = sorted({_day_start(e[0]) for e in events})
    days: list[list[dict]] = []
    calibration: dict[str, list] = {}
    warm: dict[str, dict] = {"model": {}, "tags": {}}
    lost_ids: set[str] = set()
    for start in starts:
        end = start + taste.DAY
        test = []
        for ident, h in taste.history(events, end).items():
            y = taste.reacted(h)
            if y is None or not start <= h["acted"] < end:
                continue
            snap = h["f"] or rebuild(ident, h["at"])
            if snap is None:
                lost_ids.add(ident)
                continue
            test.append((ident, h, snap, y))
        if not test:
            continue
        # What the person had hidden when the day began; the profile's rules are left out (see Priors).
        prior = taste.Priors(runtime, {by_source[e[1]] for e in events
                                       if e[2] == "hide_source" and e[0] < start and e[1] in by_source}, rules=False)
        fits = {}
        for name, fam in (("model", ()), ("tags", ("tags",))):
            if name != "model" and name not in families:
                continue
            data, _ = taste.rows(events, start, read, rebuild, fam)
            fits[name] = taste.solve(data, prior, warm[name])[0]
            warm[name] = fits[name]
        # The old point sum, as feed.score had it when the day began.
        then = feed._marks(events, start)[0]
        old_taste = feed._taste(then)
        acted = sum(1 for mark in then.values() if mark["open"] or mark["like"] or mark["skip"])
        topical = feed.TOPIC * 0.5 ** (acted / feed.TOPIC_HALF)
        learned = feed._by_source(then, by_source)
        # Each score becomes a probability the same way, by a logistic fit on the days before's reacted
        # things: the old sum has no scale, and the model is fit on quiet noes the test leaves out.
        platt = {name: taste.solve(rows_, lambda k: (0.0, 1.0))[0] if rows_ else {} for name, rows_ in calibration.items()}
        day = []
        for ident, h, snap, y in test:
            days_old = math.log(max(snap["fresh"], 1e-9)) / math.log(0.5)
            row = {"y": y, "old_s": feed.score({"site": snap["site"], "kind": snap["kind"]},
                                               int(h["at"] - days_old * taste.DAY), snap["fits"], old_taste, h["at"],
                                               topical if snap["topics"] else 0,
                                               feed.source_points(learned.get(by_source.get(ident))))}
            for name, w in fits.items():
                x = taste.vector(snap, read, ("tags",) if name == "tags" else ())
                row[name + "_s"] = sum(w.get(k, prior(k)[0]) * v for k, v in x.items())
            for name in ("old", *fits):
                a = platt.get(name, {})
                row[name + "_p"] = taste._sigmoid(a.get("bias", 0.0) + a.get("s", 0.0) * row[name + "_s"])
                calibration.setdefault(name, []).append(({"bias": 1.0, "s": row[name + "_s"]}, y, 1.0))
            day.append(row)
        days.append(day)
    return _report(days, ["old", "model"] + [f for f in families if f in warm], len(lost_ids), resamples, seed)


def _report(days: list[list[dict]], names: list[str], lost: int, resamples: int, seed: int) -> dict:
    """Each score's metrics over the replayed `days` with a day-block bootstrap 95% CI, each against the one
    it builds on, and the ship rule."""
    point = {name: _metrics(days, name) for name in names}
    boot = {name: {"auc": [], "logloss": [], "top5": []} for name in names}
    delta = {name: {"auc": [], "logloss": []} for name in names if name != "old"}
    rng = random.Random(seed)
    for _ in range(resamples if days else 0):
        sample = [days[rng.randrange(len(days))] for _ in days]
        got = {name: _metrics(sample, name) for name in names}
        for name in names:
            for k in ("auc", "logloss", "top5"):
                boot[name][k].append(got[name][k])
        for name, base in (("model", "old"), *((f, "model") for f in names[2:])):
            if got[name]["auc"] is not None and got[base]["auc"] is not None:
                delta[name]["auc"].append(got[name]["auc"] - got[base]["auc"])
            delta[name]["logloss"].append(got[name]["logloss"] - got[base]["logloss"])
    n = sum(len(day) for day in days)
    report = {"reacted": n, "days": len(days), "lost": lost,
              "scores": {name: {k: {"value": None if v is None else round(v, 4), "ci": _ci(boot[name][k])}
                                for k, v in point[name].items()} for name in names},
              "delta": {name: {k: _ci(v) for k, v in d.items()} for name, d in delta.items()}}
    low = report["delta"]["model"]["auc"][0] if n else None
    worse = (point["model"]["logloss"] or 0) > (point["old"]["logloss"] or 0)
    report["ship"] = {"enough": n >= 100, "auc_noninferior": low is not None and low > -0.02,
                      "logloss_no_worse": bool(n) and not worse}
    report["ship"]["passes"] = all(report["ship"].values())
    for name in names[2:]:
        d = report["delta"][name]
        lowers = (point[name]["logloss"] or 0) < (point["model"]["logloss"] or 0)
        report.setdefault("families", {})[name] = (
            "helps" if lowers and d["auc"][1] is not None and d["auc"][1] >= 0 else "no split")
    report.setdefault("families", {}).update({"sim": "not built", "ctx": "not built"})
    return report


def _print(report: dict) -> None:
    print(f"reacted things: {report['reacted']} over {report['days']} days; "
          f"{report['lost']} could not be rebuilt (old events whose things are gone)")
    print(f"{'':8}{'AUC':>24}{'log loss':>26}{'top-5 positive':>26}")
    for name, got in report["scores"].items():
        cells = [f"{got[k]['value']} [{got[k]['ci'][0]}, {got[k]['ci'][1]}]" for k in ("auc", "logloss", "top5")]
        print(f"{name:8}" + "".join(f"{c:>26}" for c in cells))
    for name, d in report["delta"].items():
        print(f"delta {name}: AUC {d['auc']}, log loss {d['logloss']}")
    ship = report["ship"]
    print(f"ship rule: >=100 reacted {ship['enough']}, AUC CI low > -0.02 {ship['auc_noninferior']}, "
          f"log loss no worse {ship['logloss_no_worse']} -> {'passes' if ship['passes'] else 'does not pass'}")
    print("families: " + ", ".join(f"{k} {v}" for k, v in report["families"].items()))


def main(argv: list[str] | None = None) -> None:
    from .paths import runtime_dir
    parser = argparse.ArgumentParser(prog="python -m mibo.taste_replay")
    parser.add_argument("command", choices=["replay"])
    parser.add_argument("--runtime", type=Path, default=None, help="the runtime folder (default: this home's)")
    parser.add_argument("--resamples", type=int, default=1000)
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)
    report = replay(args.runtime or runtime_dir(), args.resamples)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        _print(report)


if __name__ == "__main__":
    main()
