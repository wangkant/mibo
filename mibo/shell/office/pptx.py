"""PowerPoint decks: made from Markdown the model writes, and changed by exact replacement.

The Markdown: a "#" or "##" line starts a slide and is its title; "-" items are its points, indented for
sub-points, and "1." items are numbered; plain lines are paragraphs; "###" lines are bold lines inside the slide;
a Markdown table becomes a table; "> " lines are the slide's speaker notes. The first slide with no more than two
short plain lines under its title is the cover, and a later slide with a title and nothing else is a section divider.

Every deck is built on one theme of its own: 16:9, a deep slate and teal palette with one amber accent, Segoe UI
for Latin text and Microsoft YaHei for Chinese, and four layouts (cover, section, content, table) that share one
title position, one margin and one slide-number mark. Text stays in placeholders and tables are real tables, so
the deck is edited in PowerPoint like any other.

Nothing runs off a slide. Text is measured before it is set: an East Asian character is as wide as the font size,
any other character half that, and a line holds 85% of the box's width in those units. A slide's points are set at
20, 18, 16 or 14 pt, the largest size at which they fit; points that do not fit at 14 pt continue on further slides
with the same title, packed at 18 pt and never leaving a sub-point apart from its parent where that can be helped.
A table is set at 16, 14 or 12 pt the same way; one that does not fit at 12 pt continues on further slides with
its header row repeated, packed at 14 pt.
"""
from __future__ import annotations

import copy
import io
import math
import re
import unicodedata
import zipfile
from dataclasses import dataclass, field

from lxml import etree
from pptx import Presentation
from pptx.enum.dml import MSO_THEME_COLOR
from pptx.enum.lang import MSO_LANGUAGE_ID
from pptx.enum.shapes import MSO_SHAPE_TYPE, PP_PLACEHOLDER
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.exc import PackageNotFoundError
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.oxml import parse_xml
from pptx.oxml.ns import nsdecls, qn
from pptx.text.text import _Run
from pptx.util import Emu, Inches, Pt

# ---------------------------------------------------------------- the theme

PALETTE = {
    "dk1": "1F2A30",      # body text
    "lt1": "FFFFFF",
    "dk2": "17323D",      # titles, the cover and section background, the table header
    "lt2": "EEF2F3",      # banded table rows
    "accent1": "2B7A78",  # bullets
    "accent2": "D9893A",  # the one warm accent: section numbers and the dot beside the slide number
    "accent3": "5E7380",
    "accent4": "9DBFBC",  # subtitles on the dark slides
    "accent5": "B4583F",
    "accent6": "7A8C99",
    "hlink": "2B7A78",
    "folHlink": "5E7380",
}
HEAD_FONT = BODY_FONT = "Segoe UI"
EAST_ASIAN_FONT = "Microsoft YaHei"
CODE_FONT = "Consolas"

WIDE, HIGH = Emu(12192000), Emu(6858000)  # 13.333 in by 7.5 in
# Where things sit, in inches: left, top, width, height.
TITLE = (0.7, 0.5, 11.933, 1.1)
BODY = (0.7, 1.8, 11.933, 4.95)
NUMBER = (12.18, 6.88, 0.5, 0.32)
DOT = (12.03, 6.985, 0.11, 0.11)
COVER_TITLE = (0.9, 1.9, 7.4, 2.3)
COVER_SUB = (0.9, 4.4, 7.4, 1.5)
SECTION_NO = (0.9, 1.5, 4.0, 1.3)
SECTION_TITLE = (0.9, 2.9, 7.4, 2.6)
RING = (8.55, 1.6, 4.3, 4.3)
RING_DOT = (9.04, 2.09, 0.28, 0.28)  # on the ring, up and to the left of its centre
GAP = 0.25  # between a slide's text and its table

TITLE_SIZES = (32, 28, 24, 20)
COVER_SIZES = (40, 36, 32, 28)
SUB_SIZES = (20, 18, 16)
BODY_SIZES = (20, 18, 16, 14)
TABLE_SIZES = (16, 14, 12)
BODY_PACKED, TABLE_PACKED = 18, 14
FILL = 0.85          # the share of a line's width that is counted on, for word wrapping and wide Latin letters
LINE = 1.35       # a line's height as a multiple of its font size, for these fonts at single spacing
SPACE_BEFORE = (10, 4)  # points before a top-level paragraph, and before a sub-point
INDENT = (0.3, 0.65, 1.0, 1.3, 1.6)  # inches from the box's edge to each level's text
INSET = (0.1, 0.05)  # a text box's own inner margin, left and right, top and bottom
CELL = (0.12, 0.06)  # a table cell's inner margin

# ---------------------------------------------------------------- reading the Markdown

_INLINE = re.compile(r"(\*\*\*.+?\*\*\*|\*\*.+?\*\*|`[^`]+`|\[[^\]]+\]\([^)\s]+\)|\*[^*\s][^*]*?\*)")
_HEADING = re.compile(r"(#{1,6})\s+(.*)")
_BULLET = re.compile(r"[-*+•]\s+(.*)")
_NUMBERED = re.compile(r"(\d+)[.)]\s+(.*)")
_RULE = re.compile(r"\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?")
_CJK = re.compile(r"[　-〿㐀-鿿豈-﫿＀-￯]")
_NUMERIC = re.compile(r"[+\-−]?[¥$€£]?\d[\d,]*(\.\d+)?\s*(%|‰|万|亿|元|个|人|次|k|K|M|B)?")
# A section title that already carries its own number gets no big number above it.
_NUMBERED_TITLE = re.compile(r"(第[一二三四五六七八九十百\d]+[部分章节篇]|[一二三四五六七八九十]+[、.．]|\d+[、.．\s]|"
                             r"(Part|Chapter|Section)\s+\w+)", re.IGNORECASE)


