"""What one DOM snapshot of a document shows that its accessibility tree does not (for pageops' look): elements shown
as clickable that the tree names no control (a pointer cursor, the outermost of its kind; short parts side by side
inside it, as Reply and Forward in one bar, each a clickable of its own, as Playwright MCP gives every part of a
clickable its ref), boxes that scroll by themselves with how far down they are, the words a control with no name
keeps (its tooltip, else what names its icon, its id's and its class's words), the type of each date, time, colour or
range field, the frames shown, where each node stands down the page, and what is drawn (an svg with its shapes, a
canvas, rows of colour boxes with no words). Keys are backendNodeIds."""
from __future__ import annotations

import re
from collections import deque
from itertools import pairwise
from urllib.parse import urlsplit

from .pagewords import CONTROLS, SET_BY_VALUE, norm

# The computed styles a snapshot is asked for, in the order `layout` reads them.
STYLES = ["cursor", "overflow-y", "visibility", "content", "background-image", "background-color", "fill", "stroke"]
# A pointer cursor on these says nothing new: the tree already names them, or they hold the page.
POINTER_SKIP = {"A", "BUTTON", "INPUT", "SELECT", "TEXTAREA", "LABEL", "OPTION", "SUMMARY", "HTML", "BODY", "IFRAME",
                "VIDEO", "AUDIO", "CANVAS"}
# Where a control with no name keeps its words, in this order; then its class.
HINT_ATTRS = ("data-tooltip", "data-tip", "data-title", "data-original-title", "aria-description", "title", "alt")
# Parts of a clickable given their own ids: at most this many side by side, each of at most this many characters.
PARTS_MAX = 8
PART_WORDS = 24
# What an svg draws that gets a line and an id, at most SHAPES_MAX a drawing; drawn things in one look at most.
SHAPES = {"circle", "ellipse", "rect", "polygon", "polyline", "path", "line", "text", "image"}
SHAPES_MAX = 30
DRAWN_MAX = 60
# A knob or an icon is at most this wide and high, in pixels.
SMALL = 48
# Words a machine made ("css-1x2y3z", "a__b"), not ones a person could read.
MACHINE_WORD = re.compile(r"\d\D*\d|^[a-z]{1,4}-(?=[a-z]*\d)[a-z0-9]{5,}$|__", re.I)
# An icon's own state, shown only by its class (a star filled in).
ON_CLASS = re.compile(r"(^|\s)(on|active|is-active|is-on|liked|starred|selected|checked|pressed|faved)(\s|$)")
# Where an id's words part: dashes, underscores and a lower letter before a capital.
# Test ids, which name a control for a page's own tests (data-e2e: ByteDance's sites).
TEST_IDS = ("data-testid", "data-test", "data-qa", "data-e2e")
ID_PARTS = re.compile(r"[-_]+|(?<=[a-z])(?=[A-Z])")


def empty() -> dict:
    """A layout with nothing in it, for a document whose snapshot could not be taken."""
    return {"click": {}, "scroll": {}, "hint": {}, "type": {}, "frame": {}, "y": {}, "drawn": {}, "small": {},
            "area": {}, "outer": {}}


def colour(css: str) -> str:
    """A computed colour ("rgb(128, 128, 128)") as a person names it, with its hex: "grey #808080"; "" for none or
    one that cannot be seen."""
    found = re.match(r"rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:[,\s/]+([\d.]+%?))?", css or "")
    if not found or (found.group(4) and float(found.group(4).rstrip("%")) == 0):
        return ""
    r, g, b = (min(255, round(float(v))) for v in found.groups()[:3])
    hi, lo = max(r, g, b) / 255, min(r, g, b) / 255
    light, chroma = (hi + lo) / 2, hi - lo
    if chroma < 0.12:
        name = "black" if light < 0.15 else "white" if light > 0.9 else "grey"
    else:
        top = max(r, g, b)
        hue = (60 * (((g - b) / 255 / chroma) % 6) if top == r else 60 * ((b - r) / 255 / chroma + 2) if top == g
               else 60 * ((r - g) / 255 / chroma + 4))
        name = next(n for edge, n in ((15, "red"), (40, "orange"), (65, "yellow"), (165, "green"), (195, "cyan"),
                                      (255, "blue"), (285, "purple"), (330, "magenta"), (345, "pink"), (361, "red"))
                    if hue < edge)
        if name in ("orange", "red") and light < 0.45 and chroma < 0.6:
            name = "brown"
    return f"{name} #{r:02x}{g:02x}{b:02x}"


