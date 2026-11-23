"""Excel workbooks: made from the tables a model writes, and changed by exact replacement of a cell's text.

The model writes one table per sheet, as Markdown table rows or as CSV or tab-separated lines, the first row the
headers; a "# name" line names the next sheet and a cell that starts with = is a formula. The workbook made from it
is one a person uses as it is: numbers are numbers with a number format that matches how they were written, ISO
dates are dates, digits that are a name (a phone, an identity card, a leading zero) stay text, and formulas stay
live, checked before anything is written, and calculate when the file is opened. The header row is styled and
frozen, the table has a filter, and every column is as wide as what it holds.
"""
from __future__ import annotations

import datetime
import io
import re
import unicodedata
import zipfile
from collections import Counter
from decimal import Decimal

from openpyxl import Workbook, load_workbook
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.formula import Tokenizer
from openpyxl.formula.tokenizer import TokenizerError
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import column_index_from_string, get_column_letter, quote_sheetname
from openpyxl.utils.datetime import to_excel
from openpyxl.utils.formulas import FORMULAE

# Office's own font for Chinese, shipped with it on Windows and macOS; its Latin letters and digits are clean too.
_FONT = "等线"
_HEADER_FILL = PatternFill("solid", fgColor="DDEBF7")
_TOTAL_FILL = PatternFill("solid", fgColor="F2F2F2")
_GRID = Side("thin", color="BFBFBF")
_RULE = Side("thin", color="595959")
_WIDEST = 50   # a column is never wider than this; longer text wraps
_WRAP = 40     # text wider than this wraps

