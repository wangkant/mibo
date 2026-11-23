"""A Word document made from Markdown, and exact replacement inside one, with python-docx.

`make` gives the document a person would hand in: an A4 page with the margins Word uses for Chinese, Word's own
heading styles (so the navigation pane and a table of contents find them), real numbered and bulleted lists that
nest by indentation and restart for each list, tables with a repeated header row and column widths that fit the
page, quotes, code blocks, a horizontal rule, links that open, and page numbers in the footer. Text is set in
fonts made for both scripts: SimSun with Times New Roman for the body, SimHei with Arial for headings, the East
Asian font named on every style so Chinese never falls back to a Japanese face.

`replaced` changes text where it lies, run by run: the paragraph keeps its style, the runs the replacement
touches keep their look (the new words take the look of the run where the old ones began), every other run is
left as it was, and pictures, fields and tabs stay. It reaches tables, text boxes, headers and footers.
"""
from __future__ import annotations

import copy
import io
import re
import unicodedata

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor, Twips
from docx.text.run import Run

# Fonts: (Latin, East Asian).
BODY = ("Times New Roman", "宋体")
HEADING = ("Arial", "黑体")
CODE = ("Consolas", "宋体")
INK = RGBColor(0x1F, 0x1F, 0x1F)
MUTED = "595959"
RULE = "BFBFBF"
SHADE = "F2F2F2"
HEADER_FILL = "E7ECF4"
LINK = RGBColor(0x05, 0x63, 0xC1)
# Heading level -> (size in points, space before, space after).
HEADINGS = {1: (16, 18, 10), 2: (14, 14, 8), 3: (12, 12, 6), 4: (11, 10, 4), 5: (11, 8, 4), 6: (11, 8, 4)}
# A list level's indent in twentieths of a point: two Chinese characters of body text.
STEP = 420
# Characters a table column is weighed at, at least and at most, when the page width is shared out.
COLUMN_LEAST, COLUMN_MOST = 4, 30

_HEADING = re.compile(r"(#{1,6})(?:\s+(.*?))?\s*#*\s*")
# A list item: its indent, then a bullet or a number with a dot or a bracket. "1、" is left as written.
_ITEM = re.compile(r"([ \t]*)(?:([-*+])\s+|•\s*|(\d{1,3})[.)]\s+)(.*)")
_TASK = re.compile(r"\[([ xX])\]\s+(.*)")
_RULE_LINE = re.compile(r"(?:-[ \t]*){3,}|(?:\*[ \t]*){3,}|(?:_[ \t]*){3,}|={3,}")
_TABLE_RULE = re.compile(r"\|?\s*:?-{1,}:?\s*(?:\|\s*:?-{1,}:?\s*)*\|?")
_PAGE_BREAK = re.compile(r"\\newpage|\\pagebreak|<!--\s*page\s*break\s*-->|<div[^>]*page-break[^>]*>\s*</div>",
                         re.IGNORECASE)
_FENCE = re.compile(r"(`{3,}|~{3,})")
_NUMBER = re.compile(r"[-+]?[¥$€£]?\d[\d,]*(?:\.\d+)?\s*(?:%|元|万元|万|亿)?")

# Inline marks, tried left to right; the first that matches at a place wins.
_SPAN = re.compile(
    r"\\(?P<esc>[\\`*_{}\[\]()#+\-.!|~<>])"
    r"|(?P<tick>`+)(?P<code>.+?)(?P=tick)"
    r"|!\[(?P<alt>[^\]]*)\]\([^)]*\)"
    r"|\[(?P<label>[^\]]+)\]\((?P<href>[^)\s]+)(?:\s+\"[^\"]*\")?\)"
    r"|<(?P<auto>(?:https?://|mailto:)[^>\s]+)>"
    r"|(?P<br><br\s*/?>)"
    r"|\*\*\*(?P<bi>[^*\s](?:.*?[^*\s])?)\*\*\*"
    r"|\*\*(?P<b>[^*\s](?:.*?[^\s])?)\*\*"
    r"|(?<!\w)__(?P<b2>[^_\s](?:.*?[^_\s])?)__(?!\w)"
    r"|~~(?P<s>[^~\s](?:.*?[^~\s])?)~~"
    r"|\*(?P<i>[^*\s](?:.*?[^*\s])?)\*"
    r"|(?<!\w)_(?P<i2>[^_\s](?:.*?[^_\s])?)_(?!\w)"
    r"|(?P<url>https?://[A-Za-z0-9\-._~:/?#@!$&+,;=%]+[A-Za-z0-9\-_~/#@$&+=%])")
