"""Mibo's colours: its accent (the antenna's dot and the chest's) and its shell,
chosen by the person within cool colours and kept in the app's settings.
figures/mibo.svg is drawn in the default colours; `paint` gives it the chosen ones.

The accent's hue is 165-265 degrees (blue-green, teal, cyan, sky blue, blue,
blue-violet), saturated enough to read as a colour (HSL saturation 0.35 or
more) and neither near black nor near white (HSL lightness 0.35-0.80). The
shell is near white or a cool light grey: HSL lightness 0.80 or more, and
either almost no colour at all (max - min of its channels 8/255 or less, any
hue) or a hue of 165-265 degrees with max - min 36/255 or less.
"""
from __future__ import annotations

import asyncio
import colorsys
import re

from fastapi import Request

ERRORS: frozenset[str] = frozenset({"invalid_accent", "invalid_shell"})
DEFAULT = {"accent": "#6cc4f5", "shell": "#eef1f5"}
COOL = (165, 265)
HEX = re.compile(r"#[0-9a-f]{6}")
# What the shell's shading is mixed towards: a cool dark grey, never black.
SHADE = "#39424f"


def _rgb(value: str) -> tuple[float, float, float]:
    return tuple(int(value[i:i + 2], 16) / 255 for i in (1, 3, 5))


def _hex(rgb) -> str:
    return "#" + "".join(f"{round(max(0.0, min(1.0, c)) * 255):02x}" for c in rgb)


def _mix(a: str, b: str, share: float) -> str:
    return _hex(x + (y - x) * share for x, y in zip(_rgb(a), _rgb(b)))


def _hue(rgb) -> float:
    return colorsys.rgb_to_hls(*rgb)[0] * 360


def cool_accent(value: str) -> bool:
    rgb = _rgb(value)
    _, light, saturation = colorsys.rgb_to_hls(*rgb)
    return COOL[0] <= _hue(rgb) <= COOL[1] and saturation >= 0.35 and 0.35 <= light <= 0.80


def cool_shell(value: str) -> bool:
    rgb = _rgb(value)
    light, spread = colorsys.rgb_to_hls(*rgb)[1], max(rgb) - min(rgb)
    return light >= 0.80 and (spread <= 8 / 255 or (COOL[0] <= _hue(rgb) <= COOL[1] and spread <= 36 / 255))


def palette(accent: str, shell: str) -> dict[str, str]:
    """Every colour of the drawing that follows the two chosen ones."""
    return {
        "accent": accent,
        "shell-hi": _mix(shell, "#ffffff", 0.75),
        "shell": shell,
        "shell-lo": _mix(shell, SHADE, 0.13),
        "arm-hi": _mix(shell, "#ffffff", 0.3),
        "arm-lo": _mix(shell, SHADE, 0.17),
        "line": _mix(shell, SHADE, 0.21),
        "grey": _mix(shell, SHADE, 0.36),
    }


def chosen(settings: dict) -> dict[str, str]:
    saved = settings.get("colors") or {}
    return {key: saved.get(key) or DEFAULT[key] for key in DEFAULT}


def paint(svg: str, colors: dict[str, str]) -> str:
    """The drawing in `colors`, from the default ones it is drawn in."""
    if colors == DEFAULT:
        return svg
    swap = dict(zip(palette(**DEFAULT).values(), palette(**colors).values()))
    return HEX.sub(lambda match: swap.get(match[0], match[0]), svg)


def mount(app, workspace, body) -> None:
    from ..welcome import app_settings, save_app_settings

    desktop = workspace.home / "runtime" / "desktop"

    @app.get("/api/look/colors")
    async def read_colors():
        return chosen(await asyncio.to_thread(app_settings, desktop))

    @app.post("/api/look/colors")
    async def choose_colors(request: Request):
        payload = await body(request)
        colors = {}
        for key, fits, error in (("accent", cool_accent, "invalid_accent"), ("shell", cool_shell, "invalid_shell")):
            value = str(payload.get(key) or "").lower()
            if not HEX.fullmatch(value) or not fits(value):
                raise ValueError(error)
            colors[key] = value
        await asyncio.to_thread(save_app_settings, desktop, colors=colors)
        # The pet and the app window draw it again (petFigure, paFrame).
        workspace.figure_changed()
        return colors
