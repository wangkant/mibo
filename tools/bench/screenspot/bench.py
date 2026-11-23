"""ScreenSpot pointing benchmark: picture-reading models through an OpenAI-compatible endpoint (OpenRouter).

    python bench.py <data dir> <out dir> probe  MODELS [--cap 0.05]
    python bench.py <data dir> <out dir> main   MODELS [--cap 0.30] [--n 150]
    python bench.py <data dir> <out dir> crop   MODELS [--cap 0.30]
    python bench.py <data dir> <out dir> pro    MODELS [--cap 0.05]
    python bench.py <data dir> <out dir> spend

<data dir> is what fetch.py filled. <out dir> holds .env (LLM_API_KEY, LLM_BASE_URL; read, never printed),
answers.jsonl (one line per look: model, mode, item, convention, answer text, point, cost; never the key) and
ways.json (the convention kept per model after the probe). Runs resume: a look already answered is not asked again.
MODELS is a comma list of model ids.

probe: 20 items (10 desktop, 10 web, half icons) asked two ways, plain pixels (px) and 0-1000 normalised (k);
       the better way per model is written to ways.json (ties go to k).
main:  --n desktop and --n web items, the same for every model, text and icon balanced, stratified by source;
       asked the kept way.
crop:  the second look, asked on every first-look miss (what it rescues) and on every item of the check subset
       (every 5th main item, 30 desktop + 30 web: what it breaks and the before/after accuracy): a crop round the main answer (30% of the screen each way, centred on the first point,
       shown enlarged to 1280 px wide), asked the same way; the new point is mapped back to the full screenshot.
pro:   the ScreenSpot-Pro sample fetch.py chose, asked the kept way (the full screenshot, as main does).
--cap: stop asking once this run's summed cost (from the endpoint's own usage.cost) passes this many dollars.
Scoring (score.py): a point is right when it lies inside the true box, as ScreenSpot scores it."""
from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import random
import re
import sys
from pathlib import Path

import httpx
from PIL import Image

CFG = {  # reasoning off where the model allows it; provider pins carried over from the in-house pointing study
    "qwen/qwen3.7-flash": {"reasoning": {"effort": "none"}},
    "deepseek/deepseek-v4.1-flash": {"reasoning": {"effort": "none"}, "provider": {"order": ["ionstream", "deepinfra/fp8"], "allow_fallbacks": False}},
    "z-ai/glm-5.3-flash": {"reasoning": {"effort": "minimal"}, "max_tokens": 2000, "provider": {"order": ["novita/fp8", "z-ai/fp8"], "allow_fallbacks": False}},
    "openai/gpt-6-luna": {"reasoning": {"effort": "none"}},
}
ASK = {
    "px": "This screenshot is {W} pixels wide and {H} pixels tall. Where should I click for: {d}?\n"
          "Answer only with the point as x,y in pixels of this image, for example 512,300.",
    "k": "Where should I click in this screenshot for: {d}?\n"
         "Answer only with the point as x,y in coordinates normalised to 0-1000 (0,0 is the top-left corner, "
         "1000,1000 the bottom-right), for example 412,377.",
}
CROP_NOTE = "This is an enlarged close-up of part of a screen. If the thing is not in this close-up, give your best guess at the edge nearest to it.\n"
CROP_FRAC, CROP_W = 0.30, 1280


def env(out):
    e = dict(line.split("=", 1) for line in (out / ".env").read_text(encoding="utf-8").splitlines() if "=" in line)
    return e["LLM_API_KEY"].strip().strip('"'), e.get("LLM_BASE_URL", "https://openrouter.ai/api/v1").strip().strip('"').rstrip("/")


def items_v2(data):
    out = []
    for part in ("desktop", "web"):
        for i, x in enumerate(json.loads((data / "v2" / f"screenspot_{part}_v2.json").read_text(encoding="utf-8"))):
            bx, by, bw, bh = x["bbox"]
            out.append({"id": f"{part}-{i}", "part": part, "type": x["data_type"], "source": x["data_source"],
                        "img": str(data / "v2" / "img" / x["img_filename"]), "box": [bx, by, bx + bw, by + bh], "d": x["instruction"]})
    return out


