"""How well the app's word lists (mibo/subjects.py) find what a thing is about.

    python tools/recsim/subjects_check.py --snapshot <dir> [--misses ai,food]

Against the snapshot's labels (snapshot.py, one model call per item, made once): for how many items
the labelled main subject is among those the words find, and how often a found subject is one of
the labelled ones, with and without what the item's source says it brings as the fallback. The
simulated people's thirty subjects and the app's are two lists; TO maps the app's onto theirs.
No model is called.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mibo import subjects
from mibo.sources import catalog

TO = {"ai": "ai", "programming": "programming", "security": "programming", "gadgets": "gadgets", "internet": "gadgets",
      "tech": "gadgets", "games": "games", "anime": "anime", "film": "film", "music": "music", "books": "books",
      "philosophy": "books", "history": "history", "space": "space", "physics": "physics_chem",
      "biology": "biology_med", "science": "physics_chem", "health": "health", "fitness": "health", "food": "food",
      "travel": "travel", "outdoors": "travel", "design": "design_art", "art": "design_art", "architecture": "design_art",
      "fashion": "design_art", "photography": "photography", "finance": "finance", "crypto": "finance",
      "economy": "finance", "business": "business", "career": "business", "politics": "world_politics",
      "society": "china_society", "relationships": "china_society", "law": "law_crime", "environment": "environment",
      "sports": "sports", "cars": "cars", "military": "military", "education": "education", "parenting": "education",
      "humor": "humor", "celebrity": "celebrity", "nature": "nature", "pets": "nature", "diy": "design_art"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--misses", default="", help="list the items missed on these labelled subjects")
    args = parser.parse_args()
    labels = json.loads((args.snapshot / "labels.json").read_text(encoding="utf-8"))
    items = [json.loads(line) for line in (args.snapshot / "items.jsonl").read_text(encoding="utf-8").splitlines() if line]
    sources = catalog.all_sources([])
    for fallback in (False, True):
        total, hit, found, right, missed = Counter(), Counter(), Counter(), Counter(), defaultdict(list)
        none = 0
        for it in items:
            label = labels.get(it["id"])
            if not label:
                continue
            main_subject = max(label["subjects"].items(), key=lambda kv: kv[1])[0]
            rest = " ".join(((it.get("description") or it.get("text") or "")[:600], it.get("site") or "",
                             *map(str, it.get("tags") or [])))
            got = subjects.of(it["title"], rest)
            source = sources.get(it.get("source") or "")
            if fallback and not got and source:
                got = subjects.of("", " ".join((*source.name, *source.about)))
            mapped = {TO[key] for key in got}
            total[main_subject] += 1
            hit[main_subject] += main_subject in mapped
            none += not got
            if main_subject not in mapped:
                missed[main_subject].append((it.get("source"), it["title"][:60], got))
            for subject in mapped:
                found[subject] += 1
                right[subject] += subject in label["subjects"]
        print(f"{'with' if fallback else 'without'} the source's own line: {sum(total.values())} items, "
              f"{none} with no subject; main subject found {sum(hit.values()) / sum(total.values()):.3f}; "
              f"a found subject is a labelled one {sum(right.values()) / sum(found.values()):.3f}")
        if fallback:
            for subject, n in total.most_common():
                print(f"  {subject:16} {n:4} items, found {hit[subject] / n:.2f}; named for {found[subject]:3}, "
                      f"rightly {right[subject] / found[subject] if found[subject] else 0:.2f}")
            for subject in filter(None, args.misses.split(",")):
                for row in missed[subject][:30]:
                    print("   missed", subject, row)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