_TABLE_RULE = re.compile(r"\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?")
_HEADING = re.compile(r"#{1,6}\s+(.*?)\s*#*")
# A number as people write it: a sign, a currency sign, thousands separators, decimals, a percent sign or 元.
_NUMBER = re.compile(r"([-+]?)([¥￥$€£]?)(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?\s*(%|％|元)?")
_DATE = re.compile(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?")
_MOBILE = re.compile(r"1[3-9]\d{9}")
# Headers of columns whose digits name something rather than count it.
_NAME_HEADER = re.compile(r"电话|手机|号码|编号|编码|代码|工号|学号|证号|身份证|账号|帐号|卡号|邮编|邮政编码|单号|序列号|"
                          r"QQ|微信|\bid\b|phone|mobile|\btel\b|\bzip\b|postal|code|account|serial", re.I)
_PERCENT_HEADER = re.compile(r"%|％|占比|比例|比重|百分比|percent|(?<![汇频功速])率", re.I)
_TOTAL = re.compile(r"(合计|总计|小计|共计|总额|总和|total|subtotal|grand total|sum)[:：]?|.*(合计|总计|小计|共计)[:：]?", re.I)
_DATE_FUNCTIONS = ("=TODAY(", "=DATE(", "=EDATE(", "=EOMONTH(", "=WORKDAY(", "=DATEVALUE(")

# Functions newer than Excel 2007, which the file must name with the _xlfn. prefix Excel itself writes.
_XLFN = frozenset((
    "CONCAT TEXTJOIN IFS SWITCH MAXIFS MINIFS XLOOKUP XMATCH IFNA DAYS ISOWEEKNUM XOR NUMBERVALUE FORMULATEXT "
    "ISFORMULA SHEET SHEETS UNICHAR UNICODE ARABIC BASE DECIMAL AGGREGATE CEILING.MATH FLOOR.MATH CEILING.PRECISE "
    "FLOOR.PRECISE STDEV.S STDEV.P VAR.S VAR.P PERCENTILE.INC PERCENTILE.EXC QUARTILE.INC QUARTILE.EXC RANK.EQ "
    "RANK.AVG MODE.SNGL NORM.DIST NORM.INV NORM.S.DIST NORM.S.INV T.DIST T.INV T.TEST CHISQ.TEST F.TEST BINOM.DIST "
    "POISSON.DIST EXPON.DIST GAMMA.DIST LOGNORM.DIST WEIBULL.DIST CONFIDENCE.NORM CONFIDENCE.T COVARIANCE.S "
    "COVARIANCE.P TEXTBEFORE TEXTAFTER").split())
# Functions whose result fills several cells; a file written here has none of the metadata that spilling needs.
_SPILL = frozenset("FILTER SORT SORTBY UNIQUE SEQUENCE RANDARRAY TEXTSPLIT LET LAMBDA VSTACK HSTACK TOCOL TOROW "
                   "CHOOSECOLS CHOOSEROWS TAKE DROP EXPAND WRAPROWS WRAPCOLS".split())
_LAST_COLUMN, _LAST_ROW = 16384, 1048576


class _Bad(Exception):
    """A formula Excel would refuse or compute wrongly; the message completes a sentence about its cell."""


# ---------------------------------------------------------------- what a written cell holds

class _Typed:
    """A cell's value and what kind of value it is, with how it was written (decimals, separators, unit)."""
    __slots__ = ("value", "kind", "decimals", "grouped", "unit")

    def __init__(self, value, kind: str, decimals: int = 0, grouped: bool = False, unit: str = "") -> None:
        self.value, self.kind, self.decimals, self.grouped, self.unit = value, kind, decimals, grouped, unit


def _meant_formula(text: str) -> bool:
    """A cell starting with = is a formula unless it plainly is not one: "=", "== 注意 ==", "=> 下一步"."""
    rest = text[1:].lstrip()
    return bool(rest) and rest[0] not in "=<>" and re.search(r"[A-Za-z0-9]", rest) is not None


def _typed(text: str, names: bool = False) -> _Typed:
    """The value `text` stands for, as make() stores it; `names` says the column's digits name things."""
    if text == "":
        return _Typed(None, "empty")
    if text.startswith("="):
        return _Typed(text, "formula") if _meant_formula(text) else _Typed(text, "text")
    if number := _NUMBER.fullmatch(text):
        sign, money, whole, decimals, after = number.groups()
        bare = whole.replace(",", "")
        plain = not (money or after or decimals or "," in whole)
        if plain and (names or (len(bare) > 1 and bare.startswith("0")) or len(bare) > 15 or _MOBILE.fullmatch(bare)
                      or (sign == "+" and len(bare) >= 7)):
            return _Typed(text, "digits")
        if not (money and after):
            amount = Decimal(sign + bare + ("." + decimals if decimals else ""))
            places = len(decimals or "")
            if after in ("%", "％"):
                return _Typed(float(amount / 100), "percent", places)
            value = float(amount) if decimals else int(amount)
            if money or after:
                return _Typed(value, "money", places, True, money.replace("￥", "¥") or after)
            return _Typed(value, "number", places, "," in whole)
    if re.fullmatch(r"\d{17}[Xx]", text):   # an identity card number with its check letter
        return _Typed(text, "digits")
    if date := _DATE.fullmatch(text):
        try:
            parts = [int(p) for p in date.groups() if p is not None]
            if len(parts) == 3:
                return _Typed(datetime.date(*parts), "date")
            return _Typed(datetime.datetime(*parts), "datetime")
        except ValueError:
            pass
    return _Typed(text, "text")


def _format(kind: str, decimals: int = 0, grouped: bool = False, unit: str = "", big: bool = False) -> str:
    """The number format that shows a value of this kind the way it was written."""
    tail = "." + "0" * decimals if decimals else ""
    if kind == "percent":
        return "0" + tail + "%"
    if kind == "money":
        return f'#,##0{tail}"{unit}"' if unit == "元" else f'"{unit}"#,##0{tail}'
    if kind == "date":
        return "yyyy-mm-dd"
    if kind == "datetime":
        return "yyyy-mm-dd hh:mm"
    if kind == "number" and (grouped or tail or big):
        return ("#,##0" if grouped else "0") + tail
    if kind == "digits":
        return "@"
    return "General"


def _shown(typed: _Typed) -> str:
    """Roughly what Excel shows for the value, to size its column."""
    value, d = typed.value, typed.decimals
    if typed.kind == "percent":
        return f"{value * 100:.{d}f}%"
    if typed.kind == "money":
        return f"{typed.unit}{value:,.{d}f}"
    if typed.kind == "number":
        return f"{value:,.{d}f}" if typed.grouped else f"{value:.{d}f}"
    if typed.kind in ("date", "datetime"):
        return "2026-01-01" + (" 00:00" if typed.kind == "datetime" else "")
    return str(value)


def _width(text: str) -> int:
    """Display width: East Asian characters take two columns."""
    return max((sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in line)
                for line in text.split("\n")), default=0)


