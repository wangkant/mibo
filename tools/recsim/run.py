"""The whole measurement in one command: twelve simulated people, thirty days each, the app beside
random, popular and an oracle (and the app's path with one part changed, see sim.VARIANTS), then
the table.

    python tools/recsim/run.py --snapshot <dir> --env <.env with a model> --work <dir> [--days 30]
                               [--people zhou,ling,...] [--seed N] [--report-only] [--no-judge]
                               [--arms rank1,random,oracle] [--moments <dir>]

--arms runs only those (none but "app" calls the model); --moments is sim.py's, for picks.py.

<snapshot> holds items.jsonl and labels.json (snapshot.py). The app arm calls the model the .env names
once per card, as the app does; the labels and the sentence check call it too. Each person runs in its
own process; their cards go to <work>/<person>.json, the numbers to <work>/report.json, and the table
is printed. --report-only reads the cards already in <work>.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from llm import Model  # noqa: E402
from people import PEOPLE  # noqa: E402
from people2 import FRESH  # noqa: E402
import report  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--env", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--people", default=",".join(t.name for t in PEOPLE),
                        help="names, or 'fresh' for people2.py's twelve")
    parser.add_argument("--seed", type=int, default=0, help="another draw of the same people's days")
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--no-judge", action="store_true")
    parser.add_argument("--arms", default="")
    parser.add_argument("--moments", type=Path, default=None)
    args = parser.parse_args()
    more = (["--arms", args.arms] if args.arms else []) + (["--moments", str(args.moments)] if args.moments else [])
    names = [t.name for t in FRESH] if args.people == "fresh" else args.people.split(",")
    if not args.report_only:
        args.work.mkdir(parents=True, exist_ok=True)
        procs = {name: subprocess.Popen([sys.executable, str(HERE / "sim.py"), "--snapshot", str(args.snapshot),
                                         "--env", str(args.env), "--work", str(args.work), "--person", name,
                                         "--days", str(args.days), "--seed", str(args.seed), *more],
                                        stderr=open(args.work / f"{name}.err", "w", encoding="utf-8"))
                 for name in names}
        for name, proc in procs.items():
            if proc.wait():
                print(f"{name}: the simulation failed, see {args.work / (name + '.err')}")
    results = []
    for name in names:
        path = args.work / f"{name}.json"
        if path.is_file():
            results.extend(json.loads(path.read_text(encoding="utf-8")))
        else:
            print(f"{name}: no cards, left out")
    items = {json.loads(line)["id"]: json.loads(line)
             for line in (args.snapshot / "items.jsonl").read_text(encoding="utf-8").splitlines() if line}
    labels = json.loads((args.snapshot / "labels.json").read_text(encoding="utf-8"))
    got = report.measures(results, items, labels, args.days)
    cold = {arm: got["people"][arm].get("new", {}) for arm in got["people"]}
    if not args.no_judge and "app" in got["overall"]:
        model = Model(args.env)
        got["sentences"] = asyncio.run(report.judge(results, items, model))
        got["judge_cost"] = model.cost
    got["pick_calls"] = {run["person"]: run.get("pick_calls") for run in results if run["arm"] == "app"}
    (args.work / "report.json").write_text(json.dumps(got, ensure_ascii=False, indent=1), encoding="utf-8")
    print(report.table(got["overall"], cold))
    if "sentences" in got:
        s = got["sentences"]
        print(f"\nsentences judged {s['judged']}: true to the item {s['item_true']:.2f}, stretch {s['item_stretch']:.2f}, "
              f"false {s['item_false']:.2f}; about the person none {s['person_none']:.2f}, supported "
              f"{s['person_supported']:.2f}, made up {s['person_made_up']:.2f}; generic {s['generic']:.2f}")
    print("\n" + report.daily_table(got["daily"]))


if __name__ == "__main__":
    main()