@dataclass
class Seg:
    """A stretch of a line with one look."""
    text: str
    bold: bool = False
    italic: bool = False
    code: bool = False
    link: str = ""


@dataclass
class Para:
    kind: str  # "point", "number", "line", "head" or "code"
    level: int
    segs: list[Seg]
    number: int = 0


@dataclass
class Table:
    rows: list[list[list[Seg]]]
    align: list[str]


@dataclass
class Source:
    """One slide as written: a title, its paragraphs and tables in order, and its notes."""
    title: list[Seg]
    blocks: list = field(default_factory=list)
    notes: list[list[Seg]] = field(default_factory=list)


def _segs(text: str) -> list[Seg]:
    out = []
    for part in _INLINE.split(text):
        if not part:
            continue
        if part.startswith("***") and part.endswith("***") and len(part) > 6:
            out.append(Seg(part[3:-3], bold=True, italic=True))
        elif part.startswith("**") and part.endswith("**") and len(part) > 4:
            out.append(Seg(part[2:-2], bold=True))
        elif part.startswith("`") and len(part) > 2:
            out.append(Seg(part[1:-1], code=True))
        elif part.startswith("[") and (link := re.fullmatch(r"\[([^\]]+)\]\(([^)\s]+)\)", part)):
            out.append(Seg(link[1], link=link[2]))
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            out.append(Seg(part[1:-1], italic=True))
        else:
            out.append(Seg(part))
    return out


def _plain(segs: list[Seg]) -> str:
    return "".join(seg.text for seg in segs)


def _cells(row: str) -> list[str]:
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", row.strip().strip("|"))]


def _alignment(rule: str) -> list[str]:
    out = []
    for cell in _cells(rule):
        out.append("c" if cell.startswith(":") and cell.endswith(":") else "r" if cell.endswith(":") else
                   "l" if cell.startswith(":") else "")
    return out


def parse(text: str) -> list[Source]:
    """The slides the Markdown describes."""
    slides: list[Source] = []
    now = None
    indents: list[int] = []  # the indents of the open list, outermost first
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    n = 0
    while n < len(lines):
        raw = lines[n].rstrip().replace("\t", "    ")
        bare = raw.strip()
        n += 1
        if not bare or re.fullmatch(r"[-*_]{3,}", bare):
            continue
        heading = _HEADING.fullmatch(bare)
        if heading and len(heading[1]) <= 2:
            now = Source(_segs(heading[2].rstrip("# ").strip()))
            slides.append(now)
            indents = []
            continue
        if now is None:
            # Text before the first heading: its first plain line is the title of the slide it makes.
            plain = not (heading or bare.startswith(("|", ">", "```")) or _BULLET.fullmatch(bare)
                         or _NUMBERED.fullmatch(bare))
            now = Source(_segs(bare) if plain else [])
            slides.append(now)
            if plain:
                continue
        if bare.startswith("```"):
            while n < len(lines) and not lines[n].strip().startswith("```"):
                if lines[n].strip():
                    now.blocks.append(Para("code", 0, [Seg(lines[n].rstrip(), code=True)]))
                n += 1
            n += 1
            continue
        if bare.startswith("|"):
            rows, align = [], []
            n -= 1
            while n < len(lines) and lines[n].strip().startswith("|"):
                row = lines[n].strip()
                if _RULE.fullmatch(row):
                    align = _alignment(row)
                else:
                    rows.append([_segs(cell) for cell in _cells(row)])
                n += 1
            width = max(len(row) for row in rows)
            rows = [row + [[] for _ in range(width - len(row))] for row in rows]
            now.blocks.append(Table(rows, (align + [""] * width)[:width]))
            indents = []
            continue
        if bare.startswith(">"):
            now.notes.append(_segs(bare.lstrip(">").strip()))
            continue
        item = _BULLET.fullmatch(bare)
        numbered = None if item else _NUMBERED.fullmatch(bare)
        if item or numbered:
            indent = len(raw) - len(raw.lstrip())
            while indents and indents[-1] > indent:
                indents.pop()
            if not indents or indent > indents[-1]:
                indents.append(indent)
            level = min(len(indents) - 1, len(INDENT) - 1)
            if item:
                now.blocks.append(Para("point", level, _segs(item[1])))
            else:
                now.blocks.append(Para("number", level, _segs(numbered[2]), int(numbered[1])))
            continue
        indents = []
        if heading:
            now.blocks.append(Para("head", 0, _segs(heading[2].rstrip("# ").strip())))
        else:
            now.blocks.append(Para("line", 0, _segs(bare)))
    return slides


# ---------------------------------------------------------------- measuring

def units(text: str) -> int:
    """The text's width in half-ems: an East Asian character (and an ambiguous one, which a Chinese font draws
    full width) counts two, any other one."""
    return sum(2 if unicodedata.east_asian_width(ch) in "WFA" else 1 for ch in text)


def lines(text: str, size: float, width: float) -> int:
    """How many lines `text` at `size` pt takes in a box `width` pt wide."""
    per_line = max(1, int(width * FILL / (size / 2)))
    return max(1, math.ceil(units(text) / per_line))


def _para_size(para: Para, size: int) -> int:
    return size if para.level == 0 else max(size - 2, 12)


def text_height(paras: list[Para], size: int, width_in: float) -> float:
    """The points that paragraphs set at `size` take in a text box `width_in` inches wide."""
    total = 0.0
    for para in paras:
        own = _para_size(para, size)
        indent = INDENT[para.level] if para.kind in ("point", "number") else 0
        width = (width_in - 2 * INSET[0] - indent) * 72
        total += lines(_plain(para.segs), own, width) * own * LINE + SPACE_BEFORE[para.level > 0]
    return total