def _readable(w: str) -> bool:
    """Words a person could read ("like-btn", "icon-share"), not machine ones ("css-1x2y3z")."""
    return len(w) > 2 and not MACHINE_WORD.search(w)


def _picture_name(css: str) -> str:
    """The file name of a CSS image (content: url(send.png), a background image); "" for none."""
    found = re.search(r"url\(\s*['\"]?([^'\")]+)", css or "")
    if not found or found.group(1).startswith("data:"):
        return ""
    return re.sub(r"\.\w+$", "", found.group(1).split("?")[0].rstrip("/").rsplit("/", 1)[-1])


class _Document:
    """One document of a snapshot, read by node index: its tree, its attributes and the layout of its elements."""

    def __init__(self, doc: dict, strings: list[str]) -> None:
        self.strings = strings
        nodes, layout = doc.get("nodes") or {}, doc.get("layout") or {}
        self.parent, self.backend = nodes.get("parentIndex") or [], nodes.get("backendNodeId") or []
        self.names, self.kinds = nodes.get("nodeName") or [], nodes.get("nodeType") or []
        self.values = nodes.get("nodeValue") or []
        self.attrs = nodes.get("attributes") or []
        self.inner = set((nodes.get("contentDocumentIndex") or {}).get("index") or [])
        # Each laid-out node's styles (STYLES, padded) and its place in the layout's lists.
        self.style: dict[int, list] = {}
        self.box: dict[int, int] = {}
        for k, i in enumerate(layout.get("nodeIndex") or []):
            self.style[i] = [self.text(v) for v in (layout.get("styles") or [[]])[k]] + [""] * 8
            self.box[i] = k
        self.bounds = layout.get("bounds") or []
        self.scrolls, self.clients = layout.get("scrollRects") or [], layout.get("clientRects") or []

    def text(self, i: int) -> str:
        return self.strings[i] if isinstance(i, int) and 0 <= i < len(self.strings) else ""

    def up(self, i: int) -> int:
        return self.parent[i] if 0 <= i < len(self.parent) else -1

    def tag(self, i: int) -> str:
        return self.text(self.names[i]).upper() if 0 <= i < len(self.names) else ""

    def attrs_of(self, i: int) -> dict:
        pairs = self.attrs[i] if i < len(self.attrs) else []
        return {self.text(pairs[j]).lower(): self.text(pairs[j + 1]) for j in range(0, len(pairs) - 1, 2)}

    def shown(self, i: int) -> list | None:
        """The element's box [x, y, w, h] in the document when it is drawn, else None."""
        k = self.box.get(i)
        b = self.bounds[k] if k is not None and k < len(self.bounds) else None
        return b if b and len(b) == 4 and b[2] > 0 and b[3] > 0 and self.style[i][2] != "hidden" else None

    def styled(self, i: int) -> int:
        """The nearest node at or over i that has a layout, or -1."""
        while i >= 0 and i not in self.style:
            i = self.up(i)
        return i

    def control(self, i: int) -> bool:
        """The element is a control by its own markup: a link, a field, a button, a control's role or a place in
        the tab order."""
        found = self.attrs_of(i)
        return (self.tag(i) in ("BUTTON", "INPUT", "SELECT", "TEXTAREA") or (self.tag(i) == "A" and (
            "href" in found or "xlink:href" in found)) or found.get("role", "") in CONTROLS or "tabindex" in found)

    def holds_control(self, i: int, kids: dict[int, list[int]]) -> bool:
        stack = list(kids.get(i, []))
        while stack:
            c = stack.pop()
            if self.control(c):
                return True
            stack += kids.get(c, [])
        return False


