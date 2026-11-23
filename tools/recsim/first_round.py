"""The first run's sample finds measured offline: the round the app chooses now (feed.first_round) against the
one it chose before (`old_round`, one Thompson draw of the ranking walked in order, kept here as it was) and
against no round at all, on recsim's twenty-four people and a synthetic fresh library each. No model service.

    python tools/recsim/first_round.py --work <dir> [--seeds 3] [--first 0] [--draws 2]
                                       [--scenarios base,plat,one,five,none,thin,en] [--people zhou,ling]

The library: the sources a fresh install's two first rounds read for the person (catalog.weighed and
weights.pick, once on the language's defaults and once after the ticks), PER things each, whose true subjects
come from what the source says it brings (a hot list or a front page brings a broad mix); NAMED of the titles
name their subject in subjects.py's words, the rest say nothing, so the app falls back on the source's guess.
The person ticks what sim.py's arms tick, picks platforms from their form and interests in "plat", and answers
each sample with a like at the chance of their `worth`, as sim.py draws a reaction. After the round the model is
fitted (taste.train) and read:
- next20: the person's worth of the top 20 the feed then ranks (three draws), the first measure of learning;
- rho: Spearman's correlation of the posterior mean with the person's worth over the pool;
- unc: the score variance left; both over the things neither round (old, new) shows in that library, so a round
  that shows worse things does not leave better ones to its own next20;
- worth: the person's worth of the samples themselves (without the novelty bonus a reaction gets), the first
  impression; topics, platforms: the share of the picked ones the round asked about; subjects: distinct true
  subjects; prior_p: the prior's like chance on the samples; twice: one site twice running.
Each scenario's table gives the means and, beside each, the paired difference against `old` with its standard
error (se). <work> holds the runtimes while they run.
"""
from __future__ import annotations

import argparse
import math
import random
import shutil
import statistics
import sys
from collections import Counter, defaultdict
from itertools import pairwise
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))

from people import OFFERED, PEOPLE, Person, top  # noqa: E402
from people2 import FRESH, Fresh  # noqa: E402

from mibo import db, platforms, situation, subjects, taste  # noqa: E402
from mibo.library import Item, Library  # noqa: E402
from mibo.panels import feed  # noqa: E402
from mibo.sources import catalog, weights  # noqa: E402

NOW = 1_800_000_000.0
EVERYONE = PEOPLE + FRESH
PER, NAMED = 12, 0.7
METHODS = ("old", "new", "none")
MEASURES = ("next20", "rho", "unc", "worth", "topics", "platforms", "subjects", "prior_p", "twice", "n")
SCENARIOS = ("base", "plat", "one", "five", "none", "thin", "en")

# recsim's subjects by the app's subject that names them, and the app's others by the nearest of recsim's.
APP = {"ai": "ai", "programming": "programming", "gadgets": "gadgets", "games": "games", "anime": "anime",
       "film": "film", "music": "music", "books": "books", "history": "history", "space": "space",
       "physics_chem": "physics", "biology_med": "biology", "health": "health", "food": "food",
       "travel": "travel", "design_art": "art", "photography": "photography", "finance": "finance",
       "business": "business", "world_politics": "politics", "china_society": "society", "law_crime": "law",
       "environment": "environment", "sports": "sports", "cars": "cars", "military": "military",
       "education": "parenting", "humor": "humor", "celebrity": "celebrity", "nature": "nature"}
BACK = {app: sim for sim, app in reversed(APP.items())} | {
    "tech": "gadgets", "internet": "gadgets", "security": "programming", "science": "physics_chem",
    "fitness": "health", "design": "design_art", "architecture": "design_art", "economy": "finance",
    "crypto": "finance", "politics": "world_politics", "society": "china_society", "pets": "nature",
    "outdoors": "travel", "parenting": "education", "education": "education", "philosophy": "books",
    "fashion": "celebrity", "career": "business", "relationships": "china_society", "diy": "design_art"}
# What a hot list or a news front page brings.
HOT = {"zh": {"china_society": 3, "celebrity": 2, "humor": 2, "world_politics": 2, "law_crime": 1.5, "sports": 1,
              "finance": 1, "film": 1, "games": 1, "food": 0.5, "cars": 0.5, "military": 1, "gadgets": 1, "health": 0.5},
       "en": {"world_politics": 3, "business": 1.5, "finance": 1, "environment": 1, "law_crime": 1, "sports": 1,
              "film": 0.5, "gadgets": 1, "ai": 1, "biology_med": 0.5, "health": 0.5, "space": 0.3}}