def _room(height_in: float) -> float:
    return (height_in - 2 * INSET[1]) * 72


def _widths(table: Table, total: int) -> list[int]:
    """Column widths in EMU, in proportion to what each column holds, within bounds so no column is starved."""
    weights = [min(max(max(units(_plain(row[c])) for row in table.rows), 6), 40) for c in range(len(table.align))]
    widths = [int(total * w / sum(weights)) for w in weights]
    widths[-1] = total - sum(widths[:-1])
    return widths


def row_heights(table: Table, size: int, total: int) -> list[float]:
    """Each row's height in points at `size`, in a table `total` EMU wide."""
    widths = _widths(table, total)
    out = []
    for row in table.rows:
        tallest = max(lines(_plain(cell), size, (Emu(w).inches - 2 * CELL[0]) * 72)
                      for cell, w in zip(row, widths))
        out.append(tallest * size * LINE + 2 * CELL[1] * 72)
    return out


# ---------------------------------------------------------------- fitting slides

def _cut(segs: list[Seg], start: int, end: int) -> list[Seg]:
    """The characters start..end of the line, each stretch keeping its look."""
    out, at = [], 0
    for seg in segs:
        a, b = max(start - at, 0), min(end - at, len(seg.text))
        if a < b:
            out.append(Seg(seg.text[a:b], seg.bold, seg.italic, seg.code, seg.link))
        at += len(seg.text)
    return out


def _split_para(para: Para, size: int, width_in: float, height: float) -> list[Para]:
    """A paragraph too long for a whole slide, as pieces that each fit: cut after sentences where it can be,
    and between characters where one sentence alone is too long."""
    text = _plain(para.segs)
    ends = [m.end() for m in re.finditer(r"[。！？；!?;](\s*)|[.](\s+)", text)] + [len(text)]

    def fits(a: int, b: int) -> bool:
        return text_height([Para(para.kind, para.level, _cut(para.segs, a, b))], size, width_in) <= height

    pieces, start = [], 0
    while start < len(text):
        end = start
        for stop in ends:
            if stop > end and fits(start, stop):
                end = stop
            elif stop > end:
                break
        if end == start:
            end = start + 1
            while end < len(text) and fits(start, end + 1):
                end += 1
        pieces.append(Para(para.kind, para.level, _cut(para.segs, start, end), para.number))
        start = end
        while start < len(text) and text[start] == " ":
            start += 1
    return pieces


def fit_text(paras: list[Para], width_in: float, height_in: float) -> list[tuple[list[Para], int]]:
    """The paragraphs as slides' worth, each with the size it is set at (see the module's rule)."""
    room = _room(height_in)
    for size in BODY_SIZES:
        if text_height(paras, size, width_in) <= room:
            return [(paras, size)]
    queue = []
    for para in paras:
        queue.extend(_split_para(para, BODY_PACKED, width_in, room)
                     if text_height([para], BODY_PACKED, width_in) > room else [para])
    chunks, chunk = [], []
    while queue:
        para = queue.pop(0)
        if not chunk or text_height(chunk + [para], BODY_PACKED, width_in) <= room:
            chunk.append(para)
            continue
        # A sub-point does not start a slide: its parent and earlier siblings move along with it, as long as
        # something is left behind.
        carry = []
        if para.level > 0:
            back = len(chunk)
            while back > 0 and chunk[back - 1].level > 0:
                back -= 1
            if back > 1:
                carry, chunk = chunk[back - 1:], chunk[:back - 1]
        chunks.append(chunk)
        chunk = []
        queue[:0] = carry + [para]
    chunks.append(chunk)
    return [(c, BODY_PACKED) for c in chunks]


def fit_table(table: Table, total: int, height_in: float) -> list[tuple[Table, int]]:
    """The table as slides' worth, each with the size it is set at (see the module's rule)."""
    room = height_in * 72
    for size in TABLE_SIZES:
        if sum(row_heights(table, size, total)) <= room:
            return [(table, size)]
    heights = row_heights(table, TABLE_PACKED, total)
    parts, rows, used = [], [], heights[0]
    for row, height in zip(table.rows[1:], heights[1:]):
        if rows and used + height > room:
            parts.append(rows)
            rows, used = [], heights[0]
        rows.append(row)
        used += height
    parts.append(rows)
    return [(Table([table.rows[0]] + part, table.align), TABLE_PACKED) for part in parts]


@dataclass
class Page:
    """One slide to make: a title, text above a table, the table, text below it, and the sizes they take."""
    title: list[Seg]
    before: list[Para] = field(default_factory=list)
    table: Table | None = None
    after: list[Para] = field(default_factory=list)
    text_size: int = BODY_SIZES[0]
    table_size: int = TABLE_SIZES[0]


def pages(source: Source) -> list[Page]:
    """The slides one written slide becomes: one table to a slide, and long content continued."""
    # (text before, table, text after): text goes with the table after it, and text after the last table with that.
    groups, text = [], []
    for block in source.blocks:
        if isinstance(block, Table):
            groups.append((text, block, []))
            text = []
        else:
            text.append(block)
    if text and groups:
        groups[-1] = (groups[-1][0], groups[-1][1], text)
    elif text:
        groups.append((text, None, []))
    width_in, height_in = BODY[2], BODY[3]
    total = Inches(width_in)
    out = []
    for before, table, after in groups:
        if table is None:
            out.extend(Page(source.title, before=chunk, text_size=size)
                       for chunk, size in fit_text(before, width_in, height_in))
            continue
        page = _together(source.title, before, table, after)
        if page:
            out.append(page)
            continue
        out.extend(Page(source.title, before=chunk, text_size=size)
                   for chunk, size in fit_text(before, width_in, height_in) if before)
        out.extend(Page(source.title, table=part, table_size=size) for part, size in fit_table(table, total, height_in))
        out.extend(Page(source.title, after=chunk, text_size=size)
                   for chunk, size in fit_text(after, width_in, height_in) if after)
    return out