# ---------------------------------------------------------------- formulas

def _bounds(ref: str) -> tuple[int, int, int, int] | None:
    """Columns and rows a reference covers (first column, first row, last column, last row); None if it is not one."""
    ref = ref.replace("$", "")
    if m := re.fullmatch(r"([A-Za-z]{1,3})(\d+)(?::([A-Za-z]{1,3})(\d+))?", ref):
        c1, r1 = column_index_from_string(m[1].upper()), int(m[2])
        c2, r2 = (column_index_from_string(m[3].upper()), int(m[4])) if m[3] else (c1, r1)
    elif m := re.fullmatch(r"([A-Za-z]{1,3}):([A-Za-z]{1,3})", ref):
        c1, c2, r1, r2 = column_index_from_string(m[1].upper()), column_index_from_string(m[2].upper()), 1, _LAST_ROW
    elif m := re.fullmatch(r"(\d+):(\d+)", ref):
        c1, c2, r1, r2 = 1, _LAST_COLUMN, int(m[1]), int(m[2])
    else:
        return None
    return c1, r1, c2, r2


def _formula(text: str, sheet: str, column: int, row: int, sheets: dict[str, str], names: set[str]) -> str:
    """The formula as the file should hold it, after checking it: brackets and quotes closed, every function one
    Excel has (newer ones given their _xlfn. prefix), every reference inside a sheet the workbook has and not its
    own cell. `sheets` maps each sheet name the model may use, lowercased, to the sheet's name in the workbook;
    a reference to a renamed sheet is rewritten to the new name."""
    try:
        tokens = Tokenizer(text)
    except (TokenizerError, IndexError):
        raise _Bad(f"the formula {text} has a quote or bracket that is not closed or not opened") from None
    depth = 0
    for token in tokens.items:
        depth += (token.subtype == "OPEN") - (token.subtype == "CLOSE")
        if depth < 0:
            break
    if depth:
        raise _Bad(f"the formula {text} has brackets that do not pair up")
    for token in tokens.items:
        if token.type == "FUNC" and token.subtype == "OPEN" and token.value != "(":
            name = token.value[:-1].upper()
            bare = name.removeprefix("_XLFN.").removeprefix("_XLWS.")
            if bare in _SPILL:
                raise _Bad(f"the formula uses {bare}, whose result fills several cells and cannot be kept in this "
                           "file: write the values themselves, or use INDEX and MATCH")
            if bare in _XLFN:
                token.value = "_xlfn." + bare + "("
            elif name in FORMULAE:
                token.value = name + "("
            else:
                raise _Bad(f"the formula uses the function {token.value[:-1]}, which Excel does not have")
        elif token.type == "OPERAND" and token.subtype == "ERROR":
            raise _Bad(f"the formula holds the error value {token.value}")
        elif token.type == "OPERAND" and token.subtype == "RANGE":
            where, _, ref = token.value.rpartition("!")
            target = sheet
            if where:
                said = where[1:-1].replace("''", "'") if where.startswith("'") and where.endswith("'") else where
                if said.lower() not in sheets:
                    raise _Bad(f"the formula refers to the sheet {said}, which the workbook does not have (its sheets: "
                               + ", ".join(dict.fromkeys(sheets.values())) + ")")
                target = sheets[said.lower()]
            span = _bounds(ref)
            if span is None:
                if not where and ref.lower() in names:
                    continue
                raise _Bad(f"the formula uses {token.value}, which is neither a cell reference nor a name in the "
                           "workbook: write a reference such as B2:B9, or put text in double quotes")
            c1, r1, c2, r2 = span
            if max(c1, c2) > _LAST_COLUMN or max(r1, r2) > _LAST_ROW or min(r1, r2) < 1:
                raise _Bad(f"the formula refers to {ref}, which lies beyond the last row or column of a sheet")
            if target == sheet and min(c1, c2) <= column <= max(c1, c2) and min(r1, r2) <= row <= max(r1, r2):
                raise _Bad(f"the formula refers to its own cell {get_column_letter(column)}{row}, a circular "
                           "reference: leave the cell out of the range")
            # Excel's own spelling: the sheet's name as the workbook has it, the reference in capitals.
            if where and target != said:
                where = quote_sheetname(target)
            token.value = (where + "!" if where else "") + ref.upper()
    return tokens.render()


