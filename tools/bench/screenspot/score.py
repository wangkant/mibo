"""Score answers.jsonl: a point is right when it lies inside the true box.

    python score.py <data dir> <out dir>

Prints and writes <out dir>/report.md and report.json: accuracy by model and pass (first look / after the crop),
by desktop or web, text or icon, target size (the box's area as a share of the screenshot, ScreenSpot-Pro's
measure), what the crop rescued and broke, unparsed answers, and cost per thousand looks."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from PIL import Image  # noqa: E402

SIZE_BINS = [(0, 0.001, "<0.1%"), (0.001, 0.003, "0.1-0.3%"), (0.003, 0.01, "0.3-1%"), (0.01, 1, ">=1%")]
_sizes = {}


def hit(pt, box):
    return pt is not None and box[0] <= pt[0] <= box[2] and box[1] <= pt[1] <= box[3]


def acc(rows, items):
    by = {it["id"]: it for it in items}
    rows = [r for r in rows if r["id"] in by]
    return sum(hit(r.get("pt"), by[r["id"]]["box"]) for r in rows) / len(rows) if rows else 0.0


def area_share(it):
    if it["img"] not in _sizes:
        _sizes[it["img"]] = Image.open(it["img"]).size
    W, H = _sizes[it["img"]]
    b = it["box"]
    return (b[2] - b[0]) * (b[3] - b[1]) / (W * H)


def size_bin(it):
    s = area_share(it)
    return next(lab for lo, hi, lab in SIZE_BINS if lo <= s < hi)


def ci(k, n):
    """Wilson 95% interval, in percent."""
    if not n:
        return (0, 0)
    p, z = k / n, 1.96
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (100 * (c - h), 100 * (c + h))


def main():
    import bench
    data, out = Path(sys.argv[1]), Path(sys.argv[2])
    rows = [r for r in bench.load(out / "answers.jsonl") if "error" not in r]
    ways = json.loads((out / "ways.json").read_text()) if (out / "ways.json").exists() else {}
    items = {it["id"]: it for it in bench.items_v2(data) + bench.items_pro(data)}
    main_ids = [it["id"] for it in bench.sample(data, 150)]
    models = sorted({r["model"] for r in rows})
    look = {(r["model"], r["mode"], r["id"], r["way"]): r for r in rows}
    rep, md = {"ways": ways, "models": {}}, []

    md.append("## Probe (20 items, both conventions)\n\n| model | px | 0-1000 | kept |\n|---|---|---|---|")
    pids = [it["id"] for it in bench.probe_set(data)]
    for m in models:
        a = {w: sum(hit((look.get((m, "probe", i, w)) or {}).get("pt"), items[i]["box"]) for i in pids) for w in ("px", "k")}
        md.append(f"| {m} | {a['px']}/20 | {a['k']}/20 | {ways.get(m, '')} |")

    def cell(ids, m, mode):
        rs = [look.get((m, mode, i, ways.get(m))) for i in ids]
        rs = [(r, items[i]) for r, i in zip(rs, ids) if r]
        k = sum(hit(r.get("pt"), it["box"]) for r, it in rs)
        return k, len(rs)

    def fmt(k, n):
        if not n:
            return "-"
        lo, hi = ci(k, n)
        return f"{100 * k / n:.1f} ({lo:.0f}-{hi:.0f}) n={n}"

    groups = {"all": main_ids}
    for part in ("desktop", "web"):
        groups[part] = [i for i in main_ids if items[i]["part"] == part]
        for typ in ("text", "icon"):
            groups[f"{part} {typ}"] = [i for i in groups[part] if items[i]["type"] == typ]
    for *_, lab in SIZE_BINS:
        groups[f"size {lab}"] = [i for i in main_ids if size_bin(items[i]) == lab]
    pro_ids = [it["id"] for it in bench.items_pro(data)]
    groups["pro (sample)"] = pro_ids
    for typ in ("text", "icon"):
        groups[f"pro {typ}"] = [i for i in pro_ids if items[i]["type"] == typ]

    md.append("\n## Accuracy of the first look, % (95% Wilson interval)\n")
    md.append("| group | " + " | ".join(models) + " |\n|---|" + "---|" * len(models))
    for g, ids in groups.items():
        cells = []
        for m in models:
            k, n = cell(ids, m, "pro" if g.startswith("pro") else "main")
            cells.append(fmt(k, n))
            rep["models"].setdefault(m, {})[g] = [k, n]
        md.append(f"| {g} | " + " | ".join(cells) + " |")

    check = bench.check_ids(data)
    md.append("\n## The crop pass\n\nRescued: first-look misses the crop got right (asked on every miss). Check subset: every 5th "
              "main item (60), asked whatever the first look did: before/after accuracy there and what the crop broke. "
              "Estimated after-crop accuracy on all 300 = (first-look hits x (1 - broken share of subset hits) + rescued) / 300.\n")
    md.append("| model | misses | rescued | subset before | subset after | subset broken | est. all-300 after, % |\n|---|---|---|---|---|---|---|")
    for m in models:
        w = ways.get(m)
        miss = resc = h1s = h2s = brk = n = hits = 0
        for i in main_ids:
            f, c = look.get((m, "main", i, w)), look.get((m, "crop", i, w))
            if not f:
                continue
            h1 = hit(f.get("pt"), items[i]["box"])
            hits += h1
            h2 = c is not None and hit(c.get("pt"), items[i]["box"])
            if not h1:
                miss += 1
                resc += h2
            if i in check and c is not None:
                n += 1
                h1s += h1
                h2s += h2
                brk += h1 and not h2
        est = (hits * (1 - (brk / h1s if h1s else 0)) + resc) / len(main_ids)
        md.append(f"| {m} | {miss} | {resc} | {h1s}/{n} | {h2s}/{n} | {brk} | {100 * est:.1f} |")
        rep["models"][m]["crop_pass"] = {"misses": miss, "rescued": resc, "subset": [h1s, h2s, n], "broken": brk, "est_after": est}

    md.append("\n## Cost and answers\n\n| model | mode | looks | unparsed | mean prompt tokens | $ per 1000 looks |\n|---|---|---|---|---|---|")
    for m in models:
        for mode in ("probe", "main", "crop", "pro"):
            rs = [r for r in rows if r["model"] == m and r["mode"] == mode]
            if not rs:
                continue
            cost = sum(r.get("cost") or 0 for r in rs)
            un = sum(r.get("pt") is None for r in rs)
            mean_pt = sum(r["ptk"] for r in rs if r.get("ptk")) / max(1, sum(1 for r in rs if r.get("ptk")))
            md.append(f"| {m} | {mode} | {len(rs)} | {un} | {mean_pt:.0f} | {1000 * cost / len(rs):.3f} |")
            rep["models"][m][f"cost_{mode}"] = {"looks": len(rs), "dollars": cost, "unparsed": un}
    text = "\n".join(md)
    (out / "report.md").write_text(text, encoding="utf-8")
    (out / "report.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