def _together(title: list[Seg], before: list[Para], table: Table, after: list[Para]) -> Page | None:
    """Text and a table on one slide, at the largest pair of sizes at which all of it fits; None if it does not."""
    width_in, room = BODY[2], BODY[3] * 72
    total = Inches(width_in)
    for text_size, table_size in ((20, 16), (18, 16), (18, 14), (16, 14), (16, 12), (14, 12)):
        used = sum(row_heights(table, table_size, total))
        for paras in (before, after):
            if paras:
                used += text_height(paras, text_size, width_in) + 2 * INSET[1] * 72 + GAP * 72
        if used <= room:
            return Page(title, before, table, after, text_size, table_size)
    return None


def title_size(segs: list[Seg], box: tuple, sizes: tuple) -> int:
    """The largest size at which the title fits its box; the smallest when none does."""
    width, room = (box[2] - 2 * INSET[0]) * 72, _room(box[3])
    for size in sizes:
        if lines(_plain(segs), size, width) * size * LINE <= room:
            return size
    return sizes[-1]


# ---------------------------------------------------------------- the deck's frame

def _xfrm(shape, box: tuple) -> None:
    shape.left, shape.top, shape.width, shape.height = (Inches(v) for v in box)


def _style(placeholder, anchor: str, size: int, color: str, bold: bool = False, align: str = "l",
           font: str = "+mn") -> None:
    """The placeholder's look as its layout gives it: anchoring, alignment, size, color and weight of level 1."""
    body = placeholder._element.txBody
    pr = body.find(qn("a:bodyPr"))
    pr.attrib.clear()
    pr.set("wrap", "square")
    pr.set("anchor", anchor)
    old = body.find(qn("a:lstStyle"))
    style = parse_xml(
        f'<a:lstStyle {nsdecls("a")}><a:lvl1pPr marL="0" indent="0" algn="{align}"><a:buNone/>'
        f'<a:defRPr sz="{size * 100}" b="{int(bold)}" cap="none">{_fill(color)}'
        f'<a:latin typeface="{font}-lt"/><a:ea typeface="{font}-ea"/></a:defRPr></a:lvl1pPr></a:lstStyle>')
    body.replace(old, style)


def _fill(color: str) -> str:
    """A solidFill of a scheme color ("tx2") or a scheme color softened ("tx1/60")."""
    if "/" in color:
        name, keep = color.split("/")
        return (f'<a:solidFill><a:schemeClr val="{name}"><a:lumMod val="{int(keep) * 1000}"/>'
                f'<a:lumOff val="{(100 - int(keep)) * 1000}"/></a:schemeClr></a:solidFill>')
    return f'<a:solidFill><a:schemeClr val="{color}"/></a:solidFill>'


def _level(n: int, size: int, color: str, bullet: str, bullet_color: str) -> str:
    left = Inches(INDENT[min(n, len(INDENT) - 1)])
    hang = Inches(INDENT[0]) if n == 0 else Inches(INDENT[1] - INDENT[0])
    before = SPACE_BEFORE[n > 0] * 100
    return (f'<a:lvl{n + 1}pPr marL="{left}" indent="{-hang}" algn="l" defTabSz="457200" rtl="0" eaLnBrk="1" '
            f'latinLnBrk="0" hangingPunct="1"><a:lnSpc><a:spcPct val="100000"/></a:lnSpc>'
            f'<a:spcBef><a:spcPts val="{before}"/></a:spcBef><a:buClr><a:schemeClr val="{bullet_color}"/></a:buClr>'
            f'<a:buFont typeface="Arial"/><a:buChar char="{bullet}"/>'
            f'<a:defRPr sz="{size * 100}" kern="1200">{_fill(color)}<a:latin typeface="+mn-lt"/>'
            f'<a:ea typeface="+mn-ea"/><a:cs typeface="+mn-cs"/></a:defRPr></a:lvl{n + 1}pPr>')


def _master_styles(master) -> None:
    styles = master._element.find(qn("p:txStyles"))
    title = parse_xml(
        f'<p:titleStyle {nsdecls("a", "p")}><a:lvl1pPr algn="l" defTabSz="457200" rtl="0" eaLnBrk="1" '
        f'latinLnBrk="0" hangingPunct="1"><a:lnSpc><a:spcPct val="100000"/></a:lnSpc><a:spcBef><a:spcPct val="0"/>'
        f'</a:spcBef><a:buNone/><a:defRPr sz="{TITLE_SIZES[0] * 100}" b="1" kern="1200">{_fill("tx2")}'
        f'<a:latin typeface="+mj-lt"/><a:ea typeface="+mj-ea"/><a:cs typeface="+mj-cs"/></a:defRPr></a:lvl1pPr>'
        f'</p:titleStyle>')
    top = BODY_SIZES[0]
    levels = [_level(0, top, "tx1", "•", "accent1")] + [
        _level(n, top - 2, "tx1/75", "–" if n % 2 else "•", "accent3") for n in range(1, 9)]
    body = parse_xml(f'<p:bodyStyle {nsdecls("a", "p")}>{"".join(levels)}</p:bodyStyle>')
    styles.replace(styles.find(qn("p:titleStyle")), title)
    styles.replace(styles.find(qn("p:bodyStyle")), body)