# ---------------------------------------------------------------- reading the model's text

def _clean(cell: str) -> tuple[str, bool]:
    """A cell's text without its Markdown marks, and whether the whole cell was bold."""
    text = cell.strip().replace("\\|", "|")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    if text.startswith("="):
        return text, False
    bold = len(text) > 4 and text[:2] == text[-2:] in ("**", "__")
    if bold:
        text = text[2:-2].strip()
    if len(text) > 2 and text[0] == text[-1] == "`":
        text = text[1:-1]
    return re.sub(r"\*\*(.+?)\*\*", r"\1", text), bold


def _split(line: str, sep: str) -> list[str]:
    """A CSV or tab-separated line's fields. A field in double quotes loses them ("1,200" is 1,200); a formula
    keeps its quotes and is split only at separators outside its brackets and strings, so the commas between
    its arguments stay in it whether or not the model quoted the whole formula."""
    fields, field, depth, quoted = [], "", 0, False
    for ch in line:
        if ch == sep and not quoted and depth <= 0:
            fields.append(field)
            field, depth = "", 0
            continue
        field += ch
        if ch == '"':
            quoted = not quoted
        elif not quoted and field.lstrip().startswith("="):
            depth += (ch == "(") - (ch == ")")
    fields.append(field)
    out = []
    for field in fields:
        field = field.strip()
        if len(field) > 1 and field[0] == field[-1] == '"':
            field = field[1:-1].replace('""', '"')
        out.append(field)
    return out


def _sheets(text: str) -> list[tuple[str | None, list[list[str]]]]:
    """The sheets the text describes: each one's name as written (None for none) and its rows of cell text."""
    sheets: list[tuple[str | None, list[list[str]]]] = [(None, [])]
    lines = text.replace("\r\n", "\n").split("\n")
    # A Markdown table may be written without the pipes at the ends of its rows; its rule line still shows it.
    piped = any("|" in line and _TABLE_RULE.fullmatch(line.strip()) for line in lines)
    for line in lines:
        bare = line.strip()
        if not bare or bare.startswith("```") or re.fullmatch(r"[-*_]{3,}", bare) or _TABLE_RULE.fullmatch(bare):
            continue
        if heading := _HEADING.fullmatch(bare):
            name = _clean(heading[1])[0]
            if sheets[-1][1]:
                sheets.append((name, []))
            else:
                # A heading straight after another names the sheet; the one before was the document's title.
                sheets[-1] = (name, [])
            continue
        if bare.startswith("|") or (piped and re.search(r"(?<!\\)\|", bare)):
            bare = bare[1:] if bare.startswith("|") else bare
            bare = bare[:-1] if bare.endswith("|") and not bare.endswith("\\|") else bare
            row = re.split(r"(?<!\\)\|", bare)
        elif "\t" in line:
            row = _split(line.strip("\r\n"), "\t")   # not stripped further: an empty first cell is a cell
        else:
            row = _split(bare, ",")
        sheets[-1][1].append(row)
    if not sheets[-1][1] and len(sheets) > 1:
        sheets.pop()
    return sheets


def _sheet_names(said: list[str | None]) -> list[str]:
    """Names Excel accepts: at most 31 characters, none of []:*?/\\, no apostrophe at either end, none repeated."""
    names: list[str] = []
    for n, name in enumerate(said, 1):
        name = re.sub(r"\s+", " ", re.sub(r"[\[\]:*?/\\]", " ", name or "")).strip(" '")[:31].strip(" '")
        name = name or f"Sheet{n}"
        if name.lower() == "history":
            name += " 1"
        base, count = name, 2
        while name.lower() in (taken.lower() for taken in names):
            suffix = f" ({count})"
            name, count = base[:31 - len(suffix)] + suffix, count + 1
        names.append(name)
    return names


# ---------------------------------------------------------------- making a workbook

