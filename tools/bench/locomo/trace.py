"""Where a LoCoMo answer was lost, read from a run's traces (replay.py) and its verdicts (score.py).

    python tools/bench/locomo/trace.py <out folder> [--answers answers.jsonl]

For every question answered wrong (J = 0, or F1 under 0.5 where no verdict is kept) the words of the gold answer not
already in the question, stemmed as score.py stems them, are looked for in three places:
- the store when the questions ran (person_end.json: facts, past ones too, plans, the talk's summary and topics),
- the chat record when the questions ran (chatlog_end.json: what past-chat search can reach),
- every request the reply loop sent for that question (model-full.jsonl rows `full`: system prompt, turn context,
  tool results).
Half of those words or more in a place counts as found there. The question is then "never kept" (in neither the
store nor the record), "kept, not recalled" (in one of them, in no request) or "recalled, not used" (in a request,
answered wrong). A word match is a reading aid, not a verdict: README.md lists the cases read by hand.

Out: <out>/trace_<answers stem>.json and a summary on stdout."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from score import STEM, f1, normalize

STOP = set("i me my you your he she his her they them their we our it its is was are were be been to of in on at for "
           "with by from as that this what when where who why how did do does about after before".split())


def stems(text: str) -> set[str]:
    return {STEM.stem(w) for w in normalize(text).split() if w not in STOP}


def found(gold: set[str], text: str) -> bool:
    return bool(gold) and len(gold & stems(text)) * 2 >= len(gold)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--answers", default="answers.jsonl")
    args = ap.parse_args(argv)
    full = [json.loads(line) for line in (args.out / "model-full.jsonl").read_text(encoding="utf-8").splitlines()]
    cases, counts = [], {}
    for path in sorted(args.out.glob(f"*/out/{args.answers}")):
        out = path.parent
        verdicts = {}
        judge = out / ("judge_" + args.answers)
        if judge.exists():
            verdicts = {json.loads(line)["k"]: json.loads(line)["j"] for line in judge.read_text(encoding="utf-8").splitlines()}
        store = json.loads((out / "person_end.json").read_text(encoding="utf-8"))
        kept = "\n".join([f["text"] for f in store["facts"]] + [p["text"] for p in store["plans"]]
                         + [store["talk"].get("summary") or ""] + [t["words"] for t in store["talk"].get("topics") or []])
        record = "\n".join(r["text"] for r in json.loads((out / "chatlog_end.json").read_text(encoding="utf-8")))
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            right = verdicts[row["k"]] if row["k"] in verdicts else f1(row) >= 0.5
            if right:
                continue
            gold = stems(str(row["answer"])) - stems(row["question"])
            asked = "\n".join(json.dumps(m.get("content"), ensure_ascii=False)
                              for r in full[row["full"][0]:row["full"][1]] for m in r.get("messages") or [])
            where = {"store": found(gold, kept), "record": found(gold, record), "request": found(gold, asked)}
            kind = ("recalled, not used" if where["request"] else
                    "kept, not recalled" if where["store"] or where["record"] else "never kept")
            counts.setdefault(kind, {}).setdefault(str(row["category"]), 0)
            counts[kind][str(row["category"])] += 1
            cases.append({"conv": path.parents[1].name, "k": row["k"], "category": row["category"], "kind": kind,
                          **where, "question": row["question"], "answer": row["answer"], "reply": row["reply"][:400],
                          "steps": row.get("steps"), "evidence": row.get("evidence")})
    summary = {kind: {"n": sum(c.values()), "by_category": c} for kind, c in sorted(counts.items())}
    (args.out / f"trace_{Path(args.answers).stem}.json").write_text(
        json.dumps({"summary": summary, "cases": cases}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