def _retheme(part) -> None:
    """The theme part with this deck's colors and fonts, Chinese text given its typeface outright."""
    a = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    root = etree.fromstring(part.blob)
    root.set("name", "Mibo")
    scheme = root.find(f".//{a}clrScheme")
    scheme.set("name", "Mibo")
    for name, value in PALETTE.items():
        slot = scheme.find(a + name)
        for child in list(slot):
            slot.remove(child)
        etree.SubElement(slot, a + "srgbClr", val=value)
    fonts = root.find(f".//{a}fontScheme")
    fonts.set("name", "Mibo")
    for tag, latin in (("majorFont", HEAD_FONT), ("minorFont", BODY_FONT)):
        holder = fonts.find(a + tag)
        holder.find(a + "latin").set("typeface", latin)
        holder.find(a + "ea").set("typeface", EAST_ASIAN_FONT)
        for script in holder.findall(a + "font"):
            if script.get("script") == "Hans":
                script.set("typeface", EAST_ASIAN_FONT)
            elif script.get("script") == "Hant":
                script.set("typeface", "Microsoft JhengHei")
    part._blob = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def _mark(layout, name: str, box: tuple, fill: str = "", line: str = "") -> None:
    """A circle drawn on the layout, so it is part of the frame and not of any slide's content: filled with a
    scheme color, or outlined in one ("accent4/40" is that color at 40% opacity)."""
    tree = layout.shapes._spTree
    ids = [int(e.get("id")) for e in tree.iter(qn("p:cNvPr"))]
    x, y, w, h = (Inches(v) for v in box)

    def color(spec: str) -> str:
        name, _, alpha = spec.partition("/")
        inner = f'<a:alpha val="{int(alpha) * 1000}"/>' if alpha else ""
        return f'<a:solidFill><a:schemeClr val="{name}">{inner}</a:schemeClr></a:solidFill>'

    sp = parse_xml(
        f'<p:sp {nsdecls("a", "p")}><p:nvSpPr><p:cNvPr id="{max(ids) + 1}" name="{name}"/><p:cNvSpPr/><p:nvPr/>'
        f'</p:nvSpPr><p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm>'
        f'<a:prstGeom prst="ellipse"><a:avLst/></a:prstGeom>{color(fill) if fill else "<a:noFill/>"}'
        f'<a:ln w="{Pt(1.5)}">{color(line) if line else "<a:noFill/>"}</a:ln></p:spPr></p:sp>')
    # Drawn first, so it sits behind the placeholders.
    tree.insert(2, sp)


def _deck():
    """A presentation holding this deck's theme, master and four layouts, and no slides."""
    deck = Presentation()
    deck.slide_width, deck.slide_height = WIDE, HIGH
    deck.part._element.find(qn("p:sldSz")).attrib.pop("type", None)
    # The template's preview picture shows its own blank 4:3 slide; a deck with none gets a preview drawn by
    # whatever opens it.
    # Its printer settings came from the machine it was made on.
    package = deck.part.package
    for rid, rel in list(package._rels.items()):
        if rel.reltype == RT.THUMBNAIL:
            package.drop_rel(rid)
    for rid, rel in list(deck.part.rels.items()):
        if rel.reltype == RT.PRINTER_SETTINGS:
            deck.part.drop_rel(rid)
    master = deck.slide_master
    _retheme(master.part.part_related_by(RT.THEME))
    _retheme(deck.notes_master.part.part_related_by(RT.THEME))
    _master_styles(master)
    spots = {PP_PLACEHOLDER.TITLE: TITLE, PP_PLACEHOLDER.BODY: BODY, PP_PLACEHOLDER.SLIDE_NUMBER: NUMBER,
             PP_PLACEHOLDER.DATE: (0.7, 6.88, 3.0, 0.32), PP_PLACEHOLDER.FOOTER: (4.5, 6.88, 4.3, 0.32)}
    for placeholder in master.placeholders:
        _xfrm(placeholder, spots[placeholder.placeholder_format.type])
    _style(master.placeholders[0], "t", TITLE_SIZES[0], "tx2", bold=True, font="+mj")
    # The slide image on a notes page, shaped like the slide.
    for placeholder in deck.notes_master.placeholders:
        if placeholder.placeholder_format.type == PP_PLACEHOLDER.SLIDE_IMAGE:
            _xfrm(placeholder, (0.75, 0.75, 6.0, 3.375))

    layouts = list(deck.slide_layouts)
    keep = {"Cover": layouts[0], "Content": layouts[1], "Section": layouts[2], "Table": layouts[5]}
    for layout in layouts:
        if layout not in keep.values():
            deck.slide_layouts.remove(layout)
    for name, layout in keep.items():
        layout._element.cSld.set("name", name)
        for placeholder in list(layout.placeholders):
            kind = placeholder.placeholder_format.type
            if kind in (PP_PLACEHOLDER.DATE, PP_PLACEHOLDER.FOOTER) or (
                    kind == PP_PLACEHOLDER.SLIDE_NUMBER and name in ("Cover", "Section")):
                placeholder._element.getparent().remove(placeholder._element)
            elif kind == PP_PLACEHOLDER.SLIDE_NUMBER:
                _xfrm(placeholder, NUMBER)
                _style(placeholder, "ctr", 11, "tx1/60")
        if name in ("Cover", "Section"):
            layout.background.fill.solid()
            layout.background.fill.fore_color.theme_color = MSO_THEME_COLOR.TEXT_2
            _mark(layout, "Ring", RING, line="accent4/45")
            _mark(layout, "Dot", RING_DOT, fill="accent2")
        else:
            _mark(layout, "Dot", DOT, fill="accent2")
    title, sub = keep["Cover"].placeholders[0], keep["Cover"].placeholders[1]
    _xfrm(title, COVER_TITLE)
    _style(title, "b", COVER_SIZES[0], "bg1", bold=True, font="+mj")
    _xfrm(sub, COVER_SUB)
    _style(sub, "t", SUB_SIZES[0], "accent4")
    title, number = keep["Section"].placeholders[0], keep["Section"].placeholders[1]
    _xfrm(title, SECTION_TITLE)
    _style(title, "t", COVER_SIZES[0], "bg1", bold=True, font="+mj")
    _xfrm(number, SECTION_NO)
    _style(number, "b", 60, "accent2", bold=True, font="+mj")
    for name in ("Content", "Table"):
        _xfrm(keep[name].placeholders[0], TITLE)
        _style(keep[name].placeholders[0], "t", TITLE_SIZES[0], "tx2", bold=True, font="+mj")
    _xfrm(keep["Content"].placeholders[1], BODY)
    body = keep["Content"].placeholders[1]._element.txBody
    body.find(qn("a:bodyPr")).set("anchor", "t")
    return deck, keep


