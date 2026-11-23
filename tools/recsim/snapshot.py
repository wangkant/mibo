"""Freeze what homes gathered into a snapshot the simulation loads, and label it once.

    python tools/recsim/snapshot.py freeze --runtime <dir> [--runtime <dir> ...] --out <snapshot>
    python tools/recsim/snapshot.py label --snapshot <snapshot> --env <.env with a model>
    python tools/recsim/snapshot.py census --runtime <dir>

`freeze` copies every item of each runtime's library as the app keeps it (items.jsonl, the
features the app ranks by) and leaves the pictures behind. `label` asks the model once, in
batches, what each item is truly about and how good it is, and writes labels.json beside it.
The simulated people read labels.json; the app never sees it, so it cannot win by reading
its own labels. `census` reads every public source once into a runtime (no model), so a snapshot
can hold what the whole catalogue brings, not only what one home's weights happened to draw.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from llm import Model  # noqa: E402
from people import SUBJECTS  # noqa: E402

from mibo.library import Library  # noqa: E402

BATCH = 25

_LABEL = """You label things a recommender may show people, so a simulation knows the truth about each.
Subjects, by key:
{subjects}

For each numbered thing answer:
- "subjects": the 1-3 subject keys it is truly about, with weights summing to 1 (main subject first). Use only the keys above.
- "quality": 1-5, how worth the time it is for someone who cares about its subject: 1 spam, an ad, a bare list or a stub;
  2 thin or clickbait; 3 ordinary news or post; 4 solid, informative or fun; 5 outstanding.
- "lang": "zh", "en" or "other", the language a reader needs.
- "story": the event or work it is about in 3-6 English words, so two pieces on the same story can be told.
Answer JSON only: {{"items": [{{"n": 1, "subjects": {{"<key>": 0.7, "<key>": 0.3}}, "quality": 3, "lang": "zh", "story": "..."}}]}}"""


def freeze(runtimes: list[Path], out: Path) -> None:
    rows: dict[str, dict] = {}
    for runtime in runtimes:
        for item in Library(runtime).items(newest_first=False):
            if item.private:
                continue
            row = asdict(item)
            row["picture"] = ""
            rows.setdefault(item.id, row)
    out.mkdir(parents=True, exist_ok=True)
    (out / "items.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows.values()),
                                     encoding="utf-8")
    print(f"froze {len(rows)} items from {len(runtimes)} runtimes into {out}")


def load_items(snapshot: Path) -> list[dict]:
    return [json.loads(line) for line in (snapshot / "items.jsonl").read_text(encoding="utf-8").splitlines() if line]


def _clean(row: dict) -> dict | None:
    subjects = {k: float(v) for k, v in (row.get("subjects") or {}).items()
                if k in SUBJECTS and isinstance(v, (int, float)) and v > 0}
    if not subjects:
        return None
    total = sum(subjects.values())
    return {"subjects": {k: round(v / total, 3) for k, v in subjects.items()},
            "quality": max(1, min(5, int(row.get("quality") or 3))),
            "lang": row.get("lang") if row.get("lang") in ("zh", "other") else "en", "story": str(row.get("story") or "")[:80]}


async def label(snapshot: Path, env: Path) -> None:
    items = load_items(snapshot)
    path = snapshot / "labels.json"
    labels = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    todo = [it for it in items if it["id"] not in labels]
    model = Model(env)
    system = _LABEL.format(subjects="\n".join(f"- {k}: {zh} / {en}" for k, (zh, en, _) in SUBJECTS.items()))

    async def one(batch: list[dict]) -> None:
        things = "\n\n".join(
            f"{n}. [{it['kind']}] {it['title']}\nsite: {it['site']}\n"
            + " ".join((it.get("description") or it.get("text") or "").split())[:300]
            for n, it in enumerate(batch, 1))
        for _ in range(2):
            answer = await model.ask(system, things, max_tokens=60 * len(batch) + 200)
            try:
                rows = json.loads(answer)["items"]
            except (ValueError, KeyError, TypeError):
                continue
            for row in rows:
                n = row.get("n") if isinstance(row, dict) else None
                if isinstance(n, int) and 1 <= n <= len(batch):
                    got = _clean(row)
                    if got:
                        labels[batch[n - 1]["id"]] = got
            return

    batches = [todo[i:i + BATCH] for i in range(0, len(todo), BATCH)]
    gate = asyncio.Semaphore(6)

    async def gated(batch):
        async with gate:
            await one(batch)
    await asyncio.gather(*(gated(b) for b in batches))
    path.write_text(json.dumps(labels, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"labelled {len(labels)} of {len(items)}; model cost ${model.cost:.4f}")


async def census(runtime: Path) -> None:
    """Every public source read once into `runtime`'s library through the app's own fetch and keep
    (catalog._fetch, then kept as _keep keeps them), whatever the weights would draw: what the catalogue
    can bring at all.
    No model is called. One line per source: how many it brought, or its error."""
    from mibo import situation
    from mibo.library import Library, item_id
    from mibo.sources import base, catalog
    sources = [s for s in catalog.all_sources([]).values() if s.group != "own"]
    library = Library(runtime)
    known = {it.id for it in library.items()}
    gate = asyncio.Semaphore(catalog.AT_ONCE)
    async with base.client(**situation.client_options(runtime)) as http:
        answers = await asyncio.gather(*(catalog._fetch(http, s, gate) for s in sources))
        new = []
        for source, (finds, error, _) in zip(sources, answers):
            print(f"{source.key:28s} {len(finds):3d} {error}")
            for found in finds:
                if item_id(found.item.url) not in known:
                    known.add(item_id(found.item.url))
                    found.item.source = source.key
                    new.append(found)
    # Kept as catalog._keep keeps them, without its compact: the library's cap would drop the first
    # sources' finds. Covers are left out: a snapshot drops pictures anyway.
    for found in new:
        found.item.id, found.item.fits, found.item.why = item_id(found.item.url), False, ""
        library.add(found.item)
    print(f"census: {len(sources)} sources, {sum(1 for _, (f, _, _) in zip(sources, answers) if f)} answered, "
          f"{len(new)} new things")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    f = sub.add_parser("freeze")
    f.add_argument("--runtime", type=Path, action="append", required=True)
    f.add_argument("--out", type=Path, required=True)
    lab = sub.add_parser("label")
    lab.add_argument("--snapshot", type=Path, required=True)
    lab.add_argument("--env", type=Path, required=True)
    cen = sub.add_parser("census")
    cen.add_argument("--runtime", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "freeze":
        freeze(args.runtime, args.out)
    elif args.command == "census":
        asyncio.run(census(args.runtime))
    else:
        asyncio.run(label(args.snapshot, args.env))


if __name__ == "__main__":
    main()
