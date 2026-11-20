"""How each model points, measured rather than trusted to the prompt.

Any model that takes pictures gets a profile. From the pointing study of
2026-11-19 (56 screenshots, 210 targets, one look each): a model keeps its own
coordinate habit whatever it is asked. qwen3.7 and deepseek-v4.1 answer on
0-1000, glm-5.3 and ui-tars-1.5 in pixels of the picture, gpt-6-luna and
claude-haiku-5.5 do what they are asked (best in pixels). The table below holds
what was measured for those families, a starting point and never a list of the
models allowed to see:

- `scale`: "norm" (0-1000 both ways, 0,0 the top-left) or "px" (pixels of the
  picture as sent, whose size the prompt states).
- `marks`: numbered boxes from the structure, tag inside the box (tags above
  a box were read as the label of the box over it on dense windows).
- `zoom`: "ctx" for a second look at a crop with the whole picture beside it,
  outlined (rescued deepseek 77 -> 90%; a crop without the whole picture, or
  any second look for qwen and luna, broke more than it rescued).
- `grid`: red lines every 100 px (helped glm 80 -> 90%, hurt deepseek).
- `floor`: the target size in real pixels below which a point is not trusted
  without the structure (qwen 95% from 22 px).
- `extra`: fields for the request, through OpenRouter: reasoning off where it
  can be, and the provider pinned for deepseek (others returned wrong points
  or nothing for the same model).

`selftest` runs once when the person connects a model service (abilities.py
keeps its reading as `pointing`): one drawn picture asked in the form the
profile starts from. A model the table does not know takes the form that came
back. For a known model the measured form stands: on 2026-11-19 qwen3.7 and
deepseek-v4.1 answered this simple picture in pixels when asked for pixels in
JSON, though on real screenshots they answered 0-1000 to the same request, so
one easy picture does not reveal a habit; it catches a service that does not
point at all ("none"), whose model then only looks and tells the person
(`reach`).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from PIL import Image, ImageDraw

from .frame import LONG_EDGE


@dataclass(frozen=True)
class Profile:
    scale: str = "px"
    marks: bool = True
    zoom: str = ""
    grid: bool = False
    floor: int = 24
    long_edge: int = LONG_EDGE
    extra: dict = field(default_factory=dict)
    known: bool = False


OFF = {"reasoning": {"effort": "none"}}
PROFILES = (
    (r"qwen3(?:\.\d+)?-(?:vl-)?flash|qwen3\.\d+-flash", Profile("norm", floor=22, extra=OFF, known=True)),
    (r"deepseek-v4(?:\.\d+)?-flash", Profile("norm", zoom="ctx", floor=31, known=True, extra={
        **OFF, "provider": {"order": ["ionstream", "deepinfra/fp8"], "allow_fallbacks": False}})),
    (r"glm-5(?:\.\d+)?-flash", Profile("px", grid=True, floor=26, known=True, extra={
        "reasoning": {"effort": "minimal"}, "provider": {"order": ["novita/fp8", "z-ai/fp8"],
                                                         "allow_fallbacks": False}})),
    (r"ui-tars", Profile("px", marks=False, floor=40, known=True)),
    (r"gpt-6-luna", Profile("px", floor=17, extra=OFF, known=True)),
    (r"claude-haiku-5(?:\.\d+)?", Profile("px", floor=17, extra=OFF, known=True)),
    # Qwen-VL and Gemini publish 0-1000 as their habit; not measured here.
    (r"qwen[\d.]*-vl|gemini", Profile("norm", floor=24)),
)


def profile(model: str, measured: str = "") -> Profile:
    """The model's profile; for a model not in the table, `measured` (what selftest read back) sets the form."""
    name = str(model or "").lower()
    found = next((p for pattern, p in PROFILES if re.search(pattern, name)), Profile())
    if not found.known and measured in ("norm", "px") and measured != found.scale:
        return Profile(measured, found.marks, found.zoom, found.grid, found.floor, found.long_edge, found.extra, True)
    return found


def reach(pictures: str, pointing: str) -> str:
    """What the person's model may do with a window that only a picture can work, from what the app measured
    (abilities.py): "act" to work it by picture, "look" to look and tell the person where to click (it takes
    pictures and did not point in the self-test), "" when it takes no pictures."""
    if pictures == "no":
        return ""
    return "look" if pointing == "none" else "act"


# --- the one-picture self-test, when the person connects a model service

SELFTEST_SIZE = (1280, 800)
# Where the target is: in pixels this is (896, 560); on 0-1000 it reads (700, 700). The two readings differ.
SELFTEST_AT = (896, 560)
SELFTEST_PROMPT = ("This picture is {w} pixels wide and {h} pixels tall. Where is the centre of the orange circle? "
                   'Answer with one JSON object only: {{"x": <number>, "y": <number>}}, {form}.')
FORMS = {"px": "in pixels of this picture",
         "norm": "on a 0-1000 scale across the picture (0,0 top-left, 1000,1000 bottom-right)"}


def selftest_picture() -> Image.Image:
    image = Image.new("RGB", SELFTEST_SIZE, (236, 236, 236))
    draw = ImageDraw.Draw(image)
    for i, (x, y) in enumerate(((180, 150), (420, 610), (1100, 220))):
        draw.rectangle((x - 40, y - 25, x + 40, y + 25), fill=(90, 110, 200 - 40 * i))
    x, y = SELFTEST_AT
    draw.ellipse((x - 26, y - 26, x + 26, y + 26), fill=(255, 140, 0))
    return image


def read_selftest(answer: str) -> str:
    """"px", "norm", or "none" when the answer is neither reading of the circle (this model and service do not
    point usably)."""
    from .ask import read_json
    value = read_json(answer)
    try:
        x, y = float(value["x"]), float(value["y"])
    except (KeyError, TypeError, ValueError):
        return "none"
    px, py = SELFTEST_AT
    nx, ny = px * 1000 / SELFTEST_SIZE[0], py * 1000 / SELFTEST_SIZE[1]
    if abs(x - px) <= 26 and abs(y - py) <= 26:
        return "px"
    if abs(x - nx) <= 21 and abs(y - ny) <= 33:
        return "norm"
    return "none"


async def selftest(ask_model, model: str) -> str:
    """One look at a drawn picture through the person's own service, asked in the form `model`'s profile starts
    from: the reading that came back ("px", "norm" or "none"), or "" when no answer came (not measured).
    `ask_model(system, messages)` gives the answer's text, or None when the call failed."""
    from .frame import b64_png
    w, h = SELFTEST_SIZE
    answer = await ask_model("You point at things in pictures.", [{"role": "user", "content": [
        {"type": "text", "text": SELFTEST_PROMPT.format(w=w, h=h, form=FORMS[profile(model).scale])},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64_png(selftest_picture())}}]}])
    return "" if answer is None else read_selftest(answer)