# ---------------------------------------------------------------- filling slides

def _write(paragraph, segs: list[Seg], size: int | None = None, bold: bool | None = None,
           color: MSO_THEME_COLOR | None = None) -> None:
    """The line's stretches as runs, each carrying its own look."""
    for seg in segs:
        run = paragraph.add_run()
        run.text = seg.text
        if _CJK.search(seg.text):
            # Proofing and line breaking follow the language the run is marked with.
            run.font.language_id = MSO_LANGUAGE_ID.SIMPLIFIED_CHINESE
        if seg.bold or bold:
            run.font.bold = True
        if seg.italic:
            run.font.italic = True
        if seg.code:
            run.font.name = CODE_FONT
        if seg.link:
            run.hyperlink.address = seg.link
        if size:
            run.font.size = Pt(size)
        if color is not None:
            run.font.color.theme_color = color


def _bullets(paragraph, para: Para, expected: dict, explicit: bool) -> None:
    """The paragraph's bullet: inherited from the layout for a point, numbered for a numbered item, none for a
    line. Outside a placeholder (`explicit`) nothing is inherited, so everything is written out."""
    pr = paragraph._p.get_or_add_pPr()
    if para.kind in ("point", "number"):
        paragraph.level = para.level
        if explicit:
            pr.set("marL", str(Inches(INDENT[para.level])))
            pr.set("indent", str(-Inches(INDENT[0] if para.level == 0 else INDENT[1] - INDENT[0])))
            pr.append(parse_xml(f'<a:spcBef {nsdecls("a")}><a:spcPts val="{SPACE_BEFORE[para.level > 0] * 100}"/>'
                                f'</a:spcBef>'))
            pr.append(parse_xml(f'<a:buClr {nsdecls("a")}><a:schemeClr val="accent1"/></a:buClr>'))
        if para.kind == "number":
            pr.append(parse_xml(f'<a:buFont {nsdecls("a")} typeface="+mj-lt"/>'))
            numbering = parse_xml(f'<a:buAutoNum {nsdecls("a")} type="arabicPeriod"/>')
            if para.number != expected.get(para.level, 1):
                numbering.set("startAt", str(para.number))
            pr.append(numbering)
            expected[para.level] = para.number + 1
        elif explicit:
            pr.append(parse_xml(f'<a:buFont {nsdecls("a")} typeface="Arial"/>'))
            pr.append(parse_xml(f'<a:buChar {nsdecls("a")} char="{"•" if para.level % 2 == 0 else "–"}"/>'))
    else:
        pr.set("marL", "0")
        pr.set("indent", "0")
        if explicit:
            pr.append(parse_xml(f'<a:spcBef {nsdecls("a")}><a:spcPts val="{SPACE_BEFORE[0] * 100}"/></a:spcBef>'))
        pr.append(parse_xml(f'<a:buNone {nsdecls("a")}/>'))
    if para.kind != "number":
        expected.clear()


def _text(frame, paras: list[Para], size: int, explicit: bool = False) -> None:
    frame.word_wrap = True
    expected: dict = {}
    for row, para in enumerate(paras):
        paragraph = frame.paragraphs[0] if row == 0 else frame.add_paragraph()
        _bullets(paragraph, para, expected, explicit)
        own = _para_size(para, size) - (2 if para.kind == "code" else 0)
        # Sizes the layout already gives are left to it.
        _write(paragraph, para.segs, size=own if explicit or size != BODY_SIZES[0] or para.kind == "code" else None,
               bold=para.kind == "head" or None)


def _number(slide, n: int) -> None:
    """The layout's slide-number placeholder brought onto the slide, showing the slide's number."""
    source = next(p for p in slide.slide_layout.placeholders
                  if p.placeholder_format.type == PP_PLACEHOLDER.SLIDE_NUMBER)
    sp = copy.deepcopy(source._element)
    tree = slide.shapes._spTree
    taken = max(int(e.get("id")) for e in tree.iter(qn("p:cNvPr")))
    sp.find(qn("p:nvSpPr")).find(qn("p:cNvPr")).set("id", str(taken + 1))
    pr = sp.find(qn("p:spPr"))
    for child in list(pr):
        pr.remove(child)
    sp.txBody.replace(sp.txBody.find(qn("a:lstStyle")), parse_xml(f'<a:lstStyle {nsdecls("a")}/>'))
    sp.txBody.find(qn("a:bodyPr")).attrib.clear()
    sp.find(".//" + qn("a:fld")).find(qn("a:t")).text = str(n)
    tree.append(sp)


