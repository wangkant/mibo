"""What a deck's Markdown says, and how it is shared out over slides so nothing runs off one (pptx.py sets it).

The Markdown: a "#" or "##" line starts a slide and is its title; "-" items are its points, indented for
sub-points, and "1." items are numbered; plain lines are paragraphs; "###" lines are bold lines inside the slide;
a Markdown table becomes a table; "> " lines are the slide's speaker notes.

Text is measured before it is set: an East Asian character is as wide as the font size, any other character half
that, and a line holds 85% of the box's width in those units. A slide's points are set at 20, 18, 16 or 14 pt, the
largest size at which they fit; points that do not fit at 14 pt continue on further slides with the same title,
packed at 18 pt and never leaving a sub-point apart from its parent where that can be helped. A table is set at 16,
14 or 12 pt the same way; one that does not fit at 12 pt continues on further slides with its header row repeated,
packed at 14 pt.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from pptx.util import Emu, Inches

from . import text_width

# Where the body sits, in inches: left, top, width, height.
BODY = (0.7, 1.8, 11.933, 4.95)
GAP = 0.25  # between a slide's text and its table

BODY_SIZES = (20, 18, 16, 14)
TABLE_SIZES = (16, 14, 12)
BODY_PACKED, TABLE_PACKED = 18, 14
FILL = 0.85          # the share of a line's width that is counted on, for word wrapping and wide Latin letters
LINE = 1.35       # a line's height as a multiple of its font size, for these fonts at single spacing
SPACE_BEFORE = (10, 4)  # points before a top-level paragraph, and before a sub-point
INDENT = (0.3, 0.65, 1.0, 1.3, 1.6)  # inches from the box's edge to each level's text
INSET = (0.1, 0.05)  # a text box's own inner margin, left and right, top and bottom
CELL = (0.12, 0.06)  # a table cell's inner margin
# Text and table sizes tried, largest first, when both share one slide.
TOGETHER = ((20, 16), (18, 16), (18, 14), (16, 14), (16, 12), (14, 12))

# ---------------------------------------------------------------- reading the Markdown

_INLINE = re.compile(r"(\*\*\*.+?\*\*\*|\*\*.+?\*\*|`[^`]+`|\[[^\]]+\]\([^)\s]+\)|\*[^*\s][^*]*?\*)")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_HEADING = re.compile(r"(#{1,6})\s+(.*)")
_BULLET = re.compile(r"[-*+•]\s+(.*)")
_NUMBERED = re.compile(r"(\d+)[.)]\s+(.*)")
_RULE = re.compile(r"\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?")
_BREAK = re.compile(r"[-*_]{3,}")
# Where a long paragraph may be cut: after a sentence's end.
_SENTENCE_END = re.compile(r"[。！？；!?;](\s*)|[.](\s+)")


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
        elif part.startswith("[") and (link := _LINK.fullmatch(part)):
            out.append(Seg(link[1], link=link[2]))
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            out.append(Seg(part[1:-1], italic=True))
        else:
            out.append(Seg(part))
    return out


def plain(segs: list[Seg]) -> str:
    return "".join(seg.text for seg in segs)


def _cells(row: str) -> list[str]:
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", row.strip().strip("|"))]


def _alignment(rule: str) -> list[str]:
    return ["c" if cell.startswith(":") and cell.endswith(":") else "r" if cell.endswith(":") else
            "l" if cell.startswith(":") else "" for cell in _cells(rule)]


def _read_code(lines: list[str], n: int, blocks: list) -> int:
    """The fenced block's lines from line `n` on, as code paragraphs; returns the line after its closing fence."""
    while n < len(lines) and not lines[n].strip().startswith("```"):
        if lines[n].strip():
            blocks.append(Para("code", 0, [Seg(lines[n].rstrip(), code=True)]))
        n += 1
    return n + 1


def _read_table(lines: list[str], n: int) -> tuple[Table, int]:
    """The table whose first row is line `n`, its rows padded to one width; and the line after it."""
    rows, align = [], []
    while n < len(lines) and lines[n].strip().startswith("|"):
        row = lines[n].strip()
        if _RULE.fullmatch(row):
            align = _alignment(row)
        else:
            rows.append([_segs(cell) for cell in _cells(row)])
        n += 1
    width = max(len(row) for row in rows)
    rows = [row + [[] for _ in range(width - len(row))] for row in rows]
    return Table(rows, (align + [""] * width)[:width]), n


def _list_item(raw: str, bare: str, indents: list[int]) -> Para | None:
    """The line as a point or a numbered item, its level found from `indents` (the open list's indents, outermost
    first, kept up to date here); None when it is not a list item."""
    item = _BULLET.fullmatch(bare)
    numbered = None if item else _NUMBERED.fullmatch(bare)
    if not (item or numbered):
        return None
    indent = len(raw) - len(raw.lstrip())
    while indents and indents[-1] > indent:
        indents.pop()
    if not indents or indent > indents[-1]:
        indents.append(indent)
    level = min(len(indents) - 1, len(INDENT) - 1)
    if item:
        return Para("point", level, _segs(item[1]))
    return Para("number", level, _segs(numbered[2]), int(numbered[1]))