def layout(snap: dict) -> dict:
    """What a snapshot (DOMSnapshot.captureSnapshot with STYLES and DOM rects) shows, by backendNodeId: "click"
    (clickable with no control named), "outer" (a part of a clickable -> the clickable), "scroll" (how far down a box
    that scrolls by itself is), "hint" (a nameless control's words), "type" (a field set by value, or a list where
    several can be chosen), "area" (a text area), "frame" (a frame from another site -> its host), "small" (a knob
    or an icon), "y" (where a node of the page itself stands) and "drawn" (drawings and colour boxes of the page
    itself)."""
    strings = snap.get("strings") or []
    out = empty()
    for n, raw in enumerate(snap.get("documents") or []):
        d = _Document(raw, strings)
        words, kids, said = _words(d)
        icon = _icons(d, words, kids, said)
        if n == 0:
            _places(d, out)
        outer = _clickables(d, icon, out, kids)
        _parts(d, outer, words, kids, icon, out)
        if n == 0:
            _drawings(d, kids, said, out)
            _tiles(d, words, kids, icon, out)
    return out


def _words(d: _Document) -> tuple[list[int], dict[int, list[int]], dict[int, str]]:
    """The characters of words under each node, its element children, and the words of each svg <text> and
    <title>. Children come after their parent, so one walk back up sums them."""
    words = [0] * len(d.names)
    kids: dict[int, list[int]] = {}
    said: dict[int, str] = {}
    for i in range(len(d.names) - 1, -1, -1):
        if i < len(d.kinds) and d.kinds[i] == 3:
            t = norm(d.text(d.values[i]) if i < len(d.values) else "")
            words[i] = len(t)
            a = _text_holder(d, i)
            if a >= 0:
                said[a] = norm(f"{t} {said.get(a, '')}")
        a = d.up(i)
        if a >= 0 and d.tag(i) not in ("STYLE", "SCRIPT"):
            # A title names its parent (an svg icon) and is not words it shows.
            words[a] += words[i] if d.tag(i) != "TITLE" else 0
            if i < len(d.kinds) and d.kinds[i] == 1:
                kids.setdefault(a, []).append(i)
    # Gathered last to first: each parent's children back in document order.
    for children in kids.values():
        children.reverse()
    return words, kids, said


def _text_holder(d: _Document, i: int) -> int:
    """The svg <text> or <title> a text node is words of, at most three steps up; below 0 for none."""
    a = d.up(i)
    for _ in range(3):
        if a < 0 or d.tag(a) in ("TEXT", "TITLE"):
            return a
        a = d.up(a)
    return -1


def _icons(d: _Document, words: list[int], kids: dict[int, list[int]], said: dict[int, str]) -> dict[int, str]:
    """What an icon is called (data-icon, svg <use href="#icon-trash">, an svg's <title>, an image's alt or file
    name, a CSS image's file name), given to the elements up to four over it; "" for a drawing with no such word."""
    icon: dict[int, str] = {}
    for i in range(len(d.names)):
        tag = d.tag(i)
        found = d.attrs_of(i)
        word = found.get("data-icon", "")
        if not word and tag == "USE":
            word = (found.get("href") or found.get("xlink:href") or "").rsplit("#", 1)[-1]
        if not word and tag == "SVG":
            word = next((said.get(c, "") for c in kids.get(i, []) if d.tag(c) == "TITLE"), "")
        if not word and tag == "IMG":
            word = found.get("alt", "") or _picture_name(f"url({found.get('src', '')})")
        painted = (_picture_name(d.style[i][3]) or _picture_name(d.style[i][4])) if i in d.style and not words[i] else ""
        if not word:
            word = painted
        if not word and tag not in ("SVG", "IMG", "I") and not painted:
            continue
        # A file or id word must read as words; a title or alt is the page's own words.
        word = word if _readable(word) or (tag in ("SVG", "IMG") and " " in word) else ""
        a = i
        for _ in range(5):
            if a < 0:
                break
            if not icon.get(a):
                icon[a] = word
            a = d.up(a)
    return icon


def _places(d: _Document, out: dict) -> None:
    """Where each node of the page itself stands down the document, text included, for the state to show what is
    on the screen when the page is too long for one look."""
    for i, k in d.box.items():
        if i < len(d.backend) and k < len(d.bounds) and len(d.bounds[k]) == 4 and d.bounds[k][3] > 0:
            out["y"][d.backend[i]] = d.bounds[k][1]


