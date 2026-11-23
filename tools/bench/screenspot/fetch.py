"""Fetch ScreenSpot-v2 (desktop + web only) and a small ScreenSpot-Pro sample into a data folder outside the repo.

    python fetch.py <data dir> [--pro 48]

ScreenSpot-v2 (OS-Copilot/ScreenSpot-v2 on Hugging Face, Apache-2.0) ships one 1.3 GB zip that also holds the
mobile screenshots; only the desktop and web members are read out of it, by HTTP range requests, so the zip
itself never lands on disk. ScreenSpot-Pro (likaixin/ScreenSpot-Pro, MIT): the annotation files and the images
of a stratified sample (by application, text/icon). The files are read as data only.
Then sample.py picks the items each run uses."""
from __future__ import annotations

import argparse
import io
import json
import random
import zipfile
from pathlib import Path

import httpx

V2 = "https://huggingface.co/datasets/OS-Copilot/ScreenSpot-v2/resolve/5efbb1f1b5463a575f2eb7bc30fe29e49c15f93c/"
PRO = "https://huggingface.co/datasets/likaixin/ScreenSpot-Pro/resolve/210e78d3844251110bff86c95835ebd37a6930fa/"
PRO_API = "https://huggingface.co/api/datasets/likaixin/ScreenSpot-Pro/revision/210e78d3844251110bff86c95835ebd37a6930fa"


class Remote(io.RawIOBase):
    """A read-only, seekable view of a remote file, by Range requests."""

    def __init__(self, cl, url):
        r = cl.head(url, follow_redirects=True)
        self.cl, self.url, self.size, self.pos = cl, str(r.url), int(r.headers["content-length"]), 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else self.pos + off if whence == 1 else self.size + off
        return self.pos

    def readinto(self, b):
        if self.pos >= self.size:
            return 0
        end = min(self.pos + len(b), self.size) - 1
        data = self.cl.get(self.url, headers={"Range": f"bytes={self.pos}-{end}"}).content
        b[:len(data)] = data
        self.pos += len(data)
        return len(data)


def get(cl, url, dest):
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    r = cl.get(url, follow_redirects=True)
    r.raise_for_status()
    dest.write_bytes(r.content)
    return dest


def v2(cl, root):
    d = root / "v2"
    (d / "img").mkdir(parents=True, exist_ok=True)
    need = set()
    for part in ("desktop", "web"):
        f = get(cl, V2 + f"screenspot_{part}_v2.json", d / f"screenspot_{part}_v2.json")
        need |= {x["img_filename"] for x in json.loads(f.read_text(encoding="utf-8"))}
    need = {n for n in need if not (d / "img" / n).exists()}
    print("v2:", len(need), "images to fetch")
    if not need:
        return
    z = zipfile.ZipFile(io.BufferedReader(Remote(cl, V2 + "screenspotv2_image.zip"), buffer_size=1 << 20))
    for info in z.infolist():
        name = info.filename.rsplit("/", 1)[-1]
        if name in need:
            (d / "img" / name).write_bytes(z.read(info))
            need.discard(name)
    print("v2: missing from zip:", sorted(need))


def pro(cl, root, n):
    d = root / "pro"
    files = [s["rfilename"] for s in cl.get(PRO_API).json()["siblings"]]
    items = []
    for f in sorted(x for x in files if x.startswith("annotations/")):
        items += json.loads(get(cl, PRO + f, d / f).read_text(encoding="utf-8"))
    rng = random.Random(7)
    by = {}
    for it in items:
        by.setdefault((it["application"], it["ui_type"]), []).append(it)
    keys = sorted(by)
    rng.shuffle(keys)
    pick = [rng.choice(by[k]) for k in keys[:n]]
    for it in pick:
        get(cl, PRO + "images/" + it["img_filename"], d / "images" / it["img_filename"])
    (d / "sample.json").write_text(json.dumps(pick, ensure_ascii=False, indent=1), encoding="utf-8")
    print("pro:", len(pick), "items,", len({p["img_filename"] for p in pick}), "images")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data", type=Path)
    ap.add_argument("--pro", type=int, default=48, help="ScreenSpot-Pro items: one per (application, text/icon) pair")
    a = ap.parse_args()
    a.data.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=120, headers={"User-Agent": "bench-fetch"}) as cl:
        v2(cl, a.data)
        if a.pro:
            pro(cl, a.data, a.pro)


if __name__ == "__main__":
    main()
