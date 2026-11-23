"""Cut the pet's figure sheets from the painters' pictures.

    python tools/figure_sheet.py <art> [key ...]

<art>/<key>/ holds base.png (the figure, full body, on one flat ground),
blink.png, talk.png and look.png (the same picture with only the face
changed) and meta.json ({"ground": "#rrggbb", "face": [x, y, w, h]}).

Writes mibo/static/welcome/figures/<key>.webp for each key named
(all of them when none is): four frames side by side, rest, blink, talk and
look, 320x380 each and shown at 160x190. Also writes <art>/gallery.png, the
rest frames side by side, to look at. The characters are scaled as one set,
so every folder under <art> is read whichever keys are named.

A key with painted poses (<art>/<key>/frames/<name>.png and frames/meta.json)
also gets the pet's frames (pet.js): <key>.pet.webp, every pose trimmed to
what is in it and packed into one picture, and <key>.pet.json, where each is
in that picture and where it goes in the pet's window, with what the page
needs to know of it. One picture, so the page asks for one file and decodes
it once; trimmed, so it is mostly figure. A pose that changes only the face
(blink, talk, talk2, look, and peek's) is kept as its face box alone, drawn
over the pose it is on: everything else is that pose's own pixels, so the two
swap without the picture boiling.

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

FIGURES = Path(__file__).resolve().parents[1] / "mibo" / "static" / "welcome" / "figures"
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
        self.folder = folder
        meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
        box = tuple(meta["face"])
        self.face = box
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


# ---- the pet's frames. The window is CELL CSS px, the figure's box in it at
# BOX_AT; the frames are kept at the sheet's size, twice the CSS px.
POSES = (
    "rest", "idle2", "blink", "talk", "talk2", "look", "look_left", "look_right",
    "walk1", "walk2", "walk3", "walk4", "turn", "crouch", "air", "land", "held", "held2", "dizzy",
    "surprised", "wave1", "wave2", "give", "doze", "asleep", "peek", "peek_blink", "peek_talk", "peek_look",
)
# Poses that change only the face, and the pose each is drawn over.
ON = {"blink": "rest", "talk": "rest", "talk2": "rest", "look": "rest",
      "peek_blink": "peek", "peek_talk": "peek", "peek_look": "peek"}
# Off the ground as painted, so kept where the painting has them. The others
# stand on the feet line, and the peek ones go where their face is on base's.
AIRBORNE = {"air", "held", "held2"}
CELL = (200, 214)
BOX_AT = (20, 24)
ATLAS = FRAME[0] // 160
# The packed picture's width, and the clear pixels round each frame in it, so
# a frame drawn smoothly never takes in the edge of the one beside it.
PACK_WIDE = 2048
GUTTER = 2
WALK = ("walk1", "walk2", "walk3", "walk4")


def solid_box(alpha: Image.Image) -> tuple[int, int, int, int]:
    return alpha.point(lambda v: 255 if v > 127 else 0).getbbox()


def soles(alpha: Image.Image, band: int) -> list[float]:
    """Where the feet touch the ground, sheet px across: the middle of each
    thing in the figure's lowest `band` rows."""
    _, _, _, bottom = solid_box(alpha)
    rows = alpha.crop((0, bottom - band, alpha.width, bottom)).point(lambda v: 255 if v > 127 else 0)
    cover = rows.resize((alpha.width, 1), Image.Resampling.BOX).tobytes()
    runs, start = [], None
    for x, c in enumerate([*cover, 0]):
        if c > 20 and start is None:
            start = x
        elif c <= 20 and start is not None:
            runs.append([start, x])
            start = None
    # Bits of one shoe a few pixels apart are one foot.
    feet = []
    for run in runs:
        if feet and run[0] - feet[-1][1] < 6:
            feet[-1][1] = run[1]
        else:
            feet.append(run)
    return [(a + b) / 2 for a, b in feet if b - a >= 4]