def _clickables(d: _Document, icon: dict[int, str], out: dict, kids: dict[int, list[int]]) -> dict[int, int]:
    """Each element drawn: clickable by a pointer cursor, a box that scrolls by itself, a field's type, a text
    area, a frame from another site, a nameless control's words, a knob's size. Gives each element under a pointer
    cursor the outermost element of that cursor it sits in."""
    outer: dict[int, int] = {}
    for i, k in d.box.items():
        if i >= len(d.kinds) or d.kinds[i] != 1:
            continue
        cursor, overflow, seen = d.style[i][:3]
        b = d.bounds[k] if k < len(d.bounds) else [0, 0, 0, 0]
        if seen == "hidden" or not (b[2] > 0 and b[3] > 0):
            continue
        name, backend = d.tag(i), d.backend[i]
        if cursor == "pointer" and name not in POINTER_SKIP:
            up = d.styled(d.up(i))
            if up < 0 or d.style[up][0] != "pointer":
                out["click"][backend] = True
                outer[i] = i
            elif up in outer:
                outer[i] = outer[up]
        if overflow in ("auto", "scroll", "overlay") and k < len(d.scrolls) and k < len(d.clients):
            whole, inside = d.scrolls[k], d.clients[k]
            if len(whole) == 4 and len(inside) == 4 and inside[3] > 40 and whole[3] > inside[3] + 8:
                down = whole[1] / max(1.0, whole[3] - inside[3])
                out["scroll"][backend] = ("at the top" if down < 0.02 else "at the end" if down > 0.98
                                          else f"{round(down * 100)}% down")
        found = d.attrs_of(i)
        if name == "INPUT" and found.get("type", "").lower() in SET_BY_VALUE:
            out["type"][backend] = found["type"].lower()
        if name == "SELECT" and "multiple" in found:
            out["type"][backend] = "multiple"
        if name == "TEXTAREA":
            out["area"][backend] = True
        if name in ("IFRAME", "FRAME") and b[2] >= 20 and b[3] >= 20 and i not in d.inner:
            # A frame shown whose document this snapshot does not hold: from another site, in its own process.
            out["frame"][backend] = urlsplit(found.get("src", "")).hostname or "?"
        hint = _hint(found, i in icon, icon.get(i, ""))
        if hint:
            out["hint"][backend] = norm(hint)[:40]
        tests = " ".join(found.get(a, "") for a in TEST_IDS).strip()
        if tests and _readable(tests):
            # A control drawn round a part that carries the test id (a like's count and heart in a focusable box, or
            # under one pointer cursor) goes by it.
            for top in {outer.get(i, i), d.up(i) if kids.get(d.up(i)) == [i] else i} - {i}:
                had = out["hint"].get(d.backend[top], "")
                out["hint"][d.backend[top]] = norm(f"{' '.join(ID_PARTS.split(tests))} {had}")[:40]
        if b[2] <= SMALL and b[3] <= SMALL:
            # Small enough to be a knob or an icon: one with no name is still shown when it can be focused.
            out["small"][backend] = True
    return outer


def _hint(found: dict, is_icon: bool, icon: str) -> str:
    """The words of a control with no name: its tooltip; else what names its icon, then the words of its id, its test
    id and its class (browser-use shows a control's id and class to the model), each only when it adds a word; with
    "· on" when only its class says it is on."""
    hint = next((found[a] for a in HINT_ATTRS if found.get(a, "").strip()), "")
    if not hint:
        ident = found.get("id", "")
        tests = " ".join(found.get(a, "") for a in TEST_IDS)
        chunks = [icon, " ".join(ID_PARTS.split(ident)) if _readable(ident) else "",
                  " ".join(ID_PARTS.split(tests)) if _readable(tests.strip()) else "",
                  *(w for w in re.split(r"\s+", found.get("class", "")) if _readable(w))]
        had: set[str] = set()
        kept = []
        for chunk in chunks:
            chunk = " ".join(w for w in chunk.split() if w.lower() not in had)
            mine = set(re.split(r"[\s_-]+", chunk.lower())) - {""}
            if mine and not mine <= had:
                kept.append(chunk)
                had |= mine
        hint = " ".join(kept[:3]) or ("icon" if is_icon else "")
    if ON_CLASS.search(found.get("class", "")):
        hint = f"{hint} · on".strip(" ·")
    return hint


