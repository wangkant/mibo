"""Cut the pet's figure sheets from the painters' pictures.

    python tools/figure_sheet.py <art> [key ...]

<art>/<key>/ holds base.png (the figure, full body, on one flat ground),
blink.png, talk.png and look.png (the same picture with only the face
changed) and meta.json ({"ground": "#rrggbb", "face": [x, y, w, h]}).

Writes persona_agent/static/welcome/figures/<key>.webp for each key named
(all of them when none is): four frames side by side, rest, blink, talk and
look, 320x380 each and shown at 160x190. Also writes <art>/gallery.png, the
rest frames side by side, to look at. The characters are scaled as one set,
so every folder under <art> is read whichever keys are named.

The pet's window blends with the desktop (window.py), so a figure keeps the
painting's own soft edge: no outline is drawn round it.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import (
    Image,
    ImageChops,
    ImageDraw,
    ImageFilter,
    ImageFont,
    ImageMath,
    ImageStat,
)

FIGURES = Path(__file__).resolve().parents[1] / "persona_agent" / "static" / "welcome" / "figures"
FACES = ("blink", "talk", "look")
FRAME = (320, 380)
# Sheet pixels. Shown at half size: feet 10 px above the frame's bottom, a
# ring 2.5 px wide, and a few pixels between the ring and the frame's edge.
FEET = 360
SPARE = 6
# A frame is put together at this many times the sheet's size and then cut to it.
FINE = 2
# Painting pixels: the faces fade in over this much of their box's edge, and
# a face is looked for this far from where its box says.
FEATHER = 12
NUDGE = 4
# Of the painting's height, the part at the feet whose middle is the body's.
STANCE = 0.3
# A figure whose head would leave it below this share of the frame's height
# is let grow past the others' head size: a tiny pet reads as nothing.
LEAST_FILL = 0.86


def edge_of(picture: Image.Image) -> Image.Image:
    """A mask of the picture's outer 8 pixels, which are all ground."""
    w, h = picture.size
    edge = Image.new("L", picture.size, 255)
    ImageDraw.Draw(edge).rectangle((8, 8, w - 9, h - 9), fill=0)
    return edge


def ground_of(picture: Image.Image) -> tuple[int, ...]:
    """The ground's colour, as its middle value along the picture's edges."""
    return tuple(int(v) for v in ImageStat.Stat(picture, edge_of(picture)).median)


def tint_of(bands: list[Image.Image], ground: tuple[int, ...]) -> Image.Image:
    """How strongly each pixel has the ground's hue: its weakest strong channel
    over its strongest weak one. Green ground: green over red and blue."""
    strong = [b for b, g in zip(bands, ground) if g > 127]
    weak = [b for b, g in zip(bands, ground) if g <= 127]
    least = strong[0] if len(strong) == 1 else ImageChops.darker(*strong)
    most = weak[0] if len(weak) == 1 else ImageChops.lighter(*weak)
    return ImageChops.subtract(least, most)


def key_out(picture: Image.Image) -> Image.Image:
    """The figure as premultiplied RGBa, the ground taken out."""
    ground = ground_of(picture)
    bands = list(picture.split())
    tint = tint_of(bands, ground)
    full = ImageStat.Stat(tint, edge_of(picture)).median[0]
    # The ground is even to within a few levels; everything between it and a
    # fifth of its hue is the painting's own soft edge against it.
    clear, solid = full - 18, full * 0.2
    soft = tint.point([round(255 * min(1, max(0, (clear - v) / (clear - solid)))) for v in range(256)])
    # Any ground-coloured pixel is ground, by the edge or shut in by hair or
    # an arm, down to a slit between two locks that is only part ground. The
    # soft edge only counts next to such pixels, so a dull green leaf inside
    # her stays whole.
    near = tint.point(lambda v: 255 if v > full * 0.25 else 0).filter(ImageFilter.MaxFilter(7))
    alpha = ImageChops.lighter(soft, ImageChops.invert(near))
    # Take the ground's share out of each pixel, then the hue it left in the
    # painted edge: the strong channels come down to the weak ones there.
    keep = [
        ImageMath.lambda_eval(lambda e, g=g: e["p"] - (255 - e["a"]) * g / 255, p=band, a=alpha).convert("L")
        for band, g in zip(bands, ground)
    ]
    spill = ImageChops.multiply(tint_of(keep, ground), near)
    keep = [ImageChops.subtract(b, spill) if g > 127 else b for b, g in zip(keep, ground)]
    keep = [ImageChops.darker(b, alpha) for b in keep]
    return Image.merge("RGBa", (*keep, alpha))


def ramp(size: tuple[int, int], box: tuple[int, int, int, int]) -> Image.Image:
    """A mask that is the box, rising from nothing at its edge to full FEATHER in."""
    mask = Image.new("L", size, 0)
    pen = ImageDraw.Draw(mask)
    x, y, w, h = box
    for i in range(FEATHER + 1):
        pen.rectangle((x + i, y + i, x + w - 1 - i, y + h - 1 - i), fill=round(255 * i / FEATHER))
    return mask