class Poses:
    """A figure's painted poses, cut out and set in the pet's window."""

    def __init__(self, figure: Figure, scale: float) -> None:
        self.f = figure
        self.scale = scale
        folder = figure.folder / "frames"
        meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
        self.rows = meta.get("frames", {})
        # The face box measured as the frames' were: frames/meta.json's own for base, when it has one.
        self.base_face = tuple(meta.get("base", {}).get("face") or figure.face)
        self.feet = figure.bbox[3]
        self.pictures = {"rest": figure.frames[0]}
        self.patch = {}
        self.report = []
        # Each pose from frames/, else blink, talk and look as the sheet has them.
        for name in POSES[1:]:
            if (folder / f"{name}.png").is_file():
                self.pictures[name] = Image.open(folder / f"{name}.png").convert("RGB")
            elif name in FACES:
                self.pictures[name] = figure.frames[FACES.index(name) + 1]
                self.patch[name] = figure.face
        self.offsets = {}
        if "peek" in self.pictures:
            self.offsets["peek"] = self.peek_offset()
        # The face-only poses: their face box laid on the pose under them, which they are anyway
        # outside it, though redrawn line by line.
        for name, under in ON.items():
            if name in self.patch or name not in self.pictures or under not in self.pictures:
                continue
            box = figure.face if under == "rest" else self.union(self.face_of(under), self.face_of(name))
            other = self.pictures[name]
            dx, dy, off = nudge(self.pictures[under], other, box)
            self.pictures[name] = Image.composite(ImageChops.offset(other, dx, dy), self.pictures[under], ramp(other.size, box))
            self.patch[name] = box
            self.report.append(f"{name} on {under}: moved {dx:+d},{dy:+d}, {off:.1f} left")
        self.cut = {name: key_out(picture) for name, picture in self.pictures.items()}
        for name in self.cut:
            if name not in self.offsets:
                self.offsets[name] = self.offset(name)

    def face_of(self, name: str) -> tuple[int, ...]:
        return tuple(self.rows.get(name, {}).get("face") or self.base_face)

    @staticmethod
    def union(a, b, pad: int = 8) -> tuple[int, int, int, int]:
        x0, y0 = min(a[0], b[0]) - pad, min(a[1], b[1]) - pad
        x1, y1 = max(a[0] + a[2], b[0] + b[2]) + pad, max(a[1] + a[3], b[1] + b[3]) + pad
        return (x0, y0, x1 - x0, y1 - y0)

    def peek_offset(self) -> tuple[float, float]:
        """Where peek's picture goes on base's (painting px): its face on base's
        face, by the boxes, then to the pixel by the face itself."""
        px, py = self.face_of("peek")[:2]
        bx, by = self.base_face[:2]
        dx, dy = bx - px, by - py
        peek = self.pictures["peek"]
        base = ImageChops.offset(self.pictures["rest"], -round(dx), -round(dy)).crop((0, 0, *peek.size))
        fine_x, fine_y, _ = nudge(base, peek, (round(px), round(py), *self.base_face[2:]))
        return dx - fine_x, dy - fine_y

    def offset(self, name: str) -> tuple[float, float]:
        """How far a pose is moved to sit right (painting px): onto the feet
        line when it stands, as painted when it is off the ground, where peek
        is for peek's faces."""
        if ON.get(name) == "peek":
            return self.offsets["peek"]
        if name in AIRBORNE or name in self.patch:
            return 0.0, 0.0
        return 0.0, float(self.feet - solid_box(self.cut[name].getchannel("a"))[3])

    def place(self, name: str) -> Image.Image:
        """The pose in the pet's window at sheet size: base's body middle at
        the box's middle and its feet on the feet line, at the set's scale."""
        cut = self.cut[name]
        dx, dy = self.offsets[name]
        s = self.scale * FINE
        x0, y0, x1, y1 = cut.getchannel("a").getbbox()
        x0, y0, x1, y1 = max(0, x0 - 4), max(0, y0 - 4), min(cut.width, x1 + 4), min(cut.height, y1 + 4)
        crop = cut.crop((x0, y0, x1, y1))
        crop = crop.resize((round(crop.width * s), round(crop.height * s)), Image.Resampling.LANCZOS)
        mid, feet = self.anchor()
        canvas = Image.new("RGBa", (CELL[0] * ATLAS * FINE, CELL[1] * ATLAS * FINE), (0, 0, 0, 0))
        canvas.paste(crop, (round((mid + (x0 + dx - self.f.middle) * self.scale) * FINE),
                            round((feet + (y0 + dy - self.feet) * self.scale) * FINE)))
        return canvas.resize((CELL[0] * ATLAS, CELL[1] * ATLAS), Image.Resampling.BOX)

    @staticmethod
    def anchor() -> tuple[float, float]:
        """Where base's body middle and feet are in the window, sheet px."""
        return BOX_AT[0] * ATLAS + FRAME[0] / 2, BOX_AT[1] * ATLAS + FEET

    def to_window(self, name: str, box) -> tuple[int, int, int, int]:
        """A painting box [x, y, w, h] of a pose as sheet px in the window, [x0, y0, x1, y1], rounded out."""
        dx, dy = self.offsets[name]
        mid, feet = self.anchor()
        def x(v):
            return mid + (v + dx - self.f.middle) * self.scale

        def y(v):
            return feet + (v + dy - self.feet) * self.scale
        x0, y0, w, h = box
        return int(x(x0)) - 3, int(y(y0)) - 3, int(x(x0 + w)) + 4, int(y(y0 + h)) + 4

    def build(self) -> tuple[Image.Image, dict]:
        placed = {name: self.place(name) for name in self.pictures}
        pieces = {}
        for name, image in placed.items():
            if name in self.patch:
                box = self.to_window(name, self.patch[name])
            else:
                box = image.getchannel("a").getbbox()
                x0, y0, x1, y1 = box
                if x0 <= 0 or y0 <= 0 or x1 >= image.width or y1 >= image.height:
                    self.report.append(f"{name} reaches the window's edge: {box} of {image.size}")
            pieces[name] = (image.crop(box).convert("RGBA"), box)
        atlas, at = pack({name: piece for name, (piece, _) in pieces.items()})
        frames = {}
        for name, (_, box) in pieces.items():
            row = {"at": at[name], "to": list(box[:2])}
            if name in ON:
                row["on"] = ON[name]
            if "FAIL" in str(self.rows.get(name, {}).get("status", "")).upper():
                row["stand_in"] = True
            frames[name] = row
        self.walk(placed, frames)
        x0, y0, x1, y1 = placed["rest"].getchannel("a").getbbox()
        # Its eyes end where the blink stops changing it.
        shut = None
        if "blink" in placed:
            shut = ImageChops.difference(placed["rest"], placed["blink"]).convert("L")
            shut = shut.point(lambda v: 255 if v > 40 else 0).getbbox()
        eyes = shut[3] if shut else y0 + (y1 - y0) * 0.4
        fx0, fy0, fx1, fy1 = self.to_window("rest", self.f.face)
        def inbox(v, axis):
            return round(v / ATLAS - BOX_AT[axis], 1)

        layout = {
            "cell": list(CELL),
            "box_at": list(BOX_AT),
            "scale": ATLAS,
            "frames": frames,
            # The rest pose in the figure's box, CSS px: where it is, where its eyes end, and its face.
            "shape": {
                "top": inbox(y0, 1), "bottom": inbox(y1, 1), "left": inbox(x0, 0), "right": inbox(x1, 0),
                "eyes": inbox(eyes, 1), "face": [inbox(fx0, 0), inbox(fy0, 1), inbox(fx1, 0), inbox(fy1, 1)],
            },
        }
        if "peek" in placed:
            _, top, _, line = placed["peek"].getchannel("a").getbbox()
            # Over the app window: from its head's top to its arms, which lie on the window's edge.
            layout["peek"] = {"top": inbox(top, 1), "line": inbox(line, 1)}
        return atlas, layout

    def walk(self, placed: dict, frames: dict) -> None:
        """How far its window goes as each walking pose comes on, so that the
        foot it stands on stays where it is on the screen (CSS px), and how
        far as it stops. Painted toward the viewer's right; the page mirrors
        them to go left."""
        if not all(name in placed for name in WALK):
            return
        found = {name: soles(placed[name].getchannel("a"), 12 if name in ("walk1", "walk3") else 5) for name in WALK}
        # Contact: both feet down, the front one is stood on next. Passing: the one foot down.
        front = {n: max(found[n]) for n in ("walk1", "walk3") if found[n]}
        back = {n: min(found[n]) for n in ("walk1", "walk3") if found[n]}
        down = {n: sum(found[n]) / len(found[n]) for n in ("walk2", "walk4") if found[n]}
        steps = {
            "walk2": front.get("walk1", 0) - down.get("walk2", 0),
            "walk3": down.get("walk2", 0) - back.get("walk3", 0),
            "walk4": front.get("walk3", 0) - down.get("walk4", 0),
            "walk1": down.get("walk4", 0) - back.get("walk1", 0),
        }
        good = sorted(v for v in steps.values() if v > 0)
        middle = good[len(good) // 2] if good else 8 * ATLAS
        # Stopping, the foot it stands on stays and the other comes up beside it:
        # the window goes on, or back, by what keeps that foot where it was.
        last = soles(placed["turn" if "turn" in placed else "rest"].getchannel("a"), 12) or [self.anchor()[0]]
        plant = {**front, **down}
        for name, step in steps.items():
            sure = 0 < step < middle * 1.8
            frames[name]["advance"] = round((step if sure else middle) / ATLAS, 2)
            # The foot it stands on until the next pose, in the figure's box: it leans on over it.
            frames[name]["plant"] = round(plant.get(name, self.anchor()[0]) / ATLAS - BOX_AT[0], 1)
            self.report.append(f"{name}: soles at {[round(v / ATLAS, 1) for v in found[name]]}, "
                               f"advance {step / ATLAS:.1f}{'' if sure else ' (unsure: the middle step instead)'}")
        for name in ("walk2", "walk4"):
            foot = down.get(name, last[0])
            frames[name]["stop"] = round(max(-middle, min(foot - min(last, key=lambda x: abs(x - foot)), middle)) / ATLAS, 2)


def pack(pieces: dict) -> tuple[Image.Image, dict]:
    """The pieces in rows, tallest first, in one picture, and where each is: [x, y, w, h]."""
    at, x, y, row = {}, GUTTER, GUTTER, 0
    for name in sorted(pieces, key=lambda n: -pieces[n].height):
        w, h = pieces[name].size
        if x + w + GUTTER > PACK_WIDE:
            x, y, row = GUTTER, y + row + GUTTER, 0
        at[name] = [x, y, w, h]
        x += w + GUTTER
        row = max(row, h)
    atlas = Image.new("RGBA", (PACK_WIDE, y + row + GUTTER), (0, 0, 0, 0))
    for name, piece in pieces.items():
        atlas.paste(piece, tuple(at[name][:2]))
    return atlas, at


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
        if args.keys and f.key not in args.keys:
            continue
        sheets[f.key].save(FIGURES / f"{f.key}.webp", lossless=True, quality=100, method=6)
        if not (f.folder / "frames" / "meta.json").is_file():
            continue
        poses = Poses(f, s)
        atlas, layout = poses.build()
        # Lossy colour and exact edges: the colour's loss does not show at this
        # size, and the file is a fraction of a lossless one.
        atlas.save(FIGURES / f"{f.key}.pet.webp", quality=90, alpha_quality=100, method=6)
        (FIGURES / f"{f.key}.pet.json").write_text(json.dumps(layout, separators=(",", ":")) + "\n", encoding="utf-8")
        stand_in = [name for name, row in layout["frames"].items() if row.get("stand_in")]
        print(f"  poses: {' '.join(layout['frames'])}; {atlas.width}x{atlas.height}, "
              f"{(FIGURES / f'{f.key}.pet.webp').stat().st_size // 1024} KB"
              + (f"; stand-ins: {' '.join(stand_in)}" if stand_in else ""))
        for line in poses.report:
            print("  " + line)
    gallery(sheets, args.art / "gallery.png")


if __name__ == "__main__":
    main()