def _title(slide, segs: list[Seg], box: tuple, sizes: tuple) -> None:
    if not segs:
        slide.shapes._spTree.remove(slide.shapes.title._element)
        return
    size = title_size(segs, box, sizes)
    _write(slide.shapes.title.text_frame.paragraphs[0], segs, size=None if size == sizes[0] else size)


def _drop(placeholder) -> None:
    placeholder._element.getparent().remove(placeholder._element)


def _table(slide, table: Table, size: int, top: int) -> int:
    """The table set on the slide from `top`; returns where it ends."""
    total = Inches(BODY[2])
    heights = row_heights(table, size, total)
    shape = slide.shapes.add_table(len(table.rows), len(table.align), Inches(BODY[0]), top, total,
                                   Pt(sum(heights)))
    grid = shape.table
    grid.first_row, grid.horz_banding = True, False
    for column, width in zip(grid.columns, _widths(table, total)):
        column.width = width
    for r, (row, height) in enumerate(zip(table.rows, heights)):
        grid.rows[r].height = Pt(height)
        for c, segs in enumerate(row):
            cell = grid.cell(r, c)
            cell.margin_left = cell.margin_right = Inches(CELL[0])
            cell.margin_top = cell.margin_bottom = Inches(CELL[1])
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.fill.solid()
            cell.fill.fore_color.theme_color = (MSO_THEME_COLOR.TEXT_2 if r == 0 else
                                                MSO_THEME_COLOR.BACKGROUND_2 if r % 2 == 0 else
                                                MSO_THEME_COLOR.BACKGROUND_1)
            paragraph = cell.text_frame.paragraphs[0]
            align = table.align[c] or ("r" if r and _NUMERIC.fullmatch(_plain(segs).strip()) else "l")
            paragraph.alignment = {"l": PP_ALIGN.LEFT, "r": PP_ALIGN.RIGHT, "c": PP_ALIGN.CENTER}[align]
            _write(paragraph, segs, size=size, bold=r == 0 or None,
                   color=MSO_THEME_COLOR.BACKGROUND_1 if r == 0 else MSO_THEME_COLOR.TEXT_1)
            if not segs:
                # An empty cell still carries the size, so its row is not taller than its neighbours.
                paragraph.font.size = Pt(size)
    return top + Pt(sum(heights))


def _page(deck, layouts, page: Page, n: int):
    slide = deck.slides.add_slide(layouts["Table" if page.table and not (page.before or page.after) else "Content"])
    _title(slide, page.title, TITLE, TITLE_SIZES)
    _number(slide, n)
    if page.table is None:
        _text(slide.placeholders[1].text_frame, page.before, page.text_size)
        return slide
    top = Inches(BODY[1])
    body = slide.placeholders[1] if (page.before or page.after) else None
    if page.before:
        height = Pt(text_height(page.before, page.text_size, BODY[2])) + Inches(2 * INSET[1])
        _xfrm(body, BODY)
        body.height = height
        _text(body.text_frame, page.before, page.text_size)
        top += height + Inches(GAP)
    end = _table(slide, page.table, page.table_size, top)
    if page.after:
        height = Pt(text_height(page.after, page.text_size, BODY[2])) + Inches(2 * INSET[1])
        if page.before:
            box = slide.shapes.add_textbox(Inches(BODY[0]), end + Inches(GAP), Inches(BODY[2]), height)
            _text(box.text_frame, page.after, page.text_size, explicit=True)
        else:
            _xfrm(body, BODY)
            body.top, body.height = end + Inches(GAP), height
            _text(body.text_frame, page.after, page.text_size)
    return slide


def _cover(deck, layouts, source: Source, size: int):
    slide = deck.slides.add_slide(layouts["Cover"])
    _title(slide, source.title, COVER_TITLE, COVER_SIZES)
    sub = slide.placeholders[1]
    if not source.blocks:
        _drop(sub)
        return slide
    for row, para in enumerate(source.blocks):
        paragraph = sub.text_frame.paragraphs[0] if row == 0 else sub.text_frame.add_paragraph()
        _write(paragraph, para.segs, size=None if size == SUB_SIZES[0] else size)
    return slide


def _section(deck, layouts, source: Source, n: int):
    slide = deck.slides.add_slide(layouts["Section"])
    _title(slide, source.title, SECTION_TITLE, COVER_SIZES)
    number = slide.placeholders[1]
    if _NUMBERED_TITLE.match(_plain(source.title)):
        _drop(number)
    else:
        number.text_frame.paragraphs[0].add_run().text = f"{n:02d}"
    return slide


def _notes(slide, notes: list[list[Seg]]) -> None:
    frame = slide.notes_slide.notes_text_frame
    for row, segs in enumerate(notes):
        _write(frame.paragraphs[0] if row == 0 else frame.add_paragraph(), segs)


def _subtitle_size(source: Source) -> int | None:
    """The size the cover's subtitle takes when the slide can be the cover: no more than two plain lines under the
    title, short enough to fit the subtitle at one of its sizes. None when the slide is not a cover."""
    if len(source.blocks) > 2 or not all(isinstance(b, Para) and b.kind == "line" for b in source.blocks):
        return None
    width = (COVER_SUB[2] - 2 * INSET[0]) * 72
    return next((s for s in SUB_SIZES if sum(lines(_plain(p.segs), s, width) for p in source.blocks) * s * LINE
                 <= _room(COVER_SUB[3])), None)


