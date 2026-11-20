"""The model's pick at recorded moments, scored by what the picked thing is truly worth to the person.

    python tools/recsim/picks.py --snapshot <dir> --env <.env with a model> name=<moments dir> [name2=<dir2> ...]
                                 [--per 12] [--judge 40] [--out picks.json]

A moments folder comes from `sim.py --arms rank1 --moments <dir>`. Give two folders written at two
states of the code (another prompt, another way of choosing the candidates) and both are asked at the
moments they share, so the difference is paired: the mean worth of the pick, of the candidates, of the
best among them and of the ranking's first, how often the pick is the ranking's first, and each
variant's pick minus the first variant's with its standard error. --judge N also has the model check N
of each variant's sentences against the thing and against what the app knew (report.judge).
One call per moment and variant: 12 moments for each of 12 people cost about two cents a variant.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE))

from mibo import recommend  # noqa: E402
from mibo.textproc import salvage_json_object, strip_json_fences  # noqa: E402
from llm import Model  # noqa: E402
import report  # noqa: E402


def load(folder: Path) -> dict:
    rows = {}
    for path in sorted(folder.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            rows[(row["person"], row["at"])] = row
    return rows


def _mean(values) -> float:
    values = list(values)
    return sum(values) / len(values)


def _paired(a: list, b: list) -> list:
    d = [x - y for x, y in zip(a, b)]
    spread = (sum((x - _mean(d)) ** 2 for x in d) / (len(d) - 1)) ** 0.5 / len(d) ** 0.5
    return [round(_mean(d), 4), round(spread, 4)]


async def ask(model: Model, limit: asyncio.Semaphore, moment: dict) -> dict:
    async with limit:
        answer = await model.ask(moment["system"], moment["user"], max_tokens=recommend.MAX_TOKENS)
    value = salvage_json_object(strip_json_fences(answer or ""))
    value = value if isinstance(value, dict) else {}
    # As the app reads it: the tie is kept only when what it rests on is in the moment's grounds.
    picked = recommend.parse(answer, [({"id": i}, None) for i in moment["ids"]], "zh", moment.get("found"))
    line = picked[2] if picked else ""
    # An answer the app could not use falls back to the ranking's first, as the app does.
    place = moment["ids"].index(picked[0]["id"]) if picked else None
    tie = value.get("tie") if isinstance(value.get("tie"), str) else ""
    alone = recommend.clean_line(value.get("line"), "zh") if isinstance(value.get("line"), str) else ""
    return {"place": place, "line": line, "worth": moment["worth"][place or 0], "tie": tie,
            "from": str(value.get("from") or ""), "tie_kept": bool(line) and line != alone}


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("variants", nargs="+", help="name=<moments dir>")
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--env", type=Path, required=True)
    parser.add_argument("--per", type=int, default=12, help="moments per person")
    parser.add_argument("--judge", type=int, default=0)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    variants = {name: load(Path(folder)) for name, folder in (v.split("=", 1) for v in args.variants)}
    shared = sorted(set.intersection(*(set(rows) for rows in variants.values())))
    rng = random.Random(args.seed)
    keys = []
    for person in sorted({k[0] for k in shared}):
        own = [k for k in shared if k[0] == person]
        keys += rng.sample(own, min(args.per, len(own)))
    model = Model(args.env)
    limit = asyncio.Semaphore(8)
    out = {"moments": len(keys), "variants": {}}
    picks = {}
    for name, rows in variants.items():
        moments = [rows[k] for k in keys]
        picks[name] = got = await asyncio.gather(*(ask(model, limit, m) for m in moments))
        first = next(iter(picks.values()))
        out["variants"][name] = row = {
            "pick": round(_mean(g["worth"] for g in got), 3),
            "candidates": round(_mean(_mean(m["worth"]) for m in moments), 3),
            "best_candidate": round(_mean(max(m["worth"]) for m in moments), 3),
            "ranking_first": round(_mean(m["worth"][0] for m in moments), 3),
            "best_in_pool": round(_mean(m["best"] for m in moments), 3),
            "picked_ranking_first": round(_mean(g["place"] == 0 for g in got), 3),
            "no_usable_answer": round(_mean(g["place"] is None for g in got), 3),
            "pick_minus_ranking_first": _paired([g["worth"] for g in got], [m["worth"][0] for m in moments]),
            "pick_minus_first_variant": _paired([g["worth"] for g in got], [g["worth"] for g in first]),
            "prompt_chars": round(_mean(len(m["system"]) + len(m["user"]) for m in moments)),
            "tie_written": round(_mean(bool(g["tie"]) for g in got), 3),
            "tie_kept": round(_mean(g["tie_kept"] for g in got), 3)}
        if args.judge:
            labels = json.loads((args.snapshot / "labels.json").read_text(encoding="utf-8"))
            items = {it["id"]: it for it in map(json.loads, (args.snapshot / "items.jsonl").read_text(
                encoding="utf-8").splitlines())}
            cards = [{"id": m["ids"][g["place"]], "line": g["line"], "knew": m["knew"], "interests": m["interests"],
                      "subject": max(labels[m["ids"][g["place"]]]["subjects"].items(), key=lambda kv: kv[1])[0]}
                     for m, g in zip(moments, got) if g["place"] is not None]
            verdict = await report.judge([{"arm": "app", "person": "", "cards": cards}], items, model, args.judge)
            row["sentences"] = {k: round(v, 3) if isinstance(v, float) else v
                                for k, v in verdict.items() if k != "cases"}
            row["cases"] = verdict["cases"]
        print(name, json.dumps({k: v for k, v in row.items() if k != "cases"}, ensure_ascii=False))
    out["calls"], out["cost"] = model.calls, round(model.cost, 4)
    print(f"{model.calls} calls, ${model.cost:.4f}")
    if args.out:
        args.out.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