def _quiet(data: bytes, digits: dict[int, list[str]]) -> bytes:
    """The workbook with Excel's "number stored as text" mark turned off on cells whose digits are a name.
    openpyxl does not write ignoredErrors, so it goes into the sheet's XML in the place the schema gives it."""
    if not any(digits.values()):
        return data
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            part = source.read(item.filename)
            sheet = re.fullmatch(r"xl/worksheets/sheet(\d+)\.xml", item.filename)
            if sheet and digits.get(int(sheet[1]) - 1):
                xml = part.decode("utf-8")
                after = re.search(r"<(smartTags|drawing|legacyDrawing|legacyDrawingHF|drawingHF|picture|oleObjects|"
                                  r"controls|webPublishItems|tableParts|extLst)\b|</worksheet>", xml)
                block = ('<ignoredErrors><ignoredError sqref="' + " ".join(digits[int(sheet[1]) - 1])
                         + '" numberStoredAsText="1"/></ignoredErrors>')
                part = (xml[:after.start()] + block + xml[after.start():]).encode("utf-8")
            target.writestr(item, part)
    return out.getvalue()


def _runs(cells: set[tuple[int, int]]) -> list[str]:
    """Cells as ranges, one per unbroken run down a column: {(3, 2), (3, 3)} gives ["C2:C3"]."""
    ranges = []
    for column in sorted({c for c, _ in cells}):
        letter = get_column_letter(column)
        rows = sorted(r for c, r in cells if c == column)
        start = rows[0]
        for prev, row in zip(rows, rows[1:] + [0]):
            if row != prev + 1:
                ranges.append(f"{letter}{start}" if start == prev else f"{letter}{start}:{letter}{prev}")
                start = row
    return ranges


def _shape_of(formula: str, sheet: str, written: dict[tuple[str, int, int], str]) -> str | None:
    """The number format of the first formatted cell a checked formula refers to, in the order it names them."""
    for token in Tokenizer(formula).items:
        if token.type == "OPERAND" and token.subtype == "RANGE":
            where, _, ref = token.value.rpartition("!")
            if span := _bounds(ref):
                said = (where[1:-1].replace("''", "'") if where.startswith("'") else where) or sheet
                c1, r1, c2, r2 = span
                for (name, c, r), shape in written.items():
                    if name == said and c1 <= c <= c2 and r1 <= r <= r2 and shape != "@":
                        return shape
    return None


