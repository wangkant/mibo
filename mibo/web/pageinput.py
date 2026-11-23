"""What the model writes for a page to take: a key or a chord as Playwright names them, and a date, time, month, week
or colour in the form its field takes (pagewords.SET_BY_VALUE)."""
from __future__ import annotations

import re
import sys

from .pagewords import norm

# Keys a press may name; a chord holds them with modifiers, by Playwright's names and the usual short ones, as
# CDP's mask (Alt 1, Control 2, Meta 4, Shift 8); one letter, digit or sign is a key too.
KEYS = {"Enter": 13, "Escape": 27, "Tab": 9, "Backspace": 8, "Delete": 46, "Insert": 45, "ArrowDown": 40,
        "ArrowUp": 38, "ArrowLeft": 37, "ArrowRight": 39, "PageDown": 34, "PageUp": 33, "Home": 36, "End": 35, " ": 32,
        **{f"F{n}": 111 + n for n in range(1, 13)}}
SIGNS = {"/": 191, ".": 190, ",": 188, "-": 189, "=": 187, ";": 186, "'": 222, "[": 219, "]": 221, "`": 192,
         "\\": 220}
# Playwright's names (keyboard.press: ArrowLeft, KeyA, Digit1, Backquote, Space), the short ones people and models
# write (Left, Down, Esc, PgDn, Ins) and the signs by their code names.
KEY_NAMES = {**{k.lower(): k for k in KEYS}, "space": " ", "esc": "Escape", "del": "Delete", "return": "Enter",
             "ins": "Insert", "left": "ArrowLeft", "right": "ArrowRight", "up": "ArrowUp", "down": "ArrowDown",
             "pgup": "PageUp", "pgdn": "PageDown", "pagedn": "PageDown", "backquote": "`", "minus": "-",
             "equal": "=", "backslash": "\\", "bracketleft": "[", "bracketright": "]", "semicolon": ";",
             "quote": "'", "comma": ",", "period": ".", "slash": "/",
             **{f"key{c}": c for c in "abcdefghijklmnopqrstuvwxyz"}, **{f"digit{n}": str(n) for n in range(10)}}
MODIFIERS = {"alt": ("Alt", 1), "option": ("Alt", 1), "control": ("Control", 2), "ctrl": ("Control", 2),
             "meta": ("Meta", 4), "cmd": ("Meta", 4), "command": ("Meta", 4), "shift": ("Shift", 8),
             # Playwright's ControlOrMeta: Meta on a Mac, Control elsewhere.
             "controlormeta": ("Meta", 4) if sys.platform == "darwin" else ("Control", 2)}


def chord(keys: str) -> tuple[str, int, str]:
    """A key or chord as the model writes it ("Control+Enter", "shift+tab", "Delete"): its spelling, the modifier
    mask and the key. ValueError for a modifier or key it does not know."""
    *held, key = [p.strip() for p in str(keys).split("+")] if str(keys).strip() else [" "]
    key = KEY_NAMES.get(key.lower(), key)
    if not (key in KEYS or key in SIGNS or (len(key) == 1 and key.isascii() and key.isalnum())):
        raise ValueError(f"no key {key[:20]!r}")
    if any(p.lower() not in MODIFIERS for p in held):
        raise ValueError(f"no chord {str(keys)[:30]!r}")
    mods = dict(MODIFIERS[p.lower()] for p in held)
    named = [m for m in ("Control", "Alt", "Meta", "Shift") if m in mods]
    return "+".join([*named, "Space" if key == " " else key]), sum(mods[m] for m in named), key


DATE_YMD = re.compile(r"(\d{4})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})")
DATE_SHOWN = re.compile(r"(\d{1,2})\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{4})")
CLOCK = re.compile(r"(上午|下午|晚上)?\s*(\d{1,2})\s*[:：时点]\s*(\d{1,2})?(?:\s*[:：]\s*(\d{1,2}))?\s*分?\s*(?:([ap])\.?\s*m\.?)?",
                   re.I)


def as_value(kind: dict, text: str) -> str:
    """A date, time, month, week or colour as a person writes it, in the form its field takes (SET_BY_VALUE);
    a date given by numbers only is read in the order the field shows it. Anything else as it is."""
    t, typ = norm(text), kind["type"]

    def day(s: str) -> tuple[str | None, str]:
        m = DATE_YMD.search(s)
        if m:
            y, mo, d = m.groups()
        else:
            m = DATE_SHOWN.search(s)
            if not m:
                return None, s
            a, b, y = m.groups()
            mo, d = (b, a) if kind["order"].startswith("d") else (a, b)
        return f"{y}-{int(mo):02}-{int(d):02}", s[m.end():]

    def clock(s: str) -> str | None:
        m = CLOCK.search(s)
        if not m:
            return None
        part, h, mi, sec, half = m.groups()
        hour = int(h)
        if half:
            hour = hour % 12 + (12 if half.lower() == "p" else 0)
        elif part in ("下午", "晚上") and hour < 12:
            hour += 12
        return f"{hour:02}:{int(mi or 0):02}" + (f":{int(sec):02}" if sec else "")
    if typ == "date":
        return day(t)[0] or t
    if typ == "time":
        return clock(t) or t
    if typ == "datetime-local":
        d, rest = day(t)
        c = clock(rest) if d else None
        return f"{d}T{c}" if d and c else t
    if typ == "month":
        m = re.search(r"(\d{4})\s*[-/.年]\s*(\d{1,2})", t)
        return f"{m.group(1)}-{int(m.group(2)):02}" if m else t
    if typ == "week":
        m = re.search(r"(\d{4})\s*[-年]?\s*(?:W|第)?\s*(\d{1,2})", t, re.I)
        return f"{m.group(1)}-W{int(m.group(2)):02}" if m else t
    if typ == "color":
        m = re.fullmatch(r"#?([0-9a-f]{3}|[0-9a-f]{6})", t, re.I)
        return "#" + (m.group(1) if len(m.group(1)) == 6 else "".join(c * 2 for c in m.group(1))).lower() if m else t
    return t
