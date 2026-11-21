"""The table of a run of run.py: the judge's success overall and per site, how runs ended, calls, tokens, seconds and
money a task, the cards the gate raised, and, where a person read a task (<out>/hand.json, {"id": [true|false,
"why"]}), the judge beside them.

    python -I tools/bench/webvoyager/report.py <out folder of run.py>

The table lands in <out>/table.md and is printed."""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


def main(out: Path) -> str:
    rows = [json.loads(line) for line in (out / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    hand = json.loads((out / "hand.json").read_text(encoding="utf-8")) if (out / "hand.json").exists() else {}
    n = len(rows)
    ok = sum(r["success"] for r in rows)
    spent = sum(r["cost"] + r["judge_cost"] for r in rows)
    lines = [f"# WebVoyager subset through Mibo's hands: {rows[0]['model']}", "",
             f"- Tasks: {n}; the judge's success {ok}/{n} = {ok / n:.0%}",
             f"- Per task: model calls {sum(r['calls'] for r in rows) / n:.1f}, input tokens "
             f"{sum(r['in'] for r in rows) / n:.0f} (cached {sum(r['cached'] for r in rows) / n:.0f}), output tokens "
             f"{sum(r['out'] for r in rows) / n:.0f}, seconds {sum(r['seconds'] for r in rows) / n:.1f} (median "
             f"{sorted(r['seconds'] for r in rows)[n // 2]:.1f}), dollars {sum(r['cost'] for r in rows) / n:.4f} "
             f"and {sum(r['judge_cost'] for r in rows) / n:.4f} for the judge (all {spent:.4f})",
             f"- How runs ended: {dict(Counter(r['status'] for r in rows).most_common())}; done borne out by "
             f"{dict(Counter(r['proof'] or '-' for r in rows if r['status'] == 'done').most_common())}",
             f"- Cards: {sum(len(r['cards']) for r in rows)} in {sum(1 for r in rows if r['cards'])} tasks "
             f"{[c['kind'] + ' ' + c['button'][:30] for r in rows for c in r['cards']]}",
             f"- Model errors (after retries): {sum(r['errors'] for r in rows)} calls; product code "
             f"{sorted({json.dumps(r.get('code'), sort_keys=True) for r in rows})}", "",
             "| site | tasks | judge says done |", "|---|---|---|"]
    by_site = defaultdict(list)
    for r in rows:
        by_site[r["site"]].append(r)
    lines += [f"| {site} | {len(rs)} | {sum(r['success'] for r in rs)} |" for site, rs in by_site.items()]
    if hand:
        read = [r for r in rows if r["id"] in hand]
        agree = [r for r in read if bool(hand[r["id"]][0]) == r["success"]]
        mine = sum(bool(hand[r["id"]][0]) for r in read)
        lines += ["", f"## The judge beside a person's reading ({len(read)} tasks read)", "",
                  f"- Agree on {len(agree)}/{len(read)}; the person counts {mine}/{len(read)} done, the judge "
                  f"{sum(r['success'] for r in read)}/{len(read)}", "",
                  "| task | ended | judge | person | why (person) |", "|---|---|---|---|---|"]
        lines += [f"| {r['id']} | {r['status']} | {'yes' if r['success'] else 'no'} | "
                  f"{'yes' if hand[r['id']][0] else 'no'} | {hand[r['id']][1]} |" for r in read]
    lines += ["", "## Each task", "", "| task | ended | judge | calls | s | $ | judge's why |", "|---|---|---|---|---|---|---|"]
    lines += [f"| {r['id']} | {r['status']} | {'yes' if r['success'] else 'no'} | {r['calls']} | {r['seconds']} | "
              f"{r['cost'] + r['judge_cost']:.4f} | {r['why'].replace('|', '/')} |" for r in rows]
    table = "\n".join(lines) + "\n"
    (out / "table.md").write_text(table, encoding="utf-8")
    return table


if __name__ == "__main__":
    print(main(Path(sys.argv[1])))