def make(text: str) -> bytes:
    """The deck that `text`, written as Markdown, describes."""
    sources = parse(text)
    if not sources:
        raise ValueError("The text is empty: write the deck as Markdown, a '# ' line for each slide's title "
                         "and '- ' lines for its points.")
    deck, layouts = _deck()
    sections = 0
    for index, source in enumerate(sources):
        if index == 0 and (size := _subtitle_size(source)):
            made = [_cover(deck, layouts, source, size)]
        elif not source.blocks:
            sections += 1
            made = [_section(deck, layouts, source, sections)]
        else:
            made = [_page(deck, layouts, page, len(deck.slides) + 1) for page in pages(source)]
        if source.notes:
            _notes(made[0], source.notes)
    # The file's properties: its title, and nothing of the library's template (its author, its dates), so the same
    # text makes the same deck.
    props = deck.core_properties
    props.title = _plain(sources[0].title)[:200]
    props.author = props.last_modified_by = props.comments = props.subject = props.keywords = ""
    props.revision = 1
    for tag in ("dcterms:created", "dcterms:modified", "cp:lastPrinted"):
        for found in props._element.findall(qn(tag)):
            props._element.remove(found)
    # The template's application properties describe a 4:3 deck from another program; these describe this one.
    notes = sum(slide.has_notes_slide for slide in deck.slides)
    deck.part.package.part_related_by(RT.EXTENDED_PROPERTIES)._blob = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Properties xmlns="http://schemas.openxmlformats.org/'
        'officeDocument/2006/extended-properties"><TotalTime>0</TotalTime><Application>Mibo</Application>'
        f'<PresentationFormat>Widescreen</PresentationFormat><Slides>{len(deck.slides)}</Slides>'
        f'<Notes>{notes}</Notes></Properties>').encode()
    out = io.BytesIO()
    deck.save(out)
    return out.getvalue()


# ---------------------------------------------------------------- an existing deck

def _open(data: bytes):
    try:
        return Presentation(io.BytesIO(data))
    except (zipfile.BadZipFile, KeyError, PackageNotFoundError, etree.XMLSyntaxError) as error:
        raise ValueError(f"The file is not a PowerPoint deck that can be opened ({error}).") from None


def summary(data: bytes) -> str:
    """The deck in a few words for the model."""
    count = len(_open(data).slides)
    return f"a PowerPoint deck of {count} slide{'' if count == 1 else 's'}"


def _frames(deck):
    """Every text frame of the deck that holds its words: shapes (inside groups too), table cells, and notes."""
    def within(shapes):
        for shape in shapes:
            if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                yield from within(shape.shapes)
            elif shape.has_text_frame:
                yield shape.text_frame
            elif shape.has_table:
                for row in shape.table.rows:
                    for cell in row.cells:
                        yield cell.text_frame
    for slide in deck.slides:
        yield from within(slide.shapes)
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
            yield slide.notes_slide.notes_text_frame


def _stretches(frame):
    """Each paragraph's runs, split where a line break or a field comes between them."""
    for paragraph in frame.paragraphs:
        group = []
        for child in paragraph._p:
            if child.tag == qn("a:r"):
                group.append(child)
            elif child.tag in (qn("a:br"), qn("a:fld")):
                if group:
                    yield group
                group = []
        if group:
            yield group


def _swap(runs, old: str, new: str, every: bool) -> None:
    """`old` replaced inside these runs: only the runs it touches change, and the text put in takes the look of
    the run where the match begins."""
    texts = [run.text for run in (_Run(r, None) for r in runs)]
    joined = "".join(texts)
    starts, at = [], joined.find(old)
    while at >= 0:
        starts.append(at)
        at = -1 if not every else joined.find(old, at + len(old))
    emptied = set()
    for a in reversed(starts):
        b, edges, pos = a + len(old), [], 0
        for t in texts:
            edges.append((pos, pos + len(t)))
            pos += len(t)
        first = next(k for k, (s, e) in enumerate(edges) if s <= a < e)
        last = next(k for k, (s, e) in enumerate(edges) if s < b <= e)
        if first == last:
            s = edges[first][0]
            texts[first] = texts[first][:a - s] + new + texts[first][b - s:]
        else:
            texts[first] = texts[first][:a - edges[first][0]] + new
            for k in range(first + 1, last):
                texts[k] = ""
                emptied.add(k)
            texts[last] = texts[last][b - edges[last][0]:]
            if not texts[last]:
                emptied.add(last)
        if not texts[first]:
            emptied.add(first)
    for k, (r, t) in enumerate(zip(runs, texts)):
        if k in emptied and not t and len(r.getparent().findall(qn("a:r"))) > 1:
            r.getparent().remove(r)
        else:
            _Run(r, None).text = t


def replaced(data: bytes, old: str, new: str, every: bool) -> bytes:
    """The deck with `old` replaced by `new`, exactly once unless `every`; ValueError says what went wrong."""
    old, new = old.strip("\r\n"), new.strip("\r\n")
    if not old:
        raise ValueError("old_string is empty: give the exact text to replace.")
    if "\n" in old:
        raise ValueError("old_string spans more than one paragraph: in a deck, replace the text of one paragraph, "
                         "one table cell or one note at a time.")
    if "\n" in new:
        raise ValueError("new_string holds a line break: a replacement stays inside one paragraph; to add points, "
                         "write the deck again with write_file.")
    deck = _open(data)
    groups = [g for frame in _frames(deck) for g in _stretches(frame)
              if old in "".join(_Run(r, None).text for r in g)]
    count = sum("".join(_Run(r, None).text for r in g).count(old) for g in groups)
    if count == 0:
        raise ValueError("old_string was not found in the deck (it must match the text of one paragraph, table cell "
                         "or note exactly, without the line numbers read_file shows).")
    if count > 1 and not every:
        raise ValueError(f"old_string is in the deck {count} times: give more of the text around it so it is found "
                         "once, or set replace_all to change every one.")
    for group in groups:
        _swap(group, old, new, every)
    out = io.BytesIO()
    deck.save(out)
    return out.getvalue()