def _fill(ws, rows: list[list[str]], sheets: dict[str, str], problems: list[str],
          written: dict[tuple[str, int, int], str]) -> list[str]:
    """Writes one table into the sheet, styled; returns the ranges of cells whose digits are a name. `written`
    collects every number format given, so a formula in a column without values can take the format of what
    it refers to."""
    header = [_clean(cell)[0] for cell in rows[0]]
    names = [bool(_NAME_HEADER.search(h)) for h in header]
    body = [[(_typed(text, c < len(names) and names[c]), bold) for c, (text, bold) in
             enumerate(_clean(cell) for cell in row)] for row in rows[1:]]
    totals = {r for r, row in enumerate(body)
              if (first := next((t for t, _ in row if t.kind != "empty"), None)) is not None
              and first.kind == "text" and _TOTAL.fullmatch(first.value)
              and any(t.kind in ("number", "percent", "money", "formula") for t, _ in row)}
    width = max(len(header), *(len(row) for row in body)) if body else len(header)
    for row in body:
        row += [(_Typed(None, "empty"), False)] * (width - len(row))

    # A total the model added up itself becomes a SUM of the cells above it, when it is exactly their sum.
    for r in sorted(totals):
        start = max((t for t in totals if t < r), default=-1) + 1
        for c, (typed, bold) in enumerate(body[r]):
            above = [body[i][c][0] for i in range(start, r)]
            if (typed.kind in ("number", "money", "percent") and len(above) >= 2
                    and all(t.kind in (typed.kind, "empty") for t in above)
                    and sum(1 for t in above if t.kind == typed.kind) >= 2
                    and abs(sum(t.value for t in above if t.kind == typed.kind) - typed.value) < 1e-6):
                letter = get_column_letter(c + 1)
                body[r][c] = (_Typed(f"=SUM({letter}{start + 2}:{letter}{r + 1})", "formula"), bold)

    # Each column's format, from the values written in it; formulas take the format of the column's values.
    formats: list[dict[str, str]] = []
    for c in range(width):
        typed = [row[c][0] for row in body]
        kinds = Counter(t.kind for t in typed if t.kind in ("number", "percent", "money", "date", "datetime"))
        column: dict[str, str] = {}
        for kind in kinds:
            same = [t for t in typed if t.kind == kind]
            units = Counter(t.unit for t in same)
            column[kind] = _format(kind, min(max(t.decimals for t in same), 4), any(t.grouped for t in same),
                                   units.most_common(1)[0][0], any(abs(t.value) >= 1e11 for t in same
                                                                    if kind == "number"))
        if kinds:
            column["formula"] = column[kinds.most_common(1)[0][0]]
        elif c < len(header) and _PERCENT_HEADER.search(header[c]):
            column["formula"] = "0.0%"
        formats.append(column)

    font, strong = Font(name=_FONT, size=11), Font(name=_FONT, size=11, bold=True)
    widths = [0] * width
    for c, text in enumerate(header, 1):
        cell = ws.cell(1, c, text or None)
        if text:
            cell.data_type = "s"
        cell.font, cell.fill, cell.border = strong, _HEADER_FILL, Border(_GRID, _GRID, _GRID, _RULE)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        widths[c - 1] = _width(text) + 3   # room for the filter's arrow
    digits: set[tuple[int, int]] = set()
    for r, row in enumerate(body, 2):
        total = r - 2 in totals
        for c, (typed, bold) in enumerate(row, 1):
            column = formats[c - 1]
            cell = ws.cell(r, c)
            cell.font = strong if (bold or total) else font
            cell.border = Border(_GRID, _GRID, _RULE if total else _GRID, _GRID)
            if total:
                cell.fill = _TOTAL_FILL
            if typed.kind == "empty":
                continue
            numeric = typed.kind in ("number", "percent", "money", "date", "datetime")
            if typed.kind == "formula":
                try:
                    cell.value = _formula(typed.value, ws.title, c, r, sheets, set())
                except _Bad as bad:
                    problems.append(f"{ws.title}!{cell.coordinate}: {bad}")
                    continue
                label = row[0][0]
                shape = column.get("formula") or (
                    "0.0%" if label.kind == "text" and _PERCENT_HEADER.search(label.value) else None) or _shape_of(
                    cell.value, ws.title, written)
                if shape:
                    cell.number_format = shape
                    numeric = True
                elif typed.value.upper().startswith(_DATE_FUNCTIONS):
                    cell.number_format = "yyyy-mm-dd"
                shown = max((_width(_shown(t)) for t, _ in (line[c - 1] for line in body)
                             if t.kind in ("number", "percent", "money")), default=8) + 2
            else:
                cell.value = typed.value
                if typed.kind in ("text", "digits"):
                    cell.data_type = "s"
                cell.number_format = column.get(typed.kind) or _format(typed.kind)
                shown = _width(_shown(typed))
                if typed.kind == "digits":
                    digits.add((c, r))
            if cell.number_format != "General":
                written[ws.title, c, r] = cell.number_format
            if numeric:
                cell.alignment = Alignment(horizontal="right", vertical="center")
            else:
                wrap = shown > _WRAP or "\n" in str(typed.value)
                cell.alignment = Alignment(vertical="center", wrap_text=wrap or None)
            widths[c - 1] = max(widths[c - 1], min(shown, _WRAP) if typed.kind == "text" else shown)
    for c, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(c)].width = min(max(w + 2, 8), _WIDEST)

    if body:
        ws.freeze_panes = "A2"
        last = max((r for r in range(len(body)) if r not in totals), default=None)
        if last is not None:
            ws.auto_filter.ref = f"A1:{get_column_letter(width)}{last + 2}"
    ws.print_title_rows = "1:1"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.orientation = "landscape" if sum(min(max(w + 2, 8), _WIDEST) for w in widths) > 100 else "portrait"
    ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    return _runs(digits)


def make(text: str) -> bytes:
    """The workbook the text describes: one table per sheet, "# name" lines naming the sheets."""
    said = _sheets(text)
    if not any(rows for _, rows in said):
        raise ValueError("the text has no table rows: write each sheet as Markdown table rows or CSV lines, the "
                         "first row the headers, and a \"# name\" line before each sheet to name it")
    titles = _sheet_names([name for name, _ in said])
    sheets: dict[str, str] = {}
    for (name, _), title in zip(said, titles):
        sheets.setdefault(title.lower(), title)
        if name:
            sheets.setdefault(name.strip().lower(), title)
    book = Workbook()
    book.properties.creator = "Mibo"
    problems: list[str] = []
    written: dict[tuple[str, int, int], str] = {}
    digits: dict[int, list[str]] = {}
    for n, ((_, rows), title) in enumerate(zip(said, titles)):
        ws = book.active if n == 0 else book.create_sheet()
        ws.title = title
        if rows:
            digits[n] = _fill(ws, rows, sheets, problems, written)
    if problems:
        raise ValueError("the workbook was not written, because of these cells: " + "; ".join(problems[:8])
                         + (f"; and {len(problems) - 8} more" if len(problems) > 8 else "")
                         + ". Correct them and write the whole text again.")
    # openpyxl stores no computed values, so Excel computes every formula when it opens the file.
    book.calculation.fullCalcOnLoad = True
    out = io.BytesIO()
    book.save(out)
    return _quiet(out.getvalue(), digits)