# Each alternative above by the group that names it, in order.
_KINDS = ("esc", "code", "alt", "label", "auto", "br", "bi", "b", "b2", "s", "i", "i2", "url")
# What may follow shd in a run's, a paragraph's and a table cell's properties, in the schema's order.
_AFTER_RUN_SHD = ("w:fitText", "w:vertAlign", "w:rtl", "w:cs", "w:em", "w:lang", "w:eastAsianLayout",
                  "w:specVanish", "w:oMath")
_AFTER_PARA_SHD = ("w:tabs", "w:suppressAutoHyphens", "w:kinsoku", "w:wordWrap", "w:overflowPunct",
                   "w:topLinePunct", "w:autoSpaceDE", "w:autoSpaceDN", "w:bidi", "w:adjustRightInd", "w:snapToGrid",
                   "w:spacing", "w:ind", "w:contextualSpacing", "w:mirrorIndents", "w:suppressOverlap", "w:jc",
                   "w:textDirection", "w:textAlignment", "w:textboxTightWrap", "w:outlineLvl", "w:divId",
                   "w:cnfStyle", "w:rPr", "w:sectPr", "w:pPrChange")
_AFTER_CELL_SHD = ("w:noWrap", "w:tcMar", "w:textDirection", "w:tcFitText", "w:vAlign", "w:hideMark")


# ---------------------------------------------------------------- the look of the document

def _fonts(rpr, fonts: tuple[str, str]) -> None:
    """Names the Latin and East Asian fonts on a run's or a style's properties; the theme's fonts, which would
    win over them, are taken off."""
    element = rpr.get_or_add_rFonts()
    for theme in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
        element.attrib.pop(qn(theme), None)
    latin, east = fonts
    for key, name in (("w:ascii", latin), ("w:hAnsi", latin), ("w:cs", latin), ("w:eastAsia", east)):
        element.set(qn(key), name)


def _child(parent, tag: str, before: tuple[str, ...] = ()):
    """`parent`'s child `tag`, made when missing (ahead of the first of `before` there, as the schema orders)."""
    found = parent.find(qn(tag))
    if found is None:
        found = OxmlElement(tag)
        ahead = next((parent.find(qn(t)) for t in before if parent.find(qn(t)) is not None), None)
        if ahead is not None:
            ahead.addprevious(found)
        else:
            parent.append(found)
    return found


def _border(ppr, side: str, size: int, color: str, space: int) -> None:
    borders = _child(ppr, "w:pBdr", ("w:shd", "w:tabs", "w:suppressAutoHyphens", "w:spacing", "w:ind", "w:jc",
                                     "w:outlineLvl", "w:rPr"))
    line = OxmlElement(f"w:{side}")
    for key, value in (("w:val", "single"), ("w:sz", str(size)), ("w:space", str(space)), ("w:color", color)):
        line.set(qn(key), value)
    borders.append(line)


def _shade(props, fill: str, after: tuple[str, ...]) -> None:
    """A flat fill: `clear` with a fill colour, the form every reader draws as meant; placed ahead of `after`."""
    shd = _child(props, "w:shd", after)
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)


