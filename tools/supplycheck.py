"""What a new person's first two source rounds bring, on a fresh runtime with the real network: the share
written in their language, the spread over subjects, and text against video.

    python tools/supplycheck.py --runtime <empty folder> --topics food,travel,history [--lang zh] [--out r.json]
    python tools/supplycheck.py --draws 2000 --topics food,travel,history [--lang zh]

The first form saves the topics as the first run does, starts the first start's host check, waits as the
app waits before its first round (catalog.FIRST_ROUND_S), and runs catalog.run_round twice. Every new
library thing is counted: written in the person's language (for zh: Han characters and no kana in its
title), its subjects (subjects.of), video or not, bearing on a topic (feed.topic_matcher), with a picture.
The second form needs no network: the expected share of a round's sources in the person's language, and
their groups, over that many draws of weights.pick on an empty runtime.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import random
import re
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_HAN = re.compile(r"[一-鿿]")
_KANA = re.compile(r"[぀-ヿ]")


def in_lang(text: str, lang: str) -> bool:
    if lang.startswith("zh"):
        return bool(_HAN.search(text)) and not _KANA.search(text)
    return not _HAN.search(text) and not _KANA.search(text)


def entropy(counts: Counter) -> float:
    total = sum(counts.values())
    return round(-sum(c / total * math.log2(c / total) for c in counts.values() if c), 2) if total else 0.0


def summary(items: list, lang: str, topics: list[str]) -> dict:
    from mibo import subjects
    from mibo.panels import feed
    matcher = feed.topic_matcher(topics)
    subj, sources = Counter(), Counter()
    ours = video = bearing = pictured = 0
    for item in items:
        ours += in_lang(item.title, lang)
        video += item.kind == "video"
        pictured += bool(item.picture)
        text = " ".join((item.title, item.description[:300], item.site)).casefold()
        bearing += bool(matcher and matcher.search(text))
        for key in subjects.of(item.title, item.description) or ("(none)",):
            subj[key] += 1
        sources[item.source] += 1
    n = len(items) or 1
    named = Counter({k: v for k, v in subj.items() if k != "(none)"})
    return {"things": len(items), "in_lang": round(ours / n, 3), "video": round(video / n, 3),
            "bearing": round(bearing / n, 3), "pictured": round(pictured / n, 3),
            "subjects": len(named), "subject_entropy": entropy(named),
            "top_subject_share": round(named.most_common(1)[0][1] / max(1, sum(named.values())), 3) if named else 0,
            "no_subject": round(subj["(none)"] / n, 3), "top_subjects": named.most_common(8),
            "sources": len(sources), "per_source": sources.most_common()}


async def rounds(runtime: Path, lang: str, topics: list[str]) -> dict:
    from mibo import situation
    from mibo.library import Library
    from mibo.panels import feed
    from mibo.sources import catalog
    runtime.mkdir(parents=True, exist_ok=True)
    feed.keep_topics(runtime, feed.clean_topics(topics))
    probe = asyncio.create_task(situation.probe(runtime, lang))
    await asyncio.sleep(catalog.FIRST_ROUND_S)
    report: dict = {"topics": topics, "lang": lang, "readable": sorted(situation.readable(runtime)), "rounds": []}
    library = Library(runtime)
    all_new = []
    for n in (1, 2):
        before = {i.id for i in library.items()}
        started = time.time()
        _, picked = await catalog.run_round(runtime, lang)
        new = [i for i in library.items() if i.id not in before]
        all_new += new
        known = catalog.all_sources([])
        groups = Counter(known[k].group for k in picked if k in known)
        report["rounds"].append({"round": n, "seconds": round(time.time() - started, 1), "picked": picked,
                                 "groups": dict(groups), **summary(new, lang, topics)})
        print(json.dumps({k: v for k, v in report["rounds"][-1].items() if k not in ("per_source", "picked")},
                         ensure_ascii=False), flush=True)
    probe.cancel()
    report["both"] = summary(all_new, lang, topics)
    report["titles"] = [[i.source, i.kind, i.title[:80]] for i in all_new]
    return report


def draws(lang: str, topics: list[str], count: int) -> dict:
    from mibo.panels import feed
    from mibo.sources import catalog, weights
    with tempfile.TemporaryDirectory() as folder:
        runtime = Path(folder)
        feed.keep_topics(runtime, feed.clean_topics(topics))
        sources = catalog.all_sources([])
        rng = random.Random(7)
        ours, groups, video = 0, Counter(), 0
        for _ in range(count):
            picked = weights.pick(catalog.weighed(runtime, lang, sources, rng), rng)
            for row in picked:
                source = row["source"]
                ours += source.lang.startswith(lang[:2])
                groups[source.group] += 1
                video += source.group == "video"
        total = count * weights.ROUND
        return {"draws": count, "in_lang": round(ours / total, 3), "video_group": round(video / total, 3),
                "groups": {k: round(v / total, 3) for k, v in groups.most_common()}}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--topics", required=True)
    parser.add_argument("--lang", default="zh")
    parser.add_argument("--draws", type=int, default=0)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    topics = [t for t in args.topics.split(",") if t]
    if args.draws:
        report = draws(args.lang, topics, args.draws)
        print(json.dumps(report, ensure_ascii=False))
    else:
        report = asyncio.run(rounds(args.runtime.resolve(), args.lang, topics))
        print(json.dumps({k: v for k, v in report["both"].items() if k != "per_source"}, ensure_ascii=False))
    if args.out:
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