BROAD = ("hot", "news", "home", "top", "rank", "popular", "precious", "world", "mostread", "featured", "trending",
         "-all", "links", "posts", "onthisday", "groups")
FILLER = {"zh": ["今天大家都在看这个", "没想到结局是这样", "这一期值得一看", "一个很少人知道的故事", "评论区吵翻了"],
          "en": ["What happened next", "The story behind it", "Why this matters now", "A closer look",
                 "Everyone is talking"]}
SOURCES = {k: s for k, s in catalog.all_sources([]).items() if s.lang in ("zh", "en", "zh-Hant")}

# ------------------------------------------------------------------ library --


def _words(app: str, zh: bool) -> list[str]:
    words = [w for w in subjects.SUBJECTS[app][2] if len(w) > 1]
    return [w for w in words if (not w.isascii()) == zh] or words


def _brings(source) -> dict:
    found = subjects.of("", " ".join((*source.name, *source.about)))
    if not found or (any(w in source.key for w in BROAD) and len(found) < 2):
        mix = dict(HOT["zh" if source.lang.startswith("zh") else "en"])
        for key in found:
            mix[BACK[key]] = mix.get(BACK[key], 0) + 4
        return mix
    return {BACK[key]: 3 - n for n, key in enumerate(found)}


def _things(source, rng: random.Random) -> list[tuple[Item, dict]]:
    zh = source.lang.startswith("zh")
    brings = _brings(source)
    video = source.group == "video" or (bool(source.platform) and source.platform in platforms.PLATFORMS
                                        and platforms.PLATFORMS[source.platform].kind == "video"
                                        and "article" not in source.key)
    pictured = 1.0 if video else 0.85 if source.group in ("news", "culture") else 0.55
    host = source.platform or source.key + ".example"
    out = []
    for i in range(PER):
        main = rng.choices(list(brings), list(brings.values()))[0]
        about, second = {main: 1.0}, None
        if rng.random() < 0.3:
            second = rng.choice([k for k in APP if k != main])
            about = {main: 0.8, second: 0.4}
        word, named = rng.choice(_words(APP[main], zh)), rng.random() < NAMED
        if zh:
            filler = rng.choice(FILLER["zh"])
            title = f"{word}：{filler}{i}" if named else f"{filler}（第{i}期）"
            text = (f"关于{word}的一段介绍，" if rng.random() < 0.5 else "") + "这里讲了来龙去脉，" * rng.randint(1, 6)
        else:
            filler = rng.choice(FILLER["en"])
            title = f"{word.title()}: {filler} {i}" if named else f"{filler}, part {i}"
            text = (f"On {word}: " if rng.random() < 0.5 else "") + "the whole story, told from the start. " * rng.randint(1, 5)
        if second and rng.random() < 0.5:
            text += " " + rng.choice(_words(APP[second], zh))
        if not video and rng.random() < 0.2:
            text = text[:20]
        length = int(rng.lognormvariate(5.8, 1.0)) if video else None
        ident = f"{source.key}-{int(NOW)}-{i}"
        out.append((Item(url=f"https://{host}/{'video' if video else 'post'}/{ident}", site=host,
                         kind="video" if video else "article", title=title, description=text,
                         text=text * 3 if not video and rng.random() < 0.5 else "", length=length,
                         embed=f"https://www.youtube-nocookie.com/embed/{ident}" if video else "",
                         picture="cover.jpg" if rng.random() < pictured else "", source=source.key,
                         seen_at=int(NOW - rng.uniform(0.05, 6) * 3600), love=-1, judged=False),
                    {"subjects": about, "quality": max(1.0, min(5.0, rng.gauss(3, 1))),
                     "lang": "zh" if zh else "en" if source.lang == "en" else "other"}))
    return out


def build(runtime: Path, lang: str, topics: list[str], chosen: list[str], rng: random.Random, thin: int) -> dict:
    """A fresh install's library and the true labels of its things, by id."""
    things, read = {}, set()
    for stage in ("defaults", "ticks"):
        if stage == "ticks":
            feed.keep_topics(runtime, topics)
            feed.keep_platforms(runtime, chosen)
        for row in weights.pick(catalog.weighed(runtime, lang, SOURCES, rng), rng):
            if row["source"].key not in read:
                read.add(row["source"].key)
                things.update((item.url, (item, label)) for item, label in _things(row["source"], rng))
    rows = list(things.values())
    if thin:
        rng.shuffle(rows)
        rows = rows[:thin]
    library = Library(runtime)
    return {library.add(item).id: label for item, label in rows}