def _style(document) -> None:
    """The page, the fonts and the styles every block below is set in."""
    section = document.sections[0]
    # A4 as Word writes it, in twentieths of a point.
    section.page_width, section.page_height = Twips(11906), Twips(16838)
    section.top_margin = section.bottom_margin = Cm(2.54)
    section.left_margin = section.right_margin = Cm(3.18)
    section.header_distance, section.footer_distance = Cm(1.5), Cm(1.75)

    styles = document.styles
    defaults = styles.element.find(qn("w:docDefaults"))
    rpr = defaults.find(qn("w:rPrDefault")).find(qn("w:rPr"))
    _fonts(rpr, BODY)
    lang = rpr.find(qn("w:lang"))
    lang.set(qn("w:eastAsia"), "zh-CN")
    settings = document.settings.element
    settings.find(qn("w:themeFontLang")).set(qn("w:eastAsia"), "zh-CN")
    # Word 2013 and later open it as their own, not in compatibility mode.
    for setting in settings.iter(qn("w:compatSetting")):
        if setting.get(qn("w:name")) == "compatibilityMode":
            setting.set(qn("w:val"), "15")

    normal = styles["Normal"]
    normal.font.size = Pt(11)
    normal.font.color.rgb = INK
    _fonts(normal.element.get_or_add_rPr(), BODY)
    body = normal.paragraph_format
    body.space_before, body.space_after, body.line_spacing = Pt(0), Pt(6), 1.3
    body.widow_control = True

    for level, (size, before, after) in HEADINGS.items():
        style = styles[f"Heading {level}"]
        _fonts(style.element.get_or_add_rPr(), HEADING)
        style.font.size, style.font.bold, style.font.italic = Pt(size), True, False
        style.font.color.rgb = INK
        form = style.paragraph_format
        form.space_before, form.space_after, form.line_spacing = Pt(before), Pt(after), 1.15
        form.keep_with_next = True

    title = styles["Title"]
    _fonts(title.element.get_or_add_rPr(), HEADING)
    title.font.size, title.font.bold, title.font.color.rgb = Pt(20), True, INK
    ppr = title.element.get_or_add_pPr()
    for border in ppr.findall(qn("w:pBdr")):
        ppr.remove(border)
    form = title.paragraph_format
    form.alignment = WD_ALIGN_PARAGRAPH.CENTER
    form.space_before, form.space_after, form.line_spacing = Pt(6), Pt(18), 1.15
    form.keep_with_next = True

    quote = styles["Quote"]
    quote.font.italic, quote.font.color.rgb = False, RGBColor.from_string(MUTED)
    form = quote.paragraph_format
    form.left_indent, form.right_indent, form.space_after = Cm(0.6), Cm(0.6), Pt(4)
    _border(quote.element.get_or_add_pPr(), "left", 18, RULE, 10)

    for name in ("List Bullet", "List Number"):
        form = styles[name].paragraph_format
        form.space_after, form.line_spacing = Pt(3), 1.3

    code = styles.add_style("Code", WD_STYLE_TYPE.PARAGRAPH)
    code.base_style, code.quick_style = normal, True
    _fonts(code.element.get_or_add_rPr(), CODE)
    code.font.size = Pt(9.5)
    form = code.paragraph_format
    form.space_before, form.space_after, form.line_spacing = Pt(0), Pt(0), 1.0
    form.left_indent, form.right_indent = Cm(0.2), Cm(0.2)
    form.keep_with_next = True
    _shade(code.element.get_or_add_pPr(), SHADE, _AFTER_PARA_SHD)

    link = styles.add_style("Hyperlink", WD_STYLE_TYPE.CHARACTER)
    link.font.color.rgb, link.font.underline = LINK, True

    # Page numbers, centred in the footer.
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for kind, text in (("begin", None), (None, "PAGE"), ("separate", None), (None, None), ("end", None)):
        run = footer.add_run("1" if kind is None and text is None else "")
        run.font.size, run.font.color.rgb = Pt(9), RGBColor.from_string(MUTED)
        if kind:
            mark = OxmlElement("w:fldChar")
            mark.set(qn("w:fldCharType"), kind)
            run._r.append(mark)
        elif text:
            instr = OxmlElement("w:instrText")
            instr.set(qn("xml:space"), "preserve")
            instr.text = f" {text} "
            run._r.append(instr)


def _numbering(document) -> dict:
    """Two multi-level lists Word's own way: bullets (•, o, ▪ in Symbol, Courier New and Wingdings) and numbers
    (1., a), i.); each level indented two characters more. Returns their abstract ids and a counter for the
    list instances made from them."""
    numbering = document.part.numbering_part.element
    used = [int(n.get(qn("w:abstractNumId"))) for n in numbering.findall(qn("w:abstractNum"))]
    ids = {}
    for kind, start in (("bullet", max(used) + 1), ("number", max(used) + 2)):
        abstract = OxmlElement("w:abstractNum")
        abstract.set(qn("w:abstractNumId"), str(start))
        multi = OxmlElement("w:multiLevelType")
        multi.set(qn("w:val"), "hybridMultilevel")
        abstract.append(multi)
        for level in range(9):
            lvl = OxmlElement("w:lvl")
            lvl.set(qn("w:ilvl"), str(level))
            if kind == "bullet":
                text, font = (("", "Symbol"), ("o", "Courier New"), ("", "Wingdings"))[level % 3]
                fmt = "bullet"
            else:
                fmt = ("decimal", "lowerLetter", "lowerRoman")[level % 3]
                text, font = ("%{n}.", "%{n})", "%{n}.")[level % 3].format(n=level + 1), None
            for tag, value in (("w:start", "1"), ("w:numFmt", fmt), ("w:lvlText", text), ("w:lvlJc", "left")):
                item = OxmlElement(tag)
                item.set(qn("w:val"), value)
                lvl.append(item)
            ppr = OxmlElement("w:pPr")
            ind = OxmlElement("w:ind")
            ind.set(qn("w:left"), str(STEP * (level + 1)))
            ind.set(qn("w:hanging"), str(STEP))
            ppr.append(ind)
            lvl.append(ppr)
            if font:
                rpr = OxmlElement("w:rPr")
                fonts = OxmlElement("w:rFonts")
                for key in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
                    fonts.set(qn(key), font)
                fonts.set(qn("w:hint"), "default")
                rpr.append(fonts)
                lvl.append(rpr)
            abstract.append(lvl)
        # Abstract definitions come before the list instances in numbering.xml.
        first_num = numbering.find(qn("w:num"))
        if first_num is not None:
            first_num.addprevious(abstract)
        else:
            numbering.append(abstract)
        ids[kind] = start
    return ids


