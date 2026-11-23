"""Checks data/market/skills.json against itself and against its sources:

    python tools/skillmarket/check.py --cache <the build's cache folder> [--sample 2]

Offline, every entry: the fixed shape, one entry per skill (ids, folders and hashes unique), sources only on public
https git hosts at a full commit, a licence marked installable only when it was read from a file or field and is
an open one (or none was stated), and no third-party text beyond the skill's name (the written titles and
sentences share no long run of words with the skill's own description). Online, a sample per repository: the
source page opens at its commit, and the installer's own fetch (file by file, mirrors included) brings the folder
whole.
"""
from __future__ import annotations

import argparse
import asyncio
import difflib
import json
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from build import AGENT, OPEN, OUT, SHARE_ALIKE, market  # noqa: E402
from places import layout  # noqa: E402

HOSTS = ("https://github.com/", "https://gitlab.com/", "https://codeberg.org/", "https://gitee.com/")
SHAPE = {"id", "name", "title", "about", "publisher", "source", "licence", "category", "sub", "tags", "needs", "fit",
         "fit_note", "popularity", "hash", "files", "scan", "updated"}
PLACES = layout()
# The spoken forms tools/copy_check.py lists; the catalog's Chinese is interface text too.
SPOKEN = re.compile(r"[吧啦呀哦嘛呗]|呢[。？！”\"]|一下|看看|试试|做了什么|先问你|替你|帮你|等你|[搞弄]|啥|咋|没找到|找不到|"
                    r"打不开|用不了|这台电脑|东西|要不要|没问题|觅波")


def problems_offline(catalog: dict, cache: Path) -> list[str]:
    out = []
    facts = {}
    for data in json.loads((cache / "facts.json").read_text(encoding="utf-8")):
        for s in data["skills"]:
            facts[(data["repo"], data["commit"], s["path"])] = s
    seen = defaultdict(set)
    for e in catalog["skills"]:
        sid = e.get("id", "?")
        if set(e) != SHAPE:
            out.append(f"{sid}: keys {sorted(set(e) ^ SHAPE)}")
            continue
        src = e["source"]
        for key, value in (("id", sid), ("folder", (src["repo"], src["path"])), ("hash", e["hash"])):
            if value in seen[key]:
                out.append(f"{sid}: duplicate {key}")
            seen[key].add(value)
        if not src["url"].startswith(HOSTS) or not re.fullmatch(r"[0-9a-f]{40}", src["commit"]) \
                or not re.fullmatch(r"[\w.-]+/[\w.-]+", src["repo"]) or ".." in src["path"]:
            out.append(f"{sid}: source not a public git host at a full commit")
        if e["category"] not in PLACES or e["sub"] not in (PLACES[e["category"]] or [""]):
            out.append(f"{sid}: place {e['category']}/{e['sub']}")
        if market.listed_hash(e["files"]) != e["hash"]:
            out.append(f"{sid}: file hashes do not make up the folder hash")
        if e["fit"] not in ("ready", "partial", "no") or (e["fit"] != "ready") != bool(e["fit_note"]):
            out.append(f"{sid}: fit")
        if e["scan"]["risk"] not in ("none", "low", "high"):
            out.append(f"{sid}: risk")
        for lang in ("zh", "en"):
            if not e["title"][lang] or not e["about"][lang]:
                out.append(f"{sid}: missing {lang} text")
        for text in (e["title"]["zh"], e["about"]["zh"], e["fit_note"], e["licence"]["note"]):
            if SPOKEN.search(text or ""):
                out.append(f"{sid}: spoken Chinese in {text!r}")
        fact = facts.get((src["repo"], src["commit"], src["path"]))
        if not fact:
            out.append(f"{sid}: no build record at its commit")
            continue
        if fact["hash"] != e["hash"]:
            out.append(f"{sid}: hash differs from the build record")
        lic = e["licence"]
        read = fact["licence"]
        if lic["spdx"] != read["spdx"] and not (lic["spdx"] == "CUSTOM" and read["spdx"] not in OPEN | SHARE_ALIKE):
            out.append(f"{sid}: licence {lic['spdx']} is not the {read['spdx']} read")
        if lic["installable"] and not ((read["spdx"] in OPEN | SHARE_ALIKE and read.get("file"))
                                       or read["spdx"] == "NONE"):
            out.append(f"{sid}: installable licence that was not read")
        # Third-party text: nothing written may share a long run with the skill's own description.
        desc = fact["description"].lower()
        for text in (e["about"]["en"], e["title"]["en"]):
            m = difflib.SequenceMatcher(None, desc, text.lower(), autojunk=False)
            run = m.find_longest_match(0, len(desc), 0, len(text))
            if run.size > 60:
                out.append(f"{sid}: about repeats {run.size} characters of the description")
    return out


def check_online(catalog: dict, per_repo: int) -> tuple[int, list[str]]:
    by_repo = defaultdict(list)
    for e in sorted(catalog["skills"], key=lambda e: e["hash"]):
        by_repo[(e["source"]["repo"], e["source"]["commit"])].append(e)
    checked, out = 0, []
    home = Path(tempfile.mkdtemp(prefix="skillmarket-check-"))
    for (repo, commit), entries in sorted(by_repo.items()):
        sample = entries[:per_repo]
        for e in sample:
            # The installer's own path: each file from the first host that answers, checked against the entry.
            try:
                asyncio.run(market.fetch(home, market.entry(e)))
            except ValueError as err:
                out.append(f"{e['id']}: not fetched whole ({err})")
            try:
                page = urllib.request.urlopen(urllib.request.Request(e["source"]["url"], headers={
                    "User-Agent": AGENT}), timeout=60)
                if page.status != 200:
                    out.append(f"{e['id']}: source page {page.status}")
            except urllib.error.HTTPError as err:
                out.append(f"{e['id']}: source page {err.code}")
            checked += 1
            time.sleep(1)
        print(f"  {repo}: {len(sample)} checked", flush=True)
    return checked, out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--cache", required=True, type=Path)
    ap.add_argument("--sample", type=int, default=2, help="entries fetched fresh per repository; 0 skips the network")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    catalog = json.loads((OUT / "skills.json").read_text(encoding="utf-8"))
    skills = catalog["skills"]
    print(f"{len(skills)} entries from {len({e['source']['repo'] for e in skills})} repositories")
    for key in ("fit", "category"):
        print(f"  {key}:", dict(Counter(e[key] for e in skills).most_common()))
    print("  licence:", dict(Counter(e["licence"]["spdx"] for e in skills).most_common()))
    print("  installable:", dict(Counter(e["licence"]["installable"] for e in skills)))
    print("  risk:", dict(Counter(e["scan"]["risk"] for e in skills).most_common()))
    out = problems_offline(catalog, args.cache.resolve())
    if args.sample:
        checked, more = check_online(catalog, args.sample)
        print(f"  fetched fresh and hashed: {checked}")
        out += more
    for line in out:
        print("PROBLEM", line)
    print(f"{len(out)} problems")
    return 1 if out else 0


if __name__ == "__main__":
    sys.exit(main())