# ---------------------------------------------------------------- changing a workbook

def _lost(z: zipfile.ZipFile) -> list[str]:
    """What the workbook holds that openpyxl does not read, and that saving it again would therefore drop."""
    names = z.namelist()
    lost = []
    if any(n.startswith("xl/charts/") for n in names):
        lost.append("charts")
    if any(n.startswith("xl/drawings/drawing") and re.search(rb"<xdr:sp[ >]", z.read(n)) for n in names):
        lost.append("shapes or text boxes")
    if any(n.startswith(("xl/slicers/", "xl/timelines/")) for n in names):
        lost.append("slicers")
    if any(n.startswith(("xl/activeX/", "xl/ctrlProps/")) for n in names):
        lost.append("form controls")
    if any(n.startswith("xl/threadedComments/") for n in names):
        lost.append("threaded comments")
    if any(n.startswith("xl/worksheets/sheet") and b"sparklineGroup" in z.read(n) for n in names):
        lost.append("sparklines")
    return lost


def _hits(value, old: str) -> tuple[int, bool]:
    """How often `old` is in the cell, and whether it is the whole cell. Text and formulas match in part;
    numbers, dates and true/false only as a whole, written as make() would read them or as stored."""
    if isinstance(value, (str, CellRichText)):
        words = str(value)
        return (1, True) if words == old else (words.count(old), False)
    if isinstance(value, bool):
        return int(str(value).upper() == old.upper()), True
    said = _typed(old)
    if isinstance(value, (int, float)):
        same = said.kind in ("number", "percent", "money") and abs(said.value - value) < 1e-9 * max(1, abs(value))
        return int(same), True
    if isinstance(value, (datetime.date, datetime.datetime)):
        moment = value if isinstance(value, datetime.datetime) else datetime.datetime.combine(value, datetime.time())
        stored = said.value if said.kind in ("date", "datetime") else None
        if isinstance(stored, datetime.date) and not isinstance(stored, datetime.datetime):
            stored = datetime.datetime.combine(stored, datetime.time())
        serial = said.kind == "number" and abs(said.value - to_excel(moment)) < 1e-9
        return int(stored == moment or serial), True
    return 0, False


def _swap_rich(value: CellRichText, old: str, new: str, every: bool):
    """Rich text with `old` replaced inside the runs that hold it, so each run keeps its look; flattened to plain
    text when `old` crosses from one run into the next."""
    parts = [part.text if isinstance(part, TextBlock) else part for part in value]
    if sum(words.count(old) for words in parts) < str(value).count(old):
        plain = str(value)
        return plain.replace(old, new) if every else plain.replace(old, new, 1)
    for n, (part, words) in enumerate(zip(value, parts)):
        if old in words:
            words = words.replace(old, new) if every else words.replace(old, new, 1)
            value[n] = TextBlock(part.font, words) if isinstance(part, TextBlock) else words
            if not every:
                break
    return value