def items_pro(data):
    return [{"id": x["id"], "part": "pro", "type": x["ui_type"], "source": x["application"], "group": x["group"],
             "img": str(data / "pro" / "images" / x["img_filename"]), "box": x["bbox"], "d": x["instruction"]}
            for x in json.loads((data / "pro" / "sample.json").read_text(encoding="utf-8"))]


def stratified(pool, n, rng):
    """n items, half text half icon, each half spread over sources in proportion to their counts."""
    pick = []
    for typ, k in (("text", n - n // 2), ("icon", n // 2)):
        sub = [x for x in pool if x["type"] == typ]
        by = {}
        for x in sub:
            by.setdefault(x["source"], []).append(x)
        quota = {s: k * len(v) // len(sub) for s, v in by.items()}
        for s in sorted(by, key=lambda s: -len(by[s]))[: k - sum(quota.values())]:
            quota[s] += 1
        for s in sorted(by):
            pick += rng.sample(by[s], min(quota[s], len(by[s])))
    return pick


def sample(data, n):
    rng, allv = random.Random(2026), items_v2(data)
    return [x for part in ("desktop", "web") for x in stratified([y for y in allv if y["part"] == part], n, rng)]


def check_ids(data):
    s = sample(data, 150)
    return {x["id"] for part in ("desktop", "web") for x in [y for y in s if y["part"] == part][::5]}


def probe_set(data):
    rng, allv = random.Random(11), items_v2(data)
    main = {x["id"] for x in sample(data, 150)}
    return [x for part in ("desktop", "web") for x in stratified([y for y in allv if y["part"] == part and y["id"] not in main], 10, rng)]


def png(im):
    b = io.BytesIO()
    im.save(b, "PNG")
    return "data:image/png;base64," + base64.b64encode(b.getvalue()).decode()


def crop_view(im, pt):
    W, H = im.size
    cw, ch = int(W * CROP_FRAC), int(H * CROP_FRAC)
    x0 = int(min(max(pt[0] - cw / 2, 0), W - cw))
    y0 = int(min(max(pt[1] - ch / 2, 0), H - ch))
    k = CROP_W / cw
    return im.crop((x0, y0, x0 + cw, y0 + ch)).resize((CROP_W, round(ch * k)), Image.LANCZOS), (x0, y0, k)


def parse(text):
    n = [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", re.sub(r"<think>.*?</think>", "", text or "", flags=re.S))]
    return n[:2] if len(n) >= 2 else None


def to_px(way, xy, size):
    return [xy[0] * size[0] / 1000, xy[1] * size[1] / 1000] if way == "k" else list(xy)


async def call(cl, key, base, model, prompt, url):
    extra = CFG.get(model, {})
    body = {"model": model, "temperature": 0, "max_tokens": extra.get("max_tokens", 300), "usage": {"include": True},
            "messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": url}}, {"type": "text", "text": prompt}]}]}
    body.update({k: v for k, v in extra.items() if k != "max_tokens"})
    err = None
    for attempt in range(4):
        try:
            r = await cl.post(base + "/chat/completions", json=body, headers={"Authorization": f"Bearer {key}"}, timeout=180)
            j = r.json()
            if "choices" in j:
                u = j.get("usage") or {}
                return {"text": j["choices"][0]["message"].get("content") or "", "cost": u.get("cost") or 0,
                        "ptk": u.get("prompt_tokens"), "ctk": u.get("completion_tokens"), "prov": j.get("provider")}
            err = str(j.get("error", j))[:300]
            if r.status_code in (400, 401, 402, 404):
                break
        except Exception as e:
            err = repr(e)[:200]
        await asyncio.sleep(4 * (attempt + 1))
    return {"error": err, "cost": 0}