def _parts(d: _Document, outer: dict[int, int], words: list[int], kids: dict[int, list[int]], icon: dict[int, str],
           out: dict) -> None:
    """Short parts side by side under a pointer cursor (Reply and Forward in one bar, a star and a bin on a row):
    each a clickable of its own, which keeps what the clickable round it is (`outer`: its class, test id and id
    reach the gate). The clickable round them stays when it shows more than they do. An icon beside its one label
    is one control."""
    for i, top in outer.items():
        parts = [c for c in kids.get(i, []) if d.shown(c) and d.tag(c) not in POINTER_SKIP and (words[c] or c in icon)]
        if not 2 <= len(parts) <= PARTS_MAX or any(words[c] > PART_WORDS for c in parts):
            continue
        if sum(1 for c in parts if words[c]) == 1:
            continue
        boxes = [d.shown(c) for c in parts]
        if not all(min(p[1] + p[3], q[1] + q[3]) - max(p[1], q[1]) >= 0.5 * min(p[3], q[3])
                   and (p[0] + p[2] <= q[0] + 1 or q[0] + q[2] <= p[0] + 1) for p, q in pairwise(boxes)):
            continue
        for c in parts:
            out["click"][d.backend[c]] = True
            out["outer"][d.backend[c]] = d.backend[top]
        if words[top] == sum(words[c] for c in parts):
            out["click"].pop(d.backend[top], None)


def _drawings(d: _Document, kids: dict[int, list[int]], said: dict[int, str], out: dict) -> None:
    """Drawings in the document itself: an svg with its shapes (their centres from its top left), a canvas. One
    that is a control or holds one keeps the lines the tree gives it, with their names."""
    for i in d.box:
        tag, b = d.tag(i), d.shown(i)
        if not b or tag not in ("SVG", "CANVAS") or b[2] < 40 or b[3] < 40 or d.control(i) or d.holds_control(i, kids):
            continue
        # Inside another drawing or a control (a button whose face is a drawing): that one's line stands.
        a = d.up(i)
        while a >= 0 and d.tag(a) != "SVG" and not d.control(a):
            a = d.up(a)
        if a >= 0:
            continue
        shapes = []
        stack = deque(kids.get(i, []) if tag == "SVG" else [])
        while stack and len(shapes) < SHAPES_MAX:
            c = stack.popleft()
            kind, s = d.tag(c).lower(), d.shown(c)
            if kind in ("g", "a", "svg", "switch"):
                stack.extendleft(reversed(kids.get(c, [])))
                continue
            if kind not in SHAPES or not s:
                continue
            fill, stroke = d.style[c][6], d.style[c][7]
            paint = fill if fill not in ("", "none") and "url(" not in fill else stroke
            shapes.append({"id": d.backend[c], "kind": kind, "colour": colour(paint), "words": said.get(c, ""),
                           "x": s[0] + s[2] / 2 - b[0], "y": s[1] + s[3] / 2 - b[1], "w": s[2], "h": s[3]})
        out["drawn"][d.backend[i]] = {"kind": tag.lower(), "w": b[2], "h": b[3], "y": b[1], "shapes": shapes}


def _tiles(d: _Document, words: list[int], kids: dict[int, list[int]], icon: dict[int, str], out: dict) -> None:
    """Rows of colour boxes with no words (swatches, tiles picked by their colour): two or more of a size."""
    drawn = out["drawn"]
    for children in kids.values():
        tiles = [c for c in children if d.shown(c) and not words[c] and not kids.get(c) and c not in icon
                 and not d.control(c) and d.tag(c) not in POINTER_SKIP and d.tag(c) not in ("IMG", "CANVAS", "SVG")
                 and colour(d.style[c][5]) and 6 <= d.shown(c)[2] <= 200 and 6 <= d.shown(c)[3] <= 200]
        if len(tiles) < 2 or len(drawn) >= DRAWN_MAX:
            continue
        sizes = [d.shown(c)[2] * d.shown(c)[3] for c in tiles]
        if max(sizes) > 2 * min(sizes):
            continue
        for c in tiles:
            s = d.shown(c)
            drawn[d.backend[c]] = {"kind": "box", "colour": colour(d.style[c][5]), "w": s[2], "h": s[3], "y": s[1]}