def parse(text: str) -> list[Source]:
    """The slides the Markdown describes."""
    slides: list[Source] = []
    now = None
    indents: list[int] = []
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    n = 0
    while n < len(lines):
        raw = lines[n].rstrip().replace("\t", "    ")
        bare = raw.strip()
        n += 1
        if not bare or _BREAK.fullmatch(bare):
            continue
        heading = _HEADING.fullmatch(bare)
        if heading and len(heading[1]) <= 2:
            now = Source(_segs(heading[2].rstrip("# ").strip()))
            slides.append(now)
            indents = []
            continue
        if now is None:
            # Text before the first heading: its first plain line is the title of the slide it makes.
            titled = not (heading or bare.startswith(("|", ">", "```")) or _BULLET.fullmatch(bare)
                          or _NUMBERED.fullmatch(bare))
            now = Source(_segs(bare) if titled else [])
            slides.append(now)
            if titled:
                continue
        if bare.startswith("```"):
            n = _read_code(lines, n, now.blocks)
        elif bare.startswith("|"):
            table, n = _read_table(lines, n - 1)
            now.blocks.append(table)
            indents = []
        elif bare.startswith(">"):
            now.notes.append(_segs(bare.lstrip(">").strip()))
        elif item := _list_item(raw, bare, indents):
            now.blocks.append(item)
        elif heading:
            indents = []
            now.blocks.append(Para("head", 0, _segs(heading[2].rstrip("# ").strip())))
        else:
            indents = []
            now.blocks.append(Para("line", 0, _segs(bare)))
    return slides


# ---------------------------------------------------------------- measuring

# An ambiguous character counts as wide too: a Chinese font draws it full width.
_WIDE = "WFA"


def lines(text: str, size: float, width: float) -> int:
    """How many lines `text` at `size` pt takes in a box `width` pt wide."""
    per_line = max(1, int(width * FILL / (size / 2)))
    return max(1, math.ceil(text_width(text, _WIDE) / per_line))


def para_size(para: Para, size: int) -> int:
    """The size a paragraph is set at on a slide whose points are `size`: a sub-point two smaller."""
    return size if para.level == 0 else max(size - 2, 12)


def text_height(paras: list[Para], size: int, width_in: float) -> float:
    """The points that paragraphs set at `size` take in a text box `width_in` inches wide."""
    total = 0.0
    for para in paras:
        own = para_size(para, size)
        indent = INDENT[para.level] if para.kind in ("point", "number") else 0
        width = (width_in - 2 * INSET[0] - indent) * 72
        total += lines(plain(para.segs), own, width) * own * LINE + SPACE_BEFORE[para.level > 0]
    return total


def room(height_in: float) -> float:
    """The points of text a box `height_in` inches high holds inside its margins."""
    return (height_in - 2 * INSET[1]) * 72


def column_widths(table: Table, total: int) -> list[int]:
    """Column widths in EMU, in proportion to what each column holds, within bounds so no column is starved."""
    weights = [min(max(max(text_width(plain(row[c]), _WIDE) for row in table.rows), 6), 40)
               for c in range(len(table.align))]
    widths = [int(total * w / sum(weights)) for w in weights]
    widths[-1] = total - sum(widths[:-1])
    return widths


def row_heights(table: Table, size: int, total: int) -> list[float]:
    """Each row's height in points at `size`, in a table `total` EMU wide."""
    widths = column_widths(table, total)
    out = []
    for row in table.rows:
        tallest = max(lines(plain(cell), size, (Emu(w).inches - 2 * CELL[0]) * 72)
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
    text = plain(para.segs)
    ends = [m.end() for m in _SENTENCE_END.finditer(text)] + [len(text)]

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
    space = room(height_in)
    for size in BODY_SIZES:
        if text_height(paras, size, width_in) <= space:
            return [(paras, size)]
    queue = []
    for para in paras:
        queue.extend(_split_para(para, BODY_PACKED, width_in, space)
                     if text_height([para], BODY_PACKED, width_in) > space else [para])
    chunks, chunk = [], []
    while queue:
        para = queue.pop(0)
        if not chunk or text_height([*chunk, para], BODY_PACKED, width_in) <= space:
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
        queue[:0] = [*carry, para]
    chunks.append(chunk)
    return [(c, BODY_PACKED) for c in chunks]


def fit_table(table: Table, total: int, height_in: float) -> list[tuple[Table, int]]:
    """The table as slides' worth, each with the size it is set at (see the module's rule)."""
    space = height_in * 72
    for size in TABLE_SIZES:
        if sum(row_heights(table, size, total)) <= space:
            return [(table, size)]
    heights = row_heights(table, TABLE_PACKED, total)
    parts, rows, used = [], [], heights[0]
    for row, height in zip(table.rows[1:], heights[1:]):
        if rows and used + height > space:
            parts.append(rows)
            rows, used = [], heights[0]
        rows.append(row)
        used += height
    parts.append(rows)
    return [(Table([table.rows[0], *part], table.align), TABLE_PACKED) for part in parts]


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
    width_in, space = BODY[2], BODY[3] * 72
    total = Inches(width_in)
    for text_size, table_size in TOGETHER:
        used = sum(row_heights(table, table_size, total))
        for paras in (before, after):
            if paras:
                used += text_height(paras, text_size, width_in) + 2 * INSET[1] * 72 + GAP * 72
        if used <= space:
            return Page(title, before, table, after, text_size, table_size)
    return None


def title_size(segs: list[Seg], box: tuple, sizes: tuple) -> int:
    """The largest size at which the title fits its box; the smallest when none does."""
    width, space = (box[2] - 2 * INSET[0]) * 72, room(box[3])
    for size in sizes:
        if lines(plain(segs), size, width) * size * LINE <= space:
            return size
    return sizes[-1]