def replaced(data: bytes, old: str, new: str, every: bool) -> bytes:
    """The workbook with the cell text `old` replaced by `new`, once, or in every cell when `every`. A whole-cell
    match takes `new` as make() would type it (a number, a date, a formula); a match inside a cell's text stays
    text, and one inside a formula keeps it a formula. Styles, widths, formulas and sheets are kept."""
    if not old:
        raise ValueError("old_string is empty: give the exact text of the cell, or of part of it, to replace")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            lost = _lost(z)
        book = load_workbook(io.BytesIO(data), rich_text=True)
    except (zipfile.BadZipFile, KeyError, OSError):
        raise ValueError("the file is not a readable Excel workbook (it may be damaged or protected by a password)") \
            from None
    if lost:
        raise ValueError(f"this workbook holds {', '.join(lost)}, which would be lost if it were saved again here: "
                         "tell the person so, or write the changed table to a new workbook with write_file")
    hits = []
    for ws in book.worksheets:
        for line in ws.iter_rows():
            for cell in line:
                if cell.value is not None:
                    count, whole = _hits(cell.value, old)
                    if count:
                        hits.append((ws, cell, count, whole))
    found = sum(count for _, _, count, _ in hits)
    if not found:
        if any(mark in old.strip() for mark in ("\n", "\t", "|")):
            raise ValueError("old_string spans more than one cell: in a workbook, replace the text of one cell at "
                             "a time")
        raise ValueError("old_string was not found in the workbook (it must match the text of one cell, or part "
                         "of it, exactly; a number or date matches only as the whole cell)")
    if found > 1 and not every:
        where = ", ".join(f"{ws.title}!{cell.coordinate}" for ws, cell, _, _ in hits[:5])
        raise ValueError(f"old_string is in the workbook {found} times ({where}{', …' if len(hits) > 5 else ''}): "
                         "give the whole text of the one cell meant so it is found once, or set replace_all to "
                         "change every one")
    sheets = {ws.title.lower(): ws.title for ws in book.worksheets}
    names = {name.lower() for name in book.defined_names} | {
        name.lower() for ws in book.worksheets for name in ws.defined_names}
    for ws, cell, _, whole in hits:
        try:
            _replace(ws, cell, whole, old, new, every, sheets, names)
        except _Bad as bad:
            raise ValueError(f"{ws.title}!{cell.coordinate}: {bad}") from None
        if not every:
            break
    digits = {n: _runs(cells) for n, ws in enumerate(book.worksheets)
              if (cells := {(cell.column, cell.row) for line in ws.iter_rows() for cell in line
                            if cell.data_type == "s" and isinstance(cell.value, str)
                            and re.fullmatch(r"[+-]?\d+", cell.value)})}
    book.calculation.fullCalcOnLoad = True
    out = io.BytesIO()
    book.save(out)
    return _quiet(out.getvalue(), digits)


def _replace(ws, cell, whole: bool, old: str, new: str, every: bool, sheets: dict[str, str], names: set[str]) -> None:
    """One matched cell changed: a whole match typed as make() types it, a part match within the text or formula."""
    before = cell.value
    if whole:
        header = ws.cell(1, cell.column).value if cell.row > 1 else None
        typed = (_typed(new.strip(), isinstance(header, str) and bool(_NAME_HEADER.search(header)))
                 if cell.row > 1 else _Typed(new, "text"))
        if typed.kind == "empty":
            cell.value = None
            return
        value = typed.value
        if typed.kind == "formula":
            value = _formula(value, ws.title, cell.column, cell.row, sheets, names)
        cell.value = value
        if typed.kind in ("text", "digits"):
            cell.data_type = "s"
        if cell.number_format in ("General", "@") and typed.kind not in ("text", "formula"):
            cell.number_format = _format(typed.kind, typed.decimals, typed.grouped, typed.unit,
                                         typed.kind == "number" and abs(typed.value) >= 1e11)
    elif isinstance(before, CellRichText):
        cell.value = _swap_rich(before, old, new, every)
    else:
        value = before.replace(old, new) if every else before.replace(old, new, 1)
        formula = cell.data_type == "f"
        if formula:
            value = _formula(value, ws.title, cell.column, cell.row, sheets, names)
        cell.value = value
        if not formula:
            cell.data_type = "s"


def summary(data: bytes) -> str:
    """A few words for the model: "an Excel workbook with 收支 (14 rows), 汇总 (3 rows)"."""
    book = load_workbook(io.BytesIO(data), read_only=True)
    parts = []
    for ws in book.worksheets[:6]:
        rows = ws.max_row or sum(1 for _ in ws.iter_rows())
        first = next(ws.iter_rows(max_row=1, values_only=True), ())
        if rows <= 1 and not any(v is not None for v in first):
            parts.append(f"{ws.title} (empty)")
        else:
            parts.append(f"{ws.title} ({rows} row{'s' if rows != 1 else ''})")
    more = len(book.worksheets) - 6
    book.close()
    return "an Excel workbook with " + ", ".join(parts) + (f", and {more} more sheets" if more > 0 else "")
