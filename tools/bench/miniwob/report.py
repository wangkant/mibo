"""The result of a run of run.py: BrowserGym's score overall and per task, beside BrowserGym's published rows for
general models, what each episode took, the cards the gate showed, and the failures by cause.

    python -I tools/bench/miniwob/report.py <out folder of run.py> [<result .json to write>] [--seeds N]
        [--before <out folder of an earlier run>]

`--seeds N` scores only the first N of each task's seeds (a partial run states it); episodes of later seeds are
listed apart, beside the first seed's outcome on the same task, as run-to-run variance and not in the score.
`--before` sets an earlier run beside this one on the episodes both ran: the tasks won and lost between them, and
what an episode took in each.

Scores: `reward` is BrowserGym's (raw reward above 0, on the task's own address) when the app's run ended;
`reward10` the same when the tenth action on the page had been made (AgentLab's step limit); `strict` a raw
reward of 1. Causes come from <out>/causes.json ({"task-index": [cause, evidence, fault]}, read from the traces;
`fault` names the product fault, so failures that share one are counted together); a failure not in it is
listed as unread. The table lands in <out>/table.md and is printed."""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from tasks import FORTY, TASKS  # noqa: E402

CAUSES = {
    "model": "the model had what it needed and chose wrong",
    "loop": "the reply loop or its ceilings",
    "tool": "a tool's definition or result",
    "gate": "the permission gate or a card",
    "memory": "memory",
    "page": "the page or program layer",
    "bench": "the bench or adapter itself",
}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return round(centre - half, 3), round(centre + half, 3)


def beside(rows: list[dict], before: Path) -> tuple[list[str], dict]:
    """This run against an earlier one on the episodes both ran: the lines for the table and the same as data."""
    then = {(r["task"], r["index"]): r for r in map(json.loads, (before / "results.jsonl").read_text(
        encoding="utf-8").splitlines())}
    both = [(then[(r["task"], r["index"])], r) for r in rows if (r["task"], r["index"]) in then]
    won = [b["task"] for a, b in both if b["reward"] > a["reward"]]
    lost = [b["task"] for a, b in both if b["reward"] < a["reward"]]
    each = {}
    for side, pick in (("before", 0), ("after", 1)):
        picked = [pair[pick] for pair in both]
        each[side] = {"reward": int(sum(r["reward"] for r in picked)), "reward10": int(sum(r["reward10"] for r in picked)),
                      **{k: round(sum(r[k] for r in picked) / len(picked), 5) for k in ("calls", "moves", "in", "cost",
                                                                                          "seconds")}}
    n = len(both)
    lines = ["", f"## Beside {before.name} ({n} episodes both ran)", "",
             "| | reward | reward10 | calls | page actions | input tokens | dollars | seconds |", "|---|---|---|---|---|---|---|---|"]
    lines += [f"| {side} | {v['reward']}/{n} | {v['reward10']}/{n} | {v['calls']:.2f} | {v['moves']:.1f} | {v['in']:.0f} | "
              f"{v['cost']:.5f} | {v['seconds']:.1f} |" for side, v in each.items()]
    lines += ["", f"- won ({len(won)}): {', '.join(won)}", f"- lost ({len(lost)}): {', '.join(lost)}"]
    return lines, {"episodes": n, **each, "won": won, "lost": lost}


