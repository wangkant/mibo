"""KuaiRec's small matrix as the feed's library and a stratified sample of its people.

    python -I tools/bench/kuairec/prepare.py --zip <KuaiRec.zip> --out <dir> [--people 300] [--seed 7]

Reads the official zip as data (nothing in it is run or extracted). Writes to <out>:
videos.json (caption, cover text, hashtags, three category levels, duration, uploader per video),
library.json (the half of the videos the replay shows; the other half only says which categories
a person would name), people.json (the sample, with how much each likes, how narrow their taste is
and the three categories they would name), reactions.json (watch ratio and seconds played of each
sampled person on each library video) and popularity.json (mean watch ratio and watched-through share
of each library video over the people not in the sample).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import random
import zipfile
from collections import defaultdict
from pathlib import Path

DATA = "KuaiRec 2.0/data/"
STRATA = 5
# A category says what a person would name only with this many of their videos in the other half.
NAME_MIN = 15
TOPICS = 3


def rows(z: zipfile.ZipFile, name: str):
    with z.open(DATA + name) as f:
        yield from csv.DictReader(io.TextIOWrapper(f, "utf-8"))


def known(value) -> str:
    value = (value or "").strip()
    return "" if value in ("UNKNOWN", "None", "[]") else value


def half(vid: str) -> str:
    return "library" if int(hashlib.md5(vid.encode()).hexdigest(), 16) % 2 == 0 else "named"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--people", type=int, default=300)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    z = zipfile.ZipFile(args.zip)
    args.out.mkdir(parents=True, exist_ok=True)

    meta = {r["video_id"]: r for r in rows(z, "kuairec_caption_category.csv")}
    author = {}
    for r in rows(z, "item_daily_features.csv"):
        author.setdefault(r["video_id"], r["author_id"])

    # Pass 1: per person and per video sums.
    duration, users = {}, defaultdict(lambda: {"n": 0, "wr": 0.0, "through": 0})
    by_cat = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for r in rows(z, "small_matrix.csv"):
        vid, uid, wr = r["video_id"], r["user_id"], float(r["watch_ratio"])
        duration[vid] = float(r["video_duration"]) / 1000
        cat = known(meta.get(vid, {}).get("first_level_category_name")) or "?"
        if half(vid) == "library":
            u = users[uid]
            u["n"] += 1
            u["wr"] += wr
            u["through"] += wr >= 1
            by_cat[uid][cat][0] += 1
            by_cat[uid][cat][1] += wr >= 1
        else:
            by_cat[uid]["named:" + cat][0] += 1
            by_cat[uid]["named:" + cat][1] += wr >= 1

    videos = {}
    for vid, d in duration.items():
        m = meta.get(vid, {})
        videos[vid] = {"caption": known(m.get("caption")), "cover": known(m.get("manual_cover_text")),
                       "hashtags": [t for t in known(m.get("topic_tag")).strip("[]").split(",") if t.strip()],
                       "c1": known(m.get("first_level_category_name")), "c2": known(m.get("second_level_category_name")),
                       "c3": known(m.get("third_level_category_name")), "dur_s": round(d, 2),
                       "author": author.get(vid, "")}
    library = sorted((v for v in videos if half(v) == "library"), key=int)

    people = []
    for uid, u in users.items():
        cats = {c: nt for c, nt in by_cat[uid].items() if not c.startswith("named:")}
        p = u["through"] / u["n"]
        # Narrow taste: the share of the variance of "watched through" that the category explains.
        between = sum(n * (t / n - p) ** 2 for n, t in cats.values()) / u["n"]
        total = p * (1 - p)
        named = sorted(((t / n, c[6:]) for c, (n, t) in by_cat[uid].items()
                        if c.startswith("named:") and n >= NAME_MIN and c[6:] != "?"), reverse=True)
        people.append({"uid": uid, "n": u["n"], "mean_wr": round(u["wr"] / u["n"], 4), "through": round(p, 4),
                       "narrow": round(between / total, 4) if total else 0.0,
                       "topics": [c for _, c in named[:TOPICS]]})
    people.sort(key=lambda p: p["mean_wr"])
    for k, p in enumerate(people):
        p["stratum"] = k * STRATA // len(people)
    for key in ("narrow", "through"):
        ordered = sorted(people, key=lambda p: p[key])
        for k, p in enumerate(ordered):
            p[key + "_q"] = k * STRATA // len(ordered)
    rng = random.Random(args.seed)
    sample = []
    for s in range(STRATA):
        group = [p for p in people if p["stratum"] == s]
        sample += rng.sample(group, args.people // STRATA)
    chosen = {p["uid"] for p in sample}

    # Pass 2: the sample's reactions on the library, and everyone else's for popularity.
    lib = set(library)
    reactions = {uid: {} for uid in chosen}
    pop = defaultdict(lambda: [0, 0.0, 0])
    for r in rows(z, "small_matrix.csv"):
        vid, uid = r["video_id"], r["user_id"]
        if vid not in lib:
            continue
        wr = float(r["watch_ratio"])
        if uid in chosen:
            reactions[uid][vid] = [round(wr, 4), round(float(r["play_duration"]) / 1000, 2)]
        else:
            row = pop[vid]
            row[0] += 1
            row[1] += wr
            row[2] += wr >= 1
    popularity = {vid: {"mean_wr": round(s / n, 4), "through": round(t / n, 4)} for vid, (n, s, t) in pop.items()}

    def dump(name, value):
        (args.out / name).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    dump("videos.json", videos)
    dump("library.json", library)
    dump("people.json", sample)
    dump("everyone.json", people)
    dump("reactions.json", reactions)
    dump("popularity.json", popularity)
    print(f"videos {len(videos)}, library {len(library)}, people {len(people)}, sample {len(sample)}")


if __name__ == "__main__":
    main()