# ------------------------------------------------------------------- people --


def ticks(t) -> list[str]:
    """The topics they tick, as sim.py's arms tick them."""
    if t in FRESH:
        return list(t.ticks or ()) + list(t.typed)
    strong = sorted((s for s, w in t.interests.items() if w >= 0.5), key=lambda s: -t.interests[s])
    return (list(dict.fromkeys(OFFERED[s] for s in strong if s in OFFERED))[:4] + list(t.typed)) if t.picks else []


def picked_platforms(t) -> list[str]:
    """The platforms their form and interests point at."""
    out = []
    if t.video >= 0.3 or getattr(t, "only", "") == "video":
        out += ["bilibili.com"] + (["youtube.com"] if t.english else [])
        out += ["douyu.com"] if t.interests.get("games", 0) >= 0.5 else []
        out += ["qq.com"] if max(t.interests.get("film", 0), t.interests.get("celebrity", 0)) >= 0.5 else []
    out += ["github.com"] if t.interests.get("programming", 0) >= 0.5 else []
    out += ["douban.com"] if max(t.interests.get("books", 0), t.interests.get("film", 0)) >= 0.5 else []
    out += ["zhihu.com"] if max(t.interests.get("china_society", 0), t.interests.get("law_crime", 0)) >= 0.5 else []
    return list(dict.fromkeys(out))


def scenario(name: str, t) -> dict:
    s = {"topics": ticks(t), "platforms": [], "lang": "zh", "thin": 0,
         "read": list(getattr(t, "os_langs", None) or (("zh", "en") if t.english else ("zh",)))}
    if name == "plat":
        s["platforms"] = picked_platforms(t)
    elif name == "one":
        s["topics"] = s["topics"][:1]
    elif name == "five":
        more = ("tech", "ai", "games", "film", "food", "travel", "science", "history", "music")
        s["topics"] = (s["topics"] + [k for k in more if k not in s["topics"]])[:5]
    elif name == "none":
        s["topics"] = []
    elif name == "thin":
        s["thin"] = 15
    elif name == "en":
        s["read"], s["lang"] = ["en"], "en"
    return s

# ------------------------------------------------------------- the old round --


def _varied(veins: feed.Veins, rows: list) -> list:
    """Veins.varied with text and video in turn, as the old round ordered its rows."""
    seen = {row[1].id: veins.of(*row) for row in rows}
    left, placed, last, video = list(rows), [], None, None
    while left:
        apart = [r for r in left if not veins.same(seen[r[1].id], last)]
        row = (next((r for r in apart if feed.is_video(r[1], r[0]) != video), None) or next(iter(apart), None)
               or next((r for r in left if not veins.same(seen[r[1].id], last, False)), left[0]))
        left.remove(row)
        placed.append(row)
        last, video = seen[row[1].id], feed.is_video(row[1], row[0])
    return placed


def old_round(library: Library, events: list, now: float, topics: list[str], chosen: list[str] = ()) -> list[dict]:
    """feed.first_round before the design: the draw's best unseen presentable, two a site, a place kept for each
    chosen platform, the character's judged first, then varied."""
    carried = {key: source.platform for key, source in catalog.all_sources([]).items()}
    rows, more, per, reserved = [], [], Counter(), {}
    wanted = set(chosen)

    def waiting() -> bool:
        return len(reserved) < feed.FIRST_MAX and not wanted <= reserved.keys()

    for shaped, item in feed.ranked(library, events, now, topics, seed=int(now * 1000)):
        full = len(rows) >= 3 * feed.FIRST_MAX
        if shaped["seen"] or (full and not waiting()):
            break
        platform = carried[item.source] if item.source in carried else platforms.of_url(item.url)
        if not feed.presentable(shaped, bool(platform) and platforms.PLATFORMS[platform].kind == "video"):
            continue
        site = shaped["site"] or item.source
        if platform in wanted and platform not in reserved and waiting() and per[site] < feed.FIRST_PER_SOURCE:
            per[site] += 1
            reserved[platform] = (shaped, item)
        elif full:
            continue
        elif per[site] < feed.FIRST_PER_SOURCE:
            per[site] += 1
            rows.append((shaped, item))
        else:
            more.append((shaped, item))
    rows.sort(key=lambda row: not row[1].judged)
    kept = {item.id for _, item in reserved.values()}
    shown, room = [], feed.FIRST_MAX - len(kept)
    for row in _varied(feed.Veins(topics), [*reserved.values(), *rows]):
        if row[1].id in kept or room > 0:
            shown.append(row)
            room -= row[1].id not in kept
    return [shaped for shaped, _ in shown + more[:feed.FIRST_MAX - len(shown)]]