def main(out: Path, save: Path | None = None, seeds: int = 5, before: Path | None = None) -> str:
    every = [json.loads(line) for line in (out / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    rows = [r for r in every if r["index"] < seeds]
    first = {r["task"]: r for r in every if r["index"] == 0}
    later = [r for r in every if r["index"] >= seeds]
    runs = json.loads((out / "run.json").read_text(encoding="utf-8"))
    published = json.loads((HERE / "published.json").read_text(encoding="utf-8"))
    read = json.loads((out / "causes.json").read_text(encoding="utf-8")) if (out / "causes.json").exists() else {}
    by_task = defaultdict(list)
    for row in rows:
        by_task[row["task"]].append(row)
    n = len(rows)
    category = {t: c for t, c, _, _ in TASKS}
    names = [t for t, _, _, _ in TASKS if t in by_task]
    total = {k: sum(r[k] for r in rows) for k in ("reward", "reward10")}
    total["strict"] = sum(float(r["raw"] or 0) >= 1 for r in rows)
    lines = [f"# MiniWoB++ (BrowserGym's 125) through Mibo's hands: {rows[0]['model']}", ""]
    for key, what in (("reward10", "at AgentLab's 10 steps"), ("reward", "at the app's own ceiling"),
                      ("strict", "raw reward 1 (stricter than BrowserGym)")):
        lo, hi = wilson(int(total[key]), n)
        lines.append(f"- {what}: {int(total[key])}/{n} = {total[key] / n:.1%} (95% {lo:.1%}-{hi:.1%})")
    lines += [f"- Episodes {n} over {len(names)} tasks; per episode: model calls {sum(r['calls'] for r in rows) / n:.2f}, "
              f"actions on the page {sum(r['moves'] for r in rows) / n:.1f}, input tokens {sum(r['in'] for r in rows) / n:.0f} "
              f"(cached {sum(r['cached'] for r in rows) / n:.0f}), output {sum(r['out'] for r in rows) / n:.0f}, "
              f"seconds {sum(r['seconds'] for r in rows) / n:.1f}, dollars {sum(r['cost'] for r in rows) / n:.5f} "
              f"(all {sum(r['cost'] for r in rows):.4f})",
              f"- Model errors after retries: {sum(r['errors'] for r in rows)} calls; providers "
              f"{dict(Counter(p for r in rows for p in r.get('providers') or []))}", ""]
    bg = published["overall_other_sets"][0]
    lines += ["| BrowserGym GenericAgent (" + bg["source"] + ") | success |", "|---|---|"]
    lines += [f"| {k} | {v:.1%} |" for k, v in bg["success"].items()]
    groups = defaultdict(list)
    for t in names:
        groups[category[t]] += by_task[t]
    lines += ["", "| category | reward10 | reward |", "|---|---|---|"]
    lines += [f"| {g} | {sum(r['reward10'] for r in rs):.0f}/{len(rs)} | {sum(r['reward'] for r in rs):.0f}/{len(rs)} |"
              for g, rs in groups.items()]
    forty = [r for t in FORTY for r in by_task.get(t, [])]
    if forty:
        lines.append(f"\nThe forty picked before (regression check): {sum(r['reward'] for r in forty):.0f}/{len(forty)}")
    lines += ["", "| task | reward10 | reward | calls | s | how it ended |", "|---|---|---|---|---|---|"]
    for t in names:
        rs = by_task[t]
        k = len(rs)
        ends = Counter(r["status"] for r in rs)
        lines.append(f"| {t} | {sum(r['reward10'] for r in rs):.0f}/{k} | {sum(r['reward'] for r in rs):.0f}/{k} | "
                     f"{sum(r['calls'] for r in rs) / k:.1f} | {sum(r['seconds'] for r in rs) / k:.0f} | "
                     f"{', '.join(f'{s} {c}' for s, c in ends.most_common())} |")
    cards = [c for r in rows for c in r["cards"]]
    lines += ["", f"Cards: {len(cards)} in {sum(1 for r in rows if r['cards'])}/{n} episodes; buttons "
              f"{dict(Counter(c.get('button') or c.get('place') for c in cards).most_common(10))}"]
    failures = [r for r in rows if not r["reward"]]
    tagged = defaultdict(list)
    for r in failures:
        key = f"{r['task']}-{r['index']}"
        cause, evidence = (read.get(key) or ["unread", r["status"]])[:2]
        tagged[cause].append((key, evidence))
    faults = Counter((read.get(f"{r['task']}-{r['index']}") or ["", "", "unread"])[2] for r in failures)
    lines += ["", f"## Failures by cause ({len(failures)})", ""]
    for cause, found in sorted(tagged.items(), key=lambda kv: -len(kv[1])):
        lines.append(f"- **{CAUSES.get(cause, cause)}**: {len(found)}")
    lines += ["", "By product fault: " + ", ".join(f"{f} {c}" for f, c in faults.most_common())]
    compared: dict = {}
    if before:
        more, compared = beside(rows, before)
        lines += more
    flips = [r["task"] for r in later if r["reward"] != first[r["task"]]["reward"]]
    if later:
        lines += ["", f"## Later seeds, not in the score ({len(later)} episodes over "
                      f"{len({r['task'] for r in later})} tasks)", "",
                  f"- these seeds: {sum(r['reward'] for r in later):.0f}/{len(later)}; the first seed on the same "
                  f"tasks: {sum(first[r['task']]['reward'] for r in later):.0f}/{len(later)}; outcome differs on "
                  f"{len(flips)}: {', '.join(flips)}"]
    text = "\n".join(lines) + "\n"
    (out / "table.md").write_text(text, encoding="utf-8")
    if save:
        result = {
            "benchmark": "MiniWoB++ as BrowserGym defines it: 125 tasks, AgentLab's 5 seeds each",
            "scored": f"the first {seeds} of the 5 seeds a task: {n} of the protocol's {5 * len(TASKS)} episodes",
            "system": "Mibo's reply loop, one chat turn in a private chat beside the page in the app's browser (look and "
                      "act, mibo/surface.py; Hands, pageops and gate.py), the browser a headless Edge stand-in pane",
            "runs": runs, "episodes": n, "tasks": len(names),
            "score": {k: {"success": int(v), "rate": round(v / n, 4), "wilson95": wilson(int(v), n)}
                      for k, v in total.items()},
            "per_episode": {k: round(sum(r[k] for r in rows) / n, 2) for k in ("calls", "moves", "in", "cached",
                                                                                "out", "seconds")},
            "dollars": round(sum(r["cost"] for r in rows), 5),
            "published": bg,
            "categories": {g: {"episodes": len(rs), "reward10": sum(r["reward10"] for r in rs),
                               "reward": sum(r["reward"] for r in rs)} for g, rs in groups.items()},
            "per_task": {t: {"category": category[t],
                             "outcomes": [{"index": r["index"], "seed": r["seed"], "reward10": r["reward10"],
                                           "reward": r["reward"], "raw": r["raw"], "status": r["status"],
                                           "calls": r["calls"], "moves": r["moves"], "seconds": r["seconds"],
                                           "cost": r["cost"],
                                           **(dict(zip(("cause", "evidence", "fault"),
                                                       read.get(f"{t}-{r['index']}", ["unread", "", ""])))
                                              if not r["reward"] else {})}
                                          for r in sorted(by_task[t], key=lambda r: r["index"])]}
                         for t in names},
            "failures_by_cause": {c: {"what": CAUSES.get(c, c), "count": len(f), "episodes": [k for k, _ in f]}
                                  for c, f in sorted(tagged.items(), key=lambda kv: -len(kv[1]))},
            "failures_by_fault": dict(faults.most_common()),
            "beside_before": compared,
            "cards": {"count": len(cards), "episodes": sum(1 for r in rows if r["cards"])},
            "later_seeds": {"episodes": len(later), "reward": sum(r["reward"] for r in later),
                            "first_seed_on_same_tasks": sum(first[r["task"]]["reward"] for r in later),
                            "differs": flips,
                            "outcomes": [{"task": r["task"], "index": r["index"], "seed": r["seed"],
                                          "reward": r["reward"], "first_seed_reward": first[r["task"]]["reward"],
                                          "status": r["status"], "calls": r["calls"], "seconds": r["seconds"]}
                                         for r in later]},
        }
        save.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return text


if __name__ == "__main__":
    cli = argparse.ArgumentParser()
    cli.add_argument("out", type=Path)
    cli.add_argument("save", type=Path, nargs="?")
    cli.add_argument("--seeds", type=int, default=5)
    cli.add_argument("--before", type=Path)
    a = cli.parse_args()
    print(main(a.out, a.save, a.seeds, a.before))