def _list_instance(document, abstract: int, start: int = 1) -> int:
    """A list made from the abstract definition, counting from `start` at its first level and from 1 below."""
    numbering = document.part.numbering_part.element
    num_id = max((int(n.get(qn("w:numId"))) for n in numbering.findall(qn("w:num"))), default=0) + 1
    num = OxmlElement("w:num")
    num.set(qn("w:numId"), str(num_id))
    ref = OxmlElement("w:abstractNumId")
    ref.set(qn("w:val"), str(abstract))
    num.append(ref)
    for level in range(9):
        override = OxmlElement("w:lvlOverride")
        override.set(qn("w:ilvl"), str(level))
        first = OxmlElement("w:startOverride")
        first.set(qn("w:val"), str(start if level == 0 else 1))
        override.append(first)
        num.append(override)
    numbering.append(num)
    return num_id


def _properties(document, title: str) -> None:
    """The file's properties: its title, and nothing the library's own template put there (its name as the author,
    a comment, the dates it was made in 2013, a thumbnail of an empty page)."""
    core = document.core_properties
    core.title, core.author, core.comments, core.last_modified_by = title[:200], "", "", ""
    element = core._element
    for tag in ("dcterms:created", "dcterms:modified", "cp:lastPrinted"):
        for found in element.findall(qn(tag)):
            element.remove(found)
    rels = document.part.package.rels
    for key, rel in list(rels.items()):
        if rel.reltype == RT.THUMBNAIL:
            del rels[key]


# ---------------------------------------------------------------- inline text

def _spans(text: str, marks: frozenset = frozenset(), link: str = ""):
    """(words, marks, link) for a line's inline Markdown: bold, italic, strikethrough, code, links, line breaks."""
    at = 0
    for found in _SPAN.finditer(text):
        if found.start() > at:
            yield text[at:found.start()], marks, link
        at = found.end()
        kind = next(k for k in _KINDS if found.group(k) is not None)
        value = found.group(kind)
        if kind == "esc":
            yield value, marks, link
        elif kind == "code":
            yield value.strip() if value.strip() else value, marks | {"code"}, link
        elif kind == "alt":
            if value:
                yield value, marks, link
        elif kind == "label":
            href = found.group("href")
            yield from _spans(value, marks, href if re.match(r"(?:https?:|mailto:)", href, re.IGNORECASE) else link)
        elif kind in ("auto", "url"):
            yield value, marks, value
        elif kind == "br":
            yield "\n", marks, link
        else:
            add = {"bi": {"b", "i"}, "b": {"b"}, "b2": {"b"}, "s": {"s"}, "i": {"i"}, "i2": {"i"}}[kind]
            yield from _spans(value, marks | add, link)
    if at < len(text):
        yield text[at:], marks, link


def _plain(text: str) -> str:
    return "".join(words for words, _, _ in _spans(text))


def _run(paragraph, parent, words: str, marks: frozenset) -> None:
    element = OxmlElement("w:r")
    parent.append(element)
    run = Run(element, paragraph)
    if words == "\n":
        run.add_break()
        return
    run.text = words
    if "b" in marks:
        run.font.bold = True
    if "i" in marks:
        run.font.italic = True
    if "s" in marks:
        run.font.strike = True
    if "code" in marks:
        _fonts(element.get_or_add_rPr(), CODE)
        run.font.size = Pt(9.5)
        _shade(element.get_or_add_rPr(), SHADE, _AFTER_RUN_SHD)