# ------------------------------------------------------------------ one run --


def spearman(a: list, b: list) -> float:
    def ranks(v):
        r = [0.0] * len(v)
        for n, i in enumerate(sorted(range(len(v)), key=v.__getitem__)):
            r[i] = n
        return r
    ra, rb = ranks(a), ranks(b)
    ma, mb = statistics.mean(ra), statistics.mean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
    return num / den if den else 0.0


def _as_dict(item: Item) -> dict:
    return {"id": item.id, "kind": item.kind, "length": item.length, "text": item.text,
            "description": item.description, "site": item.site, "source": item.source}


def _pool(runtime: Path, library: Library, topics: list[str]) -> dict:
    """Every unseen presentable thing's features and the picked topics it is on, by id."""
    reader, read = taste.Reader(runtime, topics, [], now=NOW), taste.readable(runtime)
    carried = {key: source.platform for key, source in catalog.all_sources([]).items()}
    out = {}
    for shaped, item in feed.ranked(library, [], NOW, topics, seed=0, picks=False):
        platform = carried[item.source] if item.source in carried else platforms.of_url(item.url)
        if feed.presentable(shaped, bool(platform) and platforms.PLATFORMS[platform].kind == "video"):
            snap = reader.snapshot(item, shaped, NOW)
            out[item.id] = {"x": taste.vector(snap, read), "topics": snap["topics"], "platform": platform}
    return out


def run(t, scen: str, seed: int, draws: int, work: Path) -> list[dict]:
    """Every method and answer draw on one person's library."""
    s = scenario(scen, t)
    # A path of its own for every runtime: taste keeps the fits it read by path (load_at).
    base = work / f"{t.name}-{scen}-{seed}"
    shutil.rmtree(base, ignore_errors=True)
    (base / "runtime").mkdir(parents=True)
    situation.set_value(base / "runtime", "readable", s["read"])
    labels = build(base / "runtime", s["lang"], s["topics"], s["platforms"],
                   random.Random(f"{t.name}:{scen}:{seed}"), s["thin"])
    if scen == "en":
        labels = {i: dict(lab, lang="other" if lab["lang"] == "zh" else lab["lang"]) for i, lab in labels.items()}
    topics, chosen = feed.load_topics(base / "runtime"), feed.load_platforms(base / "runtime")
    library = Library(base / "runtime")
    pool = _pool(base / "runtime", library, topics)
    # Both rounds are fixed by the library, so what either shows is left out of every method's measures.
    shown = {row["id"] for round_ in (old_round, feed.first_round) for row in round_(library, [], NOW, topics, chosen)}
    db.close(base / "runtime")
    out = []
    for draw in range(draws):
        for method in METHODS:
            home = work / f"{t.name}-{scen}-{seed}-{draw}-{method}"
            shutil.rmtree(home, ignore_errors=True)
            shutil.copytree(base, home)
            runtime = home / "runtime"
            out.append(_measure(t, scen, runtime, labels, pool, topics, chosen, method, seed, draw, shown)
                       | {"person": t.name, "scen": scen, "seed": seed, "draw": draw, "method": method})
            db.close(runtime)
            shutil.rmtree(home, ignore_errors=True)
    shutil.rmtree(base, ignore_errors=True)
    return out