def nudge(base: Image.Image, other: Image.Image, box: tuple[int, int, int, int]) -> tuple[int, int, float]:
    """The whole-pixel shift that best lays <other> on <base> around the face box,
    and how far apart they still are there (mean level)."""
    x, y, w, h = box
    pad = 40
    area = (max(0, x - pad), max(0, y - pad), min(base.width, x + w + pad), min(base.height, y + h + pad))
    band = Image.new("L", (area[2] - area[0], area[3] - area[1]), 255)
    ImageDraw.Draw(band).rectangle((x - area[0], y - area[1], x - area[0] + w - 1, y - area[1] + h - 1), fill=0)
    near = base.crop(area)
    best = None
    for dy in range(-NUDGE, NUDGE + 1):
        for dx in range(-NUDGE, NUDGE + 1):
            moved = other.crop((area[0] - dx, area[1] - dy, area[2] - dx, area[3] - dy))
            off = ImageStat.Stat(ImageChops.difference(near, moved).convert("L"), band).mean[0]
            if best is None or off < best[2]:
                best = (dx, dy, off)
    return best


class Figure:
    def __init__(self, folder: Path) -> None:
        self.key = folder.name
        meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
        box = tuple(meta["face"])
        base = Image.open(folder / "base.png").convert("RGB")
        self.frames = [base]
        self.report = []
        for name in FACES:
            other = Image.open(folder / f"{name}.png").convert("RGB")
            dx, dy, off = nudge(base, other, box)
            moved = ImageChops.offset(other, dx, dy)
            self.frames.append(Image.composite(moved, base, ramp(base.size, box)))
            self.report.append(f"{name} {dx:+d},{dy:+d} (left {off:.1f})")
        self.cut = [key_out(frame) for frame in self.frames]
        solid = self.cut[0].getchannel("a").point(lambda v: 255 if v > 127 else 0)
        self.bbox = solid.getbbox()
        _, y0, _, y1 = self.bbox
        # The body's middle is the middle of what stands on the feet, which a
        # tail or a wing higher up does not reach.
        stance = solid.crop((0, round(y1 - (y1 - y0) * STANCE), solid.width, y1))
        cover = stance.resize((solid.width, 1), Image.Resampling.BOX).tobytes()
        self.middle = sum(i * c for i, c in enumerate(cover)) / sum(cover) + 0.5
        # Head size: the span of the eyes, which is what the blink changes. A
        # redrawn face also moves thin strands of hair; thinning drops those.
        shut = ImageChops.difference(self.frames[0], self.frames[1]).convert("L")
        eyes = shut.point(lambda v: 255 if v > 40 else 0).filter(ImageFilter.MinFilter(9)).getbbox()
        self.eyes = eyes[2] - eyes[0]

    def fit(self) -> float:
        """The largest scale, sheet pixels to painting pixels, that keeps it in the frame."""
        x0, y0, x1, y1 = self.bbox
        room = FRAME[0] / 2 - SPARE
        return min((FEET - SPARE) / (y1 - y0), room / (self.middle - x0), room / (x1 - self.middle))

    def frame(self, index: int, scale: float) -> Image.Image:
        cut = self.cut[index]
        x0, y0, x1, y1 = self.bbox
        fine = scale * FINE
        crop = cut.crop((x0 - 4, y0 - 4, x1 + 4, y1 + 4))
        crop = crop.resize((round(crop.width * fine), round(crop.height * fine)), Image.Resampling.LANCZOS)
        size = (FRAME[0] * FINE, FRAME[1] * FINE)
        canvas = Image.new("RGBa", size, (0, 0, 0, 0))
        canvas.paste(crop, (round(size[0] / 2 - (self.middle - x0 + 4) * fine), round(FEET * FINE - (y1 - y0 + 4) * fine)))
        # Cut down while premultiplied, so the soft edge keeps its own colour.
        return canvas.resize(FRAME, Image.Resampling.BOX).convert("RGBA")

    def sheet(self, scale: float) -> Image.Image:
        sheet = Image.new("RGBA", (FRAME[0] * 4, FRAME[1]))
        for i in range(4):
            sheet.paste(self.frame(i, scale), (FRAME[0] * i, 0))
        return sheet


def scales(figures: list[Figure]) -> dict[str, float]:
    """One head size for the set, as large as the frame lets the tightest one be."""
    head = min(f.fit() * f.eyes for f in figures)
    return {f.key: max(head / f.eyes, f.fit() * LEAST_FILL) for f in figures}


def gallery(sheets: dict[str, Image.Image], out: Path) -> None:
    w, h = FRAME[0] * 2, FRAME[1] * 2
    board = Image.new("RGB", (w * len(sheets), h + 70), (232, 230, 226))
    pen = ImageDraw.Draw(board)
    font = ImageFont.load_default(size=30)
    for i, (key, sheet) in enumerate(sheets.items()):
        rest = sheet.crop((0, 0, *FRAME)).resize((w, h), Image.Resampling.NEAREST)
        board.paste(rest, (w * i, 0), rest)
        pen.text((w * i + w / 2, h + 32), key, fill=(60, 60, 60), font=font, anchor="mm")
    board.save(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("art", type=Path)
    parser.add_argument("keys", nargs="*")
    args = parser.parse_args()
    figures = [Figure(folder) for folder in sorted(args.art.iterdir()) if (folder / "meta.json").is_file()]
    scale = scales(figures)
    sheets = {}
    for f in figures:
        _, y0, _, y1 = f.bbox
        s = scale[f.key]
        print(f"{f.key}: eyes {f.eyes}px, scale {s:.4f} (fits {f.fit():.4f}), "
              f"{(y1 - y0) * s / 2:.0f}px tall shown, faces {'; '.join(f.report)}")
        sheets[f.key] = f.sheet(s)
        if not args.keys or f.key in args.keys:
            sheets[f.key].save(FIGURES / f"{f.key}.webp", lossless=True, quality=100, method=6)
    gallery(sheets, args.art / "gallery.png")


if __name__ == "__main__":
    main()