def _write(paragraph, text: str, bold: bool = False) -> None:
    """The line's inline Markdown as runs of `paragraph`; a link becomes one Word opens."""
    for words, marks, link in _spans(text, frozenset({"b"}) if bold else frozenset()):
        if not words:
            continue
        if link:
            holder = OxmlElement("w:hyperlink")
            holder.set(qn("r:id"), paragraph.part.relate_to(link, RT.HYPERLINK, is_external=True))
            paragraph._p.append(holder)
            _run(paragraph, holder, words, marks)
            Run(holder[-1], paragraph).style = "Hyperlink"
        else:
            _run(paragraph, paragraph._p, words, marks)


# ---------------------------------------------------------------- blocks

def _width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def _cells(row: str) -> list[str]:
    row = row.strip()
    row = row.removeprefix("|")
    row = row[:-1] if row.endswith("|") and not row.endswith("\\|") else row
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", row)]


def _is_table_start(lines: list[str], n: int) -> bool:
    line = lines[n].strip()
    if line.startswith("|"):
        return True
    return "|" in line and n + 1 < len(lines) and "-" in lines[n + 1] and bool(_TABLE_RULE.fullmatch(lines[n + 1].strip()))


def _table(document, rows: list[list[str]], aligns: list[str], width: int) -> None:
    """A table filling the text width: the first row is the header (shaded, bold, repeated on each page), columns
    share the width by how much they hold, and no row breaks across pages."""
    columns = max(len(row) for row in rows)
    rows = [row + [""] * (columns - len(row)) for row in rows]
    weights = [min(max(max(_width(_plain(row[c])) for row in rows), COLUMN_LEAST), COLUMN_MOST) for c in range(columns)]
    widths = [width * w // sum(weights) for w in weights]
    widths[-1] += width - sum(widths)
    # A column the rule gives no alignment: the header centred, numbers (amounts, percentages) to the right.
    aligns = [aligns[c] if c < len(aligns) and aligns[c] else
              "right" if len(rows) > 1 and all(_NUMBER.fullmatch(_plain(row[c])) or not row[c] for row in rows[1:])
              and any(row[c] for row in rows[1:]) else "" for c in range(columns)]
    table = document.add_table(rows=len(rows), cols=columns)
    table.style = document.styles["Table Grid"]
    table.autofit = False
    tbl_pr = table._tbl.tblPr
    tbl_w = _child(tbl_pr, "w:tblW", ("w:jc", "w:tblCellSpacing", "w:tblInd", "w:tblBorders", "w:shd",
                                       "w:tblLayout", "w:tblCellMar", "w:tblLook"))
    tbl_w.set(qn("w:type"), "dxa")
    tbl_w.set(qn("w:w"), str(width))
    borders = _child(tbl_pr, "w:tblBorders", ("w:shd", "w:tblLayout", "w:tblCellMar", "w:tblLook"))
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        line = OxmlElement(f"w:{side}")
        for key, value in (("w:val", "single"), ("w:sz", "4"), ("w:space", "0"), ("w:color", "A6A6A6")):
            line.set(qn(key), value)
        borders.append(line)
    margins = _child(tbl_pr, "w:tblCellMar", ("w:tblLook",))
    for side, size in (("top", 40), ("left", 100), ("bottom", 40), ("right", 100)):
        mar = OxmlElement(f"w:{side}")
        mar.set(qn("w:w"), str(size))
        mar.set(qn("w:type"), "dxa")
        margins.append(mar)
    for c, column in enumerate(table.columns):
        column.width = widths[c] * 635  # twips to EMU
    for r, row in enumerate(rows):
        tr_pr = table.rows[r]._tr.get_or_add_trPr()
        tr_pr.append(OxmlElement("w:cantSplit"))
        if r == 0:
            tr_pr.append(OxmlElement("w:tblHeader"))
        for c, words in enumerate(row):
            cell = table.cell(r, c)
            cell.width = widths[c] * 635
            if r == 0:
                _shade(cell._tc.get_or_add_tcPr(), HEADER_FILL, _AFTER_CELL_SHD)
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            paragraph = cell.paragraphs[0]
            form = paragraph.paragraph_format
            form.space_before, form.space_after, form.line_spacing = Pt(2), Pt(2), 1.15
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER if r == 0 else {
                "center": WD_ALIGN_PARAGRAPH.CENTER, "right": WD_ALIGN_PARAGRAPH.RIGHT}.get(aligns[c])
            _write(paragraph, words, bold=r == 0)
            for run in paragraph.runs:
                run.font.size = Pt(10)
    # A table is followed by a little air before the next paragraph.
    gap = document.add_paragraph()
    gap.paragraph_format.space_after = Pt(0)
    gap.paragraph_format.line_spacing = 1.0
    gap.paragraph_format.keep_with_next = False


def _indent(raw: str) -> int:
    return len(raw.replace("\t", "    ")) - len(raw.replace("\t", "    ").lstrip(" "))


def make(text: str) -> bytes:
    """The Word document that `text`, written as Markdown, describes."""
    document = Document()
    _style(document)
    abstract = _numbering(document)
    section = document.sections[0]
    width = (section.page_width - section.left_margin - section.right_margin) // 635

    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    headings, fence = [], ""
    for line in lines:
        bare = line.strip()
        if (fence and bare.startswith(fence)) or (not fence and _FENCE.match(bare)):
            fence = "" if fence else _FENCE.match(bare)[1]
        elif not fence and (heading := _HEADING.fullmatch(bare)):
            headings.append(heading)
    tops = [h for h in headings if len(h[1]) == 1]
    first = next((line.strip() for line in lines if line.strip()), "")
    # One `#` heading at the very top is the document's title; the `##` sections under it are then Heading 1.
    titled = len(tops) == 1 and tops[0].group(0) == first
    title_text = _plain(tops[0][2] or "") if titled else ""

    # The list being written: its indents, its bullet and number instances; None between lists.
    listing: dict | None = None
    n = 0
    while n < len(lines):
        raw = lines[n].rstrip()
        bare = raw.strip()
        n += 1
        if not bare:
            continue
        item = _ITEM.fullmatch(raw)
        if item and _RULE_LINE.fullmatch(bare):
            item = None
        if not item and not (listing and _indent(raw) > 0 and not bare.startswith(("```", "~~~", "|", ">"))):
            listing = None
        if fence := _FENCE.match(bare):
            mark = fence[1]
            block = []
            while n < len(lines) and not lines[n].strip().startswith(mark):
                block.append(lines[n].rstrip("\n").replace("\t", "    "))
                n += 1
            n += 1
            for row, words in enumerate(block or [""]):
                paragraph = document.add_paragraph(style="Code")
                if words:
                    paragraph.add_run(words)
                if row == len(block) - 1 or not block:
                    paragraph.paragraph_format.space_after = Pt(8)
                    paragraph.paragraph_format.keep_with_next = False
            continue
        if _PAGE_BREAK.fullmatch(bare):
            document.add_page_break()
            continue
        if _RULE_LINE.fullmatch(bare):
            paragraph = document.add_paragraph()
            paragraph.paragraph_format.space_after = Pt(10)
            _border(paragraph._p.get_or_add_pPr(), "bottom", 6, RULE, 1)
            continue
        if heading := _HEADING.fullmatch(bare):
            level = len(heading[1])
            words = heading[2] or ""
            if titled and level == 1:
                paragraph = document.add_paragraph(style="Title")
                _write(paragraph, words)
                continue
            level = max(1, level - 1) if titled else level
            _write(document.add_paragraph(style=f"Heading {level}"), words)
            continue
        if _is_table_start(lines, n - 1):
            rows, aligns = [], []
            n -= 1
            while n < len(lines) and lines[n].strip() and "|" in lines[n]:
                line = lines[n].strip()
                n += 1
                if _TABLE_RULE.fullmatch(line) and "-" in line:
                    aligns = ["center" if c.startswith(":") and c.endswith(":") else "right" if c.endswith(":")
                              else "left" if c.startswith(":") else "" for c in _cells(line)]
                    continue
                rows.append(_cells(line))
            _table(document, rows, aligns, width)
            continue
        if bare.startswith(">"):
            words = re.sub(r"^(?:>\s?)+", "", bare)
            if words:
                _write(document.add_paragraph(style="Quote"), words)
            continue
        if item:
            indent, number, words = _indent(item[1]), item[3], item[4]
            if listing is None:
                listing = {"indents": [], "bullet": 0, "number": 0, "last": ("", 0)}
            indents = listing["indents"]
            while indents and indents[-1] > indent:
                indents.pop()
            if not indents or indent > indents[-1]:
                indents.append(indent)
            level = min(len(indents) - 1, 8)
            if not number:
                if not listing["bullet"]:
                    listing["bullet"] = _list_instance(document, abstract["bullet"])
                num_id, style = listing["bullet"], "List Bullet"
                if task := _TASK.fullmatch(words):
                    words = ("☑ " if task[1] in "xX" else "☐ ") + task[2]
            else:
                # Numbers under a bullet start again at each bullet; under a number, Word restarts them itself.
                kind, above = listing["last"]
                if not listing["number"] or (kind == "bullet" and above < level):
                    listing["number"] = _list_instance(document, abstract["number"], int(number) if level == 0 else 1)
                num_id, style = listing["number"], "List Number"
            listing["last"] = ("number" if number else "bullet", level)
            paragraph = document.add_paragraph(style=style)
            ppr = paragraph._p.get_or_add_pPr()
            num_pr = ppr.get_or_add_numPr()
            num_pr.get_or_add_ilvl().val = level
            num_pr.get_or_add_numId().val = num_id
            paragraph.paragraph_format.left_indent = Pt(STEP * (level + 1) / 20)
            paragraph.paragraph_format.first_line_indent = Pt(-STEP / 20)
            _write(paragraph, words)
            continue
        paragraph = document.add_paragraph()
        if listing:
            # A line indented under a list item continues it, set at the item's text.
            level = min(len(listing["indents"]) - 1, 8)
            paragraph.paragraph_format.left_indent = Pt(STEP * (level + 1) / 20)
            paragraph.paragraph_format.space_after = Pt(3)
        _write(paragraph, bare)

    _properties(document, title_text or next((_plain(h[2] or "") for h in headings), ""))
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


# ---------------------------------------------------------------- what a document holds

def _parts(document):
    """The body and every header and footer, each once."""
    yield document.element.body
    seen = set()
    for section in document.sections:
        for part in (section.header, section.first_page_header, section.even_page_header,
                     section.footer, section.first_page_footer, section.even_page_footer):
            if part.is_linked_to_previous:
                continue
            element = part._element
            if id(element) not in seen:
                seen.add(id(element))
                yield element


def _paragraphs(document) -> tuple[list, list]:
    """(the paragraphs a reader sees, in the body with its tables and text boxes, headers and footers; the copies
    of text boxes kept for older readers, which change with them but are not counted)."""
    shown, copies = [], []
    for part in _parts(document):
        for p in part.iter(qn("w:p")):
            fallback = any(a.tag == _FALLBACK for a in p.iterancestors())
            (copies if fallback else shown).append(p)
    return shown, copies


_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"
_RUNS = "./w:r | ./w:hyperlink/w:r | ./w:ins/w:r | ./w:smartTag/w:r | ./w:fldSimple/w:r | ./w:sdt/w:sdtContent/w:r"
# What a piece of a run that is not a w:t reads as.
_MARKS = {qn("w:tab"): "\t", qn("w:br"): "\n", qn("w:cr"): "\n", qn("w:noBreakHyphen"): "-"}
# A character no document holds, standing for a paragraph break inside the new words until they are split.
_SPLIT = "\ue000"


def _pieces(p) -> list[tuple[int, int, object]]:
    """(start, end, element) for each piece of a paragraph's own text in reading order: a w:t's words, a tab, a
    break. A text box's paragraphs inside one of its runs are paragraphs of their own."""
    pieces, at = [], 0
    for run in p.xpath(_RUNS):
        for child in run:
            words = (child.text or "") if child.tag == qn("w:t") else _MARKS.get(child.tag, "")
            if words:
                pieces.append((at, at + len(words), child))
                at += len(words)
    return pieces


def _text(p) -> str:
    return "".join((e.text or "") if e.tag == qn("w:t") else _MARKS[e.tag] for _, _, e in _pieces(p))


def _swap(p, old: str, new: str, every: bool) -> None:
    """Replaces `old` in paragraph p, piece by piece. Only what differs is touched (the words old and new share at
    either end stay where they are, in their own runs); the new words go into the first w:t the changed ones
    touch, what else they covered is taken out of the other pieces, and every run keeps its properties."""
    same = 0
    while same < min(len(old), len(new)) and old[same] == new[same]:
        same += 1
    tail = 0
    while tail < min(len(old), len(new)) - same and old[-1 - tail] == new[-1 - tail]:
        tail += 1
    words = new[same:len(new) - tail]
    starts = [m.start() for m in re.finditer(re.escape(old), _text(p))]
    for found in reversed(starts if every else starts[:1]):
        start, end = found + same, found + len(old) - tail
        if start == end:
            _insert(p, start, words)
            continue
        new, placed = words, False
        for lo, hi, element in _pieces(p):
            if hi <= start or lo >= end:
                continue
            if element.tag == qn("w:t"):
                cut_from, cut_to = max(start, lo) - lo, min(end, hi) - lo
                element.text = element.text[:cut_from] + ("" if placed else new) + element.text[cut_to:]
                element.set(qn("xml:space"), "preserve")
            else:
                if not placed:
                    holder = OxmlElement("w:t")
                    holder.text = new
                    holder.set(qn("xml:space"), "preserve")
                    element.addprevious(holder)
                element.getparent().remove(element)
            placed = True
    _split_marked(p)


def _insert(p, at: int, words: str) -> None:
    """Puts `words` in at character `at` of paragraph p, in the run whose words end there (as typing would), or
    the one that starts there at the paragraph's beginning."""
    pieces = [(lo, hi, e) for lo, hi, e in _pieces(p) if e.tag == qn("w:t")]
    hit = next((x for x in pieces if x[0] < at <= x[1]), None) or next((x for x in pieces if x[0] == at), None)
    if hit is None:
        # Between two tabs or breaks: the words go in beside them, in that run.
        holder = OxmlElement("w:t")
        holder.text = words
        holder.set(qn("xml:space"), "preserve")
        lo, _, element = next(x for x in _pieces(p) if at in (x[0], x[1]))
        (element.addprevious if lo == at else element.addnext)(holder)
        return
    lo, _, element = hit
    element.text = element.text[:at - lo] + words + element.text[at - lo:]
    element.set(qn("xml:space"), "preserve")


def _split_marked(p) -> None:
    for _, _, element in _pieces(p):
        if element.tag == qn("w:t") and _SPLIT in element.text:
            _split(p, element)
            return


def _split(p, t) -> None:
    """Splits paragraph p where `t` holds the split mark: p keeps what comes before it, a copy of p placed after
    it holds the rest, with p's style, numbering and the run's look; a section break stays with the last part."""
    at = t.text.index(_SPLIT)
    path, node = [], t
    while node is not p:
        parent = node.getparent()
        path.append(parent.index(node))
        node = parent
    path.reverse()
    rest = copy.deepcopy(p)
    p.addnext(rest)
    for keep_before, root in ((True, p), (False, rest)):
        node = root
        for index in path:
            children = list(node)
            for k, other in enumerate(children):
                if (k > index if keep_before else k < index) and other.tag not in (qn("w:pPr"), qn("w:rPr")):
                    node.remove(other)
            node = children[index]
        node.text = node.text[:at] if keep_before else node.text[at + 1:]
    ppr = p.find(qn("w:pPr"))
    if ppr is not None and ppr.find(qn("w:sectPr")) is not None:
        ppr.remove(ppr.find(qn("w:sectPr")))
    # Word's own paragraph ids must stay unique.
    for key in [k for k in rest.attrib if k.startswith("{http://schemas.microsoft.com/office/word/2010/wordml}")]:
        del rest.attrib[key]
    _split_marked(rest)


def replaced(data: bytes, old: str, new: str, every: bool) -> bytes:
    """The document with `old` replaced by `new`, exactly once unless `every`. A `new` of several lines becomes as
    many paragraphs, each in the style of the one it was written into. ValueError says what went wrong."""
    old, new = old.replace("\r\n", "\n").strip("\n"), new.replace("\r\n", "\n").strip("\n")
    if not old:
        raise ValueError("old_string is empty: give the exact text to replace.")
    document = Document(io.BytesIO(data))
    shown, copies = _paragraphs(document)
    count = sum(_text(p).count(old) for p in shown)
    if count == 0 and "\n" in old:
        raise ValueError("old_string spans more than one paragraph: in a Word document, replace within one paragraph "
                         "(or one table cell) at a time; new_string may hold several lines, which become paragraphs.")
    if count == 0:
        row = " | " in old or old.startswith("|")
        raise ValueError("old_string was not found in the document: it must match the text of one paragraph exactly, "
                         "as read_file shows it without the line numbers"
                         + ("; a table row read_file shows as | a | b | is several cells, so replace within one cell"
                            if row else "") + ".")
    if count > 1 and not every:
        raise ValueError(f"old_string is in the document {count} times: give more of the text around it so it is "
                         "found once, or set replace_all to change every one.")
    for p in shown + copies:
        if old in _text(p):
            _swap(p, old, new.replace("\n", _SPLIT), every)
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


def summary(data: bytes) -> str:
    """A few words for the model: “a Word document titled “…”, of 12 paragraphs and 2 tables”."""
    document = Document(io.BytesIO(data))
    paragraphs = sum(1 for p in document.paragraphs if p.text.strip())
    tables = len(document.tables)
    title = document.core_properties.title
    return ("a Word document" + (f" titled “{title}”," if title else "")
            + f" of {paragraphs} paragraph{'s' if paragraphs != 1 else ''}"
            + (f" and {tables} table{'s' if tables != 1 else ''}" if tables else ""))