def _measure(t, scen: str, runtime: Path, labels: dict, pool: dict, topics: list, chosen: list, method: str,
             seed: int, draw: int, either: set) -> dict:
    library = Library(runtime)
    who = (Fresh if t in FRESH else Person)(t, labels, seed * 100 + EVERYONE.index(t) + 7919 * draw)
    rng = random.Random(f"answers:{t.name}:{scen}:{seed}:{draw}")
    mute = getattr(t, "mute", False)
    rounds = {"old": old_round, "new": feed.first_round}
    shown = [library.get(row["id"]) for row in rounds[method](library, [], NOW, topics, chosen)] \
        if method in rounds else []
    for item in shown:
        like = rng.random() < who.worth(_as_dict(item), NOW, 0) and not mute
        who.shown.append((NOW, top(labels[item.id])))
        feed.remember(runtime, item, "seen", NOW, surface="first")
        if not mute:
            feed.remember(runtime, item, "like" if like else "skip", NOW, surface="first")
    fitted = taste.train(runtime, NOW + 1)
    events = feed.events(runtime)

    def worth(item: Item) -> float:
        return 1 / (1 + math.exp(-(4 * who.appeal(_as_dict(item), NOW, 0, context=False) - 1.0)))

    nxt = []
    for s in range(3):
        rows = [item for shaped, item in feed.ranked(library, events, NOW + 2, topics, seed=1000 + s)
                if item.id not in either][:20]
        nxt.append(statistics.mean(map(worth, rows)) if rows else 0.0)
    ids = {item.id for item in shown}
    prior, fit = (taste.Belief(m, taste.Priors(runtime)) for m in ({"m": {}, "q": {}}, fitted))
    rest = [(fit.chance(c["x"]), worth(library.get(i))) for i, c in pool.items() if i not in either]
    sites = [item.site for item in shown]
    have = set(chosen) & {c["platform"] for c in pool.values()}
    return {"n": len(shown), "next20": statistics.mean(nxt),
            "rho": spearman([p for (p, _), _ in rest], [w for _, w in rest]) if len(rest) > 2 else 0.0,
            "unc": statistics.mean(var for (_, var), _ in rest) if rest else 0.0,
            "worth": statistics.mean(map(worth, shown)) if shown else None,
            "topics": statistics.mean(any(tp.casefold() in pool.get(i, {}).get("topics", ()) for i in ids)
                                      for tp in topics) if topics and shown else None,
            "platforms": statistics.mean(any(pool.get(i, {}).get("platform") == p for i in ids) for p in have)
            if shown and have else None,
            "subjects": len({top(labels[i]) for i in ids}) if shown else None,
            "prior_p": statistics.mean(prior.chance(pool[i]["x"])[0] for i in ids if i in pool) if shown else None,
            "twice": sum(a == b for a, b in pairwise(sites)) if shown else None}

# ------------------------------------------------------------------- report --


def report(rows: list[dict]) -> None:
    by = defaultdict(dict)
    for r in rows:
        by[(r["scen"], r["person"], r["seed"], r["draw"])][r["method"]] = r
    for scen in dict.fromkeys(r["scen"] for r in rows):
        sets = [d for k, d in by.items() if k[0] == scen]
        print(f"\n{scen}: {len(sets)} paired sets")
        print("".ljust(10) + "".join(m.rjust(25) for m in METHODS))
        for key in MEASURES:
            line = key.ljust(10)
            for m in METHODS:
                vals = [d[m][key] for d in sets if d[m][key] is not None]
                diffs = [d[m][key] - d["old"][key] for d in sets if d[m][key] is not None and d["old"][key] is not None]
                if not vals:
                    line += "-".rjust(25)
                elif m == "old" or len(diffs) < 2:
                    line += f"{statistics.mean(vals):.3f}".rjust(25)
                else:
                    se = statistics.stdev(diffs) / math.sqrt(len(diffs))
                    line += f"{statistics.mean(vals):.3f} ({statistics.mean(diffs):+.3f} se {se:.3f})".rjust(25)
            print(line)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--seeds", type=int, default=3)
    parser.add_argument("--first", type=int, default=0)
    parser.add_argument("--draws", type=int, default=2)
    parser.add_argument("--scenarios", default="base")
    parser.add_argument("--people", default="")
    args = parser.parse_args()
    # The fit runs here when the measure asks, not in a worker thread.
    taste.fit = lambda runtime, soon=False: None
    who = [t for t in EVERYONE if not args.people or t.name in args.people.split(",")]
    rows = []
    for seed in range(args.first, args.first + args.seeds):
        for scen in args.scenarios.split(","):
            for t in who:
                if scen != "en" or t.english:
                    rows += run(t, scen, seed, args.draws, args.work)
                    print(seed, scen, t.name, file=sys.stderr, flush=True)
    report(rows)


if __name__ == "__main__":
    main()