def load(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


async def run(a):
    key, base = env(a.out)
    ans = a.out / "answers.jsonl"
    rows = load(ans)
    have = {(r["model"], r["mode"], r["id"], r["way"]) for r in rows if "error" not in r}
    ways = json.loads((a.out / "ways.json").read_text()) if (a.out / "ways.json").exists() else {}
    first = {(r["model"], r["id"]): r for r in rows if r["mode"] == "main" and "error" not in r}
    if a.mode == "probe":
        items, plan = probe_set(a.data), lambda m: ["px", "k"]
    elif a.mode == "pro":
        items, plan = items_pro(a.data), lambda m: [ways[m]]
    else:
        items, plan = sample(a.data, a.n), lambda m: [ways[m]]
    spent, lock, imgs = [0.0], asyncio.Lock(), {}
    import score
    check = check_ids(a.data)

    def image(p):
        if p not in imgs:
            imgs[p] = Image.open(p).convert("RGB")
        return imgs[p]

    async def one(cl, sem, m, it, way):
        im = image(it["img"])
        meta = {}
        if a.mode == "crop":
            f = first.get((m, it["id"]))
            if not f or f.get("pt") is None:
                return
            if it["id"] not in check and score.hit(f["pt"], it["box"]):
                return
            im, (x0, y0, k) = crop_view(im, f["pt"])
            meta = {"crop": [x0, y0, k], "first": f["pt"]}
        W, H = im.size
        prompt = (CROP_NOTE if a.mode == "crop" else "") + ASK[way].format(W=W, H=H, d=it["d"])
        async with sem:
            if spent[0] > a.cap:
                return
            r = await call(cl, key, base, m, prompt, png(im))
        xy = parse(r.get("text"))
        pt = to_px(way, xy, (W, H)) if xy else None
        if pt and a.mode == "crop":
            pt = [meta["crop"][0] + pt[0] / meta["crop"][2], meta["crop"][1] + pt[1] / meta["crop"][2]]
        r.update({"model": m, "mode": a.mode, "id": it["id"], "way": way, "pt": pt, **meta})
        async with lock:
            spent[0] += r.get("cost") or 0
            with ans.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    jobs = []
    async with httpx.AsyncClient(limits=httpx.Limits(max_connections=48)) as cl:
        for m in a.models:
            sem = asyncio.Semaphore(8)
            jobs += [one(cl, sem, m, it, w) for it in items for w in plan(m) if (m, a.mode, it["id"], w) not in have]
        print(len(jobs), "looks to ask")
        await asyncio.gather(*jobs)
    print(f"this run cost ${spent[0]:.4f}" + ("  (stopped at the cap)" if spent[0] > a.cap else ""))
    if a.mode == "probe":
        for m in a.models:
            acc = {w: score.acc([r for r in load(ans) if r["model"] == m and r["mode"] == "probe" and r["way"] == w and "error" not in r], items) for w in ("px", "k")}
            ways[m] = "px" if acc["px"] > acc["k"] else "k"
            print(m, f"probe accuracy px {acc['px']:.2f}  k {acc['k']:.2f}  -> {ways[m]}")
        (a.out / "ways.json").write_text(json.dumps(ways, indent=1))


def spend(out):
    key, base = env(out)
    d = httpx.get(base + "/key", headers={"Authorization": f"Bearer {key}"}, timeout=30).json()["data"]
    print(json.dumps({k: d.get(k) for k in ("usage", "limit", "limit_remaining")}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("mode", choices=["probe", "main", "crop", "pro", "spend"])
    ap.add_argument("models", nargs="?", default="")
    ap.add_argument("--cap", type=float, default=0.05)
    ap.add_argument("--n", type=int, default=150)
    a = ap.parse_args()
    a.models = [m for m in a.models.split(",") if m]
    if a.mode == "spend":
        spend(a.out)
    else:
        asyncio.run(run(a))


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    main()
