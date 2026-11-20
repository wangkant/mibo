"""The table of a run of run.py: success per task and overall, calls, tokens, seconds and money an episode, the
cards the gate showed, the published numbers on the same tasks (published.json), and the failures by cause.

    python -I tools/bench/miniwob/report.py <out folder of run.py>

Causes: a first guess from how the episode ended, overridden by <out>/causes.json ({"task-seed": [cause, why]})
where someone read the episode. The table lands in <out>/table.md and is printed."""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from tasks import TASKS  # noqa: E402

CAUSES = ("could not see it", "could not do it", "misread the task", "ran out of steps", "the gate")


def guess(row: dict) -> tuple[str, str]:
    steps = " | ".join(row.get("steps") or [])
    status = row.get("status")
    if status in ("cap", "timeout"):
        return "ran out of steps", f"{status} after {row['calls']} calls"
    if status == "handover" and "secret field" in (row.get("result") or "") + steps:
        return "the gate", "a password field is never typed into: handed back"
    if status == "declined" or "[changed]" in steps:
        return "the gate", "a card was declined or the page changed under it"
    if status == "handover":
        return "could not do it", row.get("result", "")[:120]
    if row.get("done"):
        return "misread the task", f"the task scored {row['raw']} ({row.get('reason') or 'wrong answer'})"
    return "misread the task", f"{status}: {row.get('result', '')[:120]}"


def main(out: Path) -> str:
    rows = [json.loads(line) for line in (out / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    published = json.loads((HERE / "published.json").read_text(encoding="utf-8"))
    reviewed = json.loads((out / "causes.json").read_text(encoding="utf-8")) if (out / "causes.json").exists() else {}
    by_task = defaultdict(list)
    for row in rows:
        by_task[row["task"]].append(row)
    n = len(rows)
    lines = [f"# MiniWoB++ through Mibo's hands: {rows[0]['model']}", ""]
    ok = sum(r["success"] for r in rows)
    tasks_run = [t for t, _ in TASKS if t in by_task]
    per_task = [sum(r["success"] for r in by_task[t]) / len(by_task[t]) for t in tasks_run]
    lines += [f"- Episodes: {n} over {len(tasks_run)} tasks; success {ok}/{n} = {ok / n:.1%}; "
              f"mean of per-task rates {sum(per_task) / len(per_task):.1%}",
              f"- Per episode: model calls {sum(r['calls'] for r in rows) / n:.2f}, input tokens "
              f"{sum(r['in'] for r in rows) / n:.0f} (cached {sum(r['cached'] for r in rows) / n:.0f}), output tokens "
              f"{sum(r['out'] for r in rows) / n:.0f}, seconds {sum(r['seconds'] for r in rows) / n:.1f}, "
              f"dollars {sum(r['cost'] for r in rows) / n:.5f} (all {sum(r['cost'] for r in rows):.4f})",
              f"- Model errors (after retries): {sum(r['errors'] for r in rows)} calls; product code "
              f"{sorted({json.dumps(r.get('code'), sort_keys=True) for r in rows})}", ""]
    groups = defaultdict(list)
    for t, g in TASKS:
        groups[g] += by_task.get(t, [])
    lines += ["| group | success |", "|---|---|"]
    lines += [f"| {g} | {sum(r['success'] for r in rs)}/{len(rs)} |" for g, rs in groups.items() if rs]
    keep = ["Human", "Synapse", "RCI", "AdaPlanner", "CC-Net", "WebGUM"]
    lines += ["", "| task | Mibo | calls | in tok | s | cards | how it ended | " + " | ".join(keep) + " |",
              "|---" * (7 + len(keep)) + "|"]
    for t in tasks_run:
        rs = by_task[t]
        k = len(rs)
        pub = published["tasks"].get(t) or {}
        ends = Counter(r["status"] for r in rs)
        lines.append(f"| {t} | {sum(r['success'] for r in rs)}/{k} | {sum(r['calls'] for r in rs) / k:.1f} | "
                     f"{sum(r['in'] for r in rs) / k:.0f} | {sum(r['seconds'] for r in rs) / k:.0f} | "
                     f"{sum(len(r['cards']) for r in rs)} | {', '.join(f'{s} {c}' for s, c in ends.most_common())} | "
                     + " | ".join("-" if pub.get(c) is None else f"{pub[c]:.2f}" for c in keep) + " |")
    lines += ["", f"Published: {published['source']}"]
    for other in published["overall_other_sets"]:
        lines.append(f"Other sets: {other['what']}: {other['success']} ({other['source']})")
    cards = [(r, c) for r in rows for c in r["cards"]]
    asked = sum(1 for r in rows if r["cards"])
    lines += ["", "## The gate", "",
              f"- Cards: {len(cards)} in {asked}/{n} episodes; kinds {dict(Counter(c['kind'] for _, c in cards))}",
              f"- The button it named is on the page: {sum(c['button_on_page'] for _, c in cards)}/{len(cards)}; "
              f"the text it showed was what was typed: {sum(c['text_typed'] for _, c in cards)}/{len(cards)}",
              f"- Episodes with a card that failed: {sum(1 for r in rows if r['cards'] and not r['success'])}"]
    names = Counter(c["button"] for _, c in cards)
    lines.append(f"- Buttons on cards: {dict(names.most_common(15))}")
    failures = [r for r in rows if not r["success"]]
    sorted_failures = defaultdict(list)
    for r in failures:
        key = f"{r['task']}-{r['seed']}"
        cause, why = reviewed.get(key) or guess(r)
        sorted_failures[cause].append((key, why))
    lines += ["", f"## Failures by cause ({len(failures)}; {'read by hand' if reviewed else 'first guess only'})", ""]
    for cause in CAUSES + tuple(c for c in sorted_failures if c not in CAUSES):
        found = sorted_failures.get(cause) or []
        if not found:
            continue
        lines.append(f"- **{cause}**: {len(found)} ({', '.join(k for k, _ in found)})")
        lines.append(f"  - e.g. {found[0][0]}: {found[0][1]}")
    text = "\n".join(lines) + "\n"
    (out / "table.md").write_text(text, encoding="utf-8")
    return text


if __name__ == "__main__":
    print(main(Path(sys.argv[1])))
