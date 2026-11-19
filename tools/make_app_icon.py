"""Draw the app icon: two eyes on a dark tile, one of them winking.

    python tools/make_app_icon.py

Writes persona_agent/static/app.ico (Windows) and app.png (GTK and Qt).
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

STATIC = Path(__file__).resolve().parents[1] / "persona_agent" / "static"
INK, PAPER = (29, 27, 24, 255), (246, 244, 240, 255)
CANVAS = 1024
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def draw() -> Image.Image:
    c = CANVAS
    image = Image.new("RGBA", (c, c), (0, 0, 0, 0))
    pen = ImageDraw.Draw(image)
    pen.rounded_rectangle([0, 0, c - 1, c - 1], radius=c * 0.225, fill=INK)
    pen.rounded_rectangle([c * 0.285, c * 0.365, c * 0.415, c * 0.635], radius=c * 0.065, fill=PAPER)
    # The wink: a short arc with round ends.
    box, stroke = [c * 0.50, c * 0.42, c * 0.80, c * 0.72], round(c * 0.085)
    pen.arc(box, 215, 325, fill=PAPER, width=stroke)
    reach = (box[2] - box[0]) / 2 - stroke / 2
    for angle in (215, 325):
        x = c * 0.65 + reach * math.cos(math.radians(angle))
        y = c * 0.57 + reach * math.sin(math.radians(angle))
        pen.ellipse([x - stroke / 2, y - stroke / 2, x + stroke / 2, y + stroke / 2], fill=PAPER)
    return image


def main() -> None:
    master = draw()
    master.resize((256, 256), Image.LANCZOS).save(STATIC / "app.png", optimize=True)
    master.save(STATIC / "app.ico", sizes=[(size, size) for size in ICO_SIZES])


if __name__ == "__main__":
    main()
