"""One picture as sent to the model, and the way back from its pixels to real ones.

Real pixels are, for a window, physical screen pixels of the virtual desktop
(the ones SendInput and UI Automation use on a per-monitor-aware thread), and
for the pane, CSS pixels of the page's viewport (the ones DevTools input
takes). `k` is picture pixels per real pixel, the same both ways, so a point
the model gives on the picture is `origin + p / k` in real pixels.
"""
from __future__ import annotations

import base64
import io
from dataclasses import dataclass, field

from PIL import Image, ImageChops, ImageDraw

# A picture longer than this on its long edge is scaled down; never up.
LONG_EDGE = 1280
# How far round a point a change counts as "where it should", in real pixels.
NEAR = 60
# A pixel counts as changed above this difference (of 255), against JPEG noise and blinking carets.
CHANGED = 24


@dataclass
class Frame:
    image: Image.Image             # as sent: scaled, secrets painted over
    kind: str                      # "pane" or "window"
    origin: tuple[float, float]    # real pixel of the picture's top-left corner
    k: float                       # picture pixels per real pixel
    real: tuple[int, int]          # the captured area in real pixels
    hwnd: int = 0
    rect: tuple = ()               # the window's rect when captured, to tell a stale picture
    dpi: int = 96
    url: str = ""
    secrets: list = field(default_factory=list)   # real boxes painted over
    marks: dict = field(default_factory=dict)     # number -> (real x, real y, what)

    @property
    def size(self) -> tuple[int, int]:
        return self.image.size

    def to_real(self, x: float, y: float) -> tuple[float, float]:
        return self.origin[0] + x / self.k, self.origin[1] + y / self.k

    def to_image(self, x: float, y: float) -> tuple[float, float]:
        return (x - self.origin[0]) * self.k, (y - self.origin[1]) * self.k

    def inside(self, x: float, y: float) -> bool:
        wide, high = self.image.size
        return 0 <= x < wide and 0 <= y < high

    def data_url(self) -> str:
        return "data:image/jpeg;base64," + b64(self.image, "JPEG", quality=80)


def fit(image: Image.Image, long_edge: int = LONG_EDGE) -> tuple[Image.Image, float]:
    """The image scaled so its long edge is at most `long_edge`, and the factor applied."""
    k = min(1.0, long_edge / max(image.size))
    if k < 1:
        image = image.resize((max(1, round(image.size[0] * k)), max(1, round(image.size[1] * k))), Image.LANCZOS)
    return image, k


def paint_over(image: Image.Image, boxes: list, origin: tuple[float, float], k: float = 1.0) -> None:
    """Fill each real box (x, y, w, h) grey on the picture, with a margin for the field's border."""
    draw = ImageDraw.Draw(image)
    for x, y, wide, high in boxes:
        x0, y0 = (x - origin[0]) * k - 2, (y - origin[1]) * k - 2
        draw.rectangle((x0, y0, x0 + wide * k + 4, y0 + high * k + 4), fill=(128, 128, 128))


def ring(image: Image.Image, x: float, y: float, r: int = 18) -> Image.Image:
    """A copy with a ring at a picture point, for the person's card."""
    out = image.copy()
    draw = ImageDraw.Draw(out)
    for width, colour in ((5, (255, 255, 255)), (3, (230, 30, 60))):
        draw.ellipse((x - r, y - r, x + r, y + r), outline=colour, width=width)
    return out


def change(before: Frame, after: Frame, *points: tuple[float, float]) -> dict:
    """What changed between two pictures of the same thing: {"any", "near", "box"} with `box` the changed
    area in real pixels; `near` whether it touches NEAR real pixels round any of the real `points` (a click's,
    or a drag's start and end)."""
    if before.size != after.size or before.origin != after.origin:
        return {"any": True, "near": True, "box": None, "moved": True}
    diff = ImageChops.difference(before.image, after.image).convert("L").point(lambda v: 255 if v > CHANGED else 0)
    box = diff.getbbox()
    if not box:
        return {"any": False, "near": False, "box": None}
    x0, y0 = before.to_real(box[0], box[1])
    x1, y1 = before.to_real(box[2], box[3])
    near = False
    r = NEAR * before.k
    for at in points:
        ix, iy = before.to_image(*at)
        near = near or diff.crop((max(0, int(ix - r)), max(0, int(iy - r)), int(ix + r), int(iy + r))).getbbox() is not None
    return {"any": True, "near": near, "box": (round(x0), round(y0), round(x1 - x0), round(y1 - y0))}


def b64(image: Image.Image, kind: str = "PNG", **save) -> str:
    """The image encoded as `kind` (Pillow's format name, with its `save` options), in base64."""
    buf = io.BytesIO()
    image.save(buf, kind, **save)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def png_part(image: Image.Image) -> dict:
    """The image as a PNG part of a message's content."""
    return {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64(image)}}


def pack(frame: Frame) -> dict:
    """A frame as JSON, to cross from the app's process (where the pane and the windows are) to the service's
    (where the model is called)."""
    return {"png": b64(frame.image), "kind": frame.kind, "origin": list(frame.origin), "k": frame.k,
            "real": list(frame.real), "hwnd": frame.hwnd, "rect": list(frame.rect), "dpi": frame.dpi,
            "url": frame.url, "marks": {str(n): [x, y, what, list(b)] for n, (x, y, what, b) in frame.marks.items()}}


def unpack(data: dict) -> Frame:
    image = Image.open(io.BytesIO(base64.b64decode(data["png"]))).convert("RGB")
    return Frame(image, data["kind"], tuple(data["origin"]), float(data["k"]), tuple(data["real"]),
                 hwnd=int(data.get("hwnd") or 0), rect=tuple(data.get("rect") or ()), dpi=int(data.get("dpi") or 96),
                 url=str(data.get("url") or ""),
                 marks={int(n): (m[0], m[1], m[2], tuple(m[3])) for n, m in (data.get("marks") or {}).items()})
