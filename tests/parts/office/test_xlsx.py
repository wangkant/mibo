"""Excel workbooks made from the table a model writes, and changed by exact replacement: values typed the way a
person means them, formulas live and checked, the table styled, and an edit that keeps everything else."""
from __future__ import annotations

import datetime
import io
import zipfile
from xml.etree import ElementTree

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont

from mibo.shell.office import xlsx

BUDGET = """# 2026 年家庭预算
## 收支
| 项目 | 类别 | 金额 | 占比 | 日期 |
|---|---|---|---|---|
| 房租 | 固定 | 4,500 | =C2/C$6 | 2026-01-05 |
| 餐饮 | 日常 | 2,300.50 | =C3/C$6 | 2026-01-10 |
| 交通 | 日常 | 600 | =C4/C$6 | 2026-01-12 |
| 教育 | 固定 | 1,000 | =C5/C$6 | 2026-01-15 |
| 合计 | | =SUM(C2:C5) | =SUM(D2:D5) | |

# 汇总
指标,数值
支出总额,=收支!C6
房租占比,='收支'!D2
"""

CONTACTS = """姓名,手机,身份证号,工号,邮编,余额,备注
张三,13812345678,110101199001011234,0012,100080,"1,200",老同学
李四,13987654321,11010119900101123X,0013,200000,35.5,=== 待确认 ===
"""


def _book(data: bytes):
    return load_workbook(io.BytesIO(data))


def test_numbers_dates_and_percentages_are_stored_as_values_with_a_matching_format() -> None:
    ws = _book(xlsx.make(BUDGET))["收支"]
    assert ws["C2"].value == 4500 and ws["C3"].value == 2300.5
    assert ws["C2"].number_format == ws["C3"].number_format == "#,##0.00"
    assert ws["E2"].value == datetime.datetime(2026, 1, 5) and ws["E2"].number_format == "yyyy-mm-dd"
    ws = _book(xlsx.make("a,b,c\n12.5%,¥1,200.00,30元"))["Sheet1"]
    assert ws["A2"].value == 0.125 and ws["A2"].number_format == "0.0%"


def test_typing_follows_how_people_write() -> None:
    assert xlsx._typed("33.3%").value == 0.333
    assert (xlsx._typed("¥1,200.50").value, xlsx._typed("¥1,200.50").kind) == (1200.5, "money")
    assert xlsx._format("money", 2, True, "¥") == '"¥"#,##0.00'
    assert (xlsx._typed("30元").value, xlsx._format("money", 0, True, "元")) == (30, '#,##0"元"')
    assert xlsx._typed("2026-02-30").kind == "text"
    assert xlsx._typed("2026-03-01 09:30").value == datetime.datetime(2026, 3, 1, 9, 30)
    assert xlsx._typed("-42").value == -42


def test_digits_that_name_something_stay_text() -> None:
    ws = _book(xlsx.make(CONTACTS))["Sheet1"]
    for ref, text in (("B2", "13812345678"), ("C2", "110101199001011234"), ("C3", "11010119900101123X"),
                      ("D2", "0012"), ("E2", "100080")):
        assert ws[ref].value == text and ws[ref].data_type == "s" and ws[ref].number_format == "@"
    assert ws["F2"].value == 1200 and ws["F3"].value == 35.5
    # Outside a column of names, digits are numbers unless they cannot be.
    assert xlsx._typed("12345").value == 12345
    assert xlsx._typed("1234567890123456").kind == "digits"
    assert xlsx._typed("+8613812345678").kind == "digits"


def test_excels_mark_on_text_digits_is_turned_off_in_well_formed_xml() -> None:
    data = xlsx.make(CONTACTS)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name in z.namelist():
            if name.endswith((".xml", ".rels")):
                ElementTree.fromstring(z.read(name))
        sheet = z.read("xl/worksheets/sheet1.xml").decode()
    assert '<ignoredError sqref="B2:B3 C2:C3 D2:D3 E2:E3" numberStoredAsText="1"/>' in sheet
    assert sheet.index("<ignoredErrors>") > sheet.index("<pageSetup")


def test_text_that_only_looks_like_a_formula_stays_text() -> None:
    ws = _book(xlsx.make(CONTACTS))["Sheet1"]
    assert ws["G3"].value == "=== 待确认 ===" and ws["G3"].data_type == "s"
    assert xlsx._typed("=> 下一步").kind == "text" and xlsx._typed("=").kind == "text"


def test_formulas_stay_live_as_written_and_calculate_on_opening() -> None:
    book = _book(xlsx.make(BUDGET))
    ws = book["收支"]
    assert ws["C6"].value == "=SUM(C2:C5)" and ws["D2"].value == "=C2/C$6"
    assert ws["D2"].number_format == "0.0%" and ws["C6"].number_format == "#,##0.00"
    assert book["汇总"]["B2"].value == "=收支!C6" and book["汇总"]["B3"].value == "='收支'!D2"
    assert book.calculation.fullCalcOnLoad


def test_a_formula_in_a_column_without_values_takes_a_format_from_its_row_or_its_references() -> None:
    ws = _book(xlsx.make(BUDGET + "储蓄率,=收支!D2\n住房,=SUMIF(收支!B2:B5,\"固定\",收支!C2:C5)\n"))["汇总"]
    assert ws["B2"].number_format == "#,##0.00"   # what 收支!C6 shows
    assert ws["B4"].number_format == "0.0%" and ws["B5"].number_format == "#,##0.00"
    assert ws["B5"].alignment.horizontal == "right"


def test_formulas_are_spelled_as_excel_stores_them() -> None:
    ws = _book(xlsx.make("a,b\n1,=sum(a2:a2)\n2,\"=TEXTJOIN(\"\",\"\",TRUE,A2:A3)\""))["Sheet1"]
    assert ws["B2"].value == "=SUM(A2:A2)"
    assert ws["B3"].value == '=_xlfn.TEXTJOIN(",",TRUE,A2:A3)'


def test_a_formula_split_at_its_commas_in_csv_is_put_back_together() -> None:
    ws = _book(xlsx.make("a,b,c\n1,2,=IF(A2>B2,A2,B2)\n3,4,=IF(A3>0,\"正\",\"负\")"))["Sheet1"]
    assert ws["C2"].value == "=IF(A2>B2,A2,B2)" and ws["C3"].value == '=IF(A3>0,"正","负")'
    ws = _book(xlsx.make("a\tb\tc\n\t5\t=B2*2"))["Sheet1"]
    assert ws["A2"].value is None and ws["C2"].value == "=B2*2"


def test_a_total_written_as_a_number_becomes_a_sum() -> None:
    ws = _book(xlsx.make("| 项目 | 金额 |\n|---|---|\n| 甲 | 100 |\n| 乙 | 250 |\n| 合计 | 350 |"))["Sheet1"]
    assert ws["B4"].value == "=SUM(B2:B3)" and ws["A4"].font.b
    ws = _book(xlsx.make("| 项目 | 金额 |\n|---|---|\n| 甲 | 100 |\n| 乙 | 250 |\n| 合计 | 999 |"))["Sheet1"]
    assert ws["B4"].value == 999


@pytest.mark.parametrize(("text", "words"), [
    ("a,b\n1,=SUM(A2:A3", "do not pair up"),
    ("a,b\n1,\"=IF(A2>0,\"\"是)\"", "not closed"),
    ("a,b\n1,=SUM(收入)", "neither a cell reference"),
    ("a,b\n1,=FOO(A2)", "FOO, which Excel does not have"),
    ("a,b\n1,=支出!A2", "the sheet 支出"),
    ("a,b\n1,=SUM(B2:B3)", "its own cell B2"),
    ("a,b\n1,=UNIQUE(A2:A9)", "fills several cells"),
    ("a,b\n1,=#REF!+1", "#REF!"),
    ("a,b\n1,=XFE1", "beyond the last"),
])
def test_a_malformed_formula_stops_the_workbook_with_a_sentence_naming_the_cell(text: str, words: str) -> None:
    with pytest.raises(ValueError, match="Sheet1!B2") as caught:
        xlsx.make(text)
    assert words in str(caught.value)


def test_the_table_is_styled_frozen_filtered_and_sized() -> None:
    ws = _book(xlsx.make(BUDGET))["收支"]
    assert ws.freeze_panes == "A2"
    assert ws.auto_filter.ref == "A1:E5"   # the total row stays out of sorting
    assert ws["A1"].font.b and ws["A1"].fill.fgColor.rgb.endswith("DDEBF7")
    assert ws["B2"].font.name == "等线"
    assert ws["C2"].alignment.horizontal == "right" and ws["D2"].alignment.horizontal == "right"
    assert ws["A6"].font.b and ws.print_title_rows == "$1:$1"
    long = "这是一段很长的说明文字，" * 6
    ws = _book(xlsx.make(f"编号,说明\nA1,{long}"))["Sheet1"]
    assert ws["B2"].alignment.wrap_text and ws.column_dimensions["B"].width == xlsx._WRAP + 2
    ws = _book(xlsx.make("名称,English\n中文名字很长,abc"))["Sheet1"]
    assert ws.column_dimensions["A"].width == 14 and ws.column_dimensions["B"].width == 12


def test_sheet_names_are_ones_excel_accepts_and_references_follow_them() -> None:
    names = xlsx._sheet_names(["收支/2026", "收支 2026", "x" * 40, None, "'引号'", "history"])
    assert names == ["收支 2026", "收支 2026 (2)", "x" * 31, "Sheet4", "引号", "history 1"]
    book = _book(xlsx.make("# 收支/2026\na,b\n1,2\n# 汇总\nx,y\n总,='收支/2026'!B2"))
    assert book.sheetnames == ["收支 2026", "汇总"]
    assert book["汇总"]["B2"].value == "='收支 2026'!B2"


def test_a_title_heading_before_the_sheets_name_is_dropped_and_markdown_marks_go() -> None:
    book = _book(xlsx.make("# 预算\n## 一月\n项目 | 金额\n--- | ---\n**房租** | 1\n房租<br>押金 | 2"))
    ws = book["一月"]
    assert book.sheetnames == ["一月"]
    assert ws["A2"].value == "房租" and ws["A2"].font.b and ws["A3"].value == "房租\n押金"


def test_text_without_a_table_is_refused() -> None:
    with pytest.raises(ValueError, match="no table rows"):
        xlsx.make("# 空\n\n")


def test_a_whole_cell_replacement_is_typed_and_keeps_the_cells_look() -> None:
    data = xlsx.make(BUDGET)
    book = _book(xlsx.replaced(data, "600", "800", False))
    ws = book["收支"]
    assert ws["C4"].value == 800 and ws["C4"].number_format == "#,##0.00" and ws["C4"].font.name == "等线"
    assert ws["C6"].value == "=SUM(C2:C5)" and ws.freeze_panes == "A2" and book.sheetnames == ["收支", "汇总"]
    assert ws.column_dimensions["A"].width == _book(data)["收支"].column_dimensions["A"].width
    ws = _book(xlsx.replaced(data, "2026-01-12", "2026-02-01", False))["收支"]
    assert ws["E4"].value == datetime.datetime(2026, 2, 1)
    ws = _book(xlsx.replaced(data, "=SUM(C2:C5)", "=SUM(C2:C4)", False))["收支"]
    assert ws["C6"].value == "=SUM(C2:C4)"


def test_a_part_replacement_stays_text_and_inside_a_formula_stays_a_formula() -> None:
    data = xlsx.make(CONTACTS)
    ws = _book(xlsx.replaced(data, "老", "大学", False))["Sheet1"]
    assert ws["G2"].value == "大学同学"
    ws = _book(xlsx.replaced(xlsx.make(BUDGET), "C2:C5", "C2:C4", False))["收支"]
    assert ws["C6"].value == "=SUM(C2:C4)"
    ws = _book(xlsx.replaced(data, "13812345678", "13900001111", False))["Sheet1"]
    assert ws["B2"].value == "13900001111" and ws["B2"].data_type == "s"


def test_a_replacement_that_breaks_a_formula_is_refused() -> None:
    with pytest.raises(ValueError, match=r"收支!C6: .*pair up"):
        xlsx.replaced(xlsx.make(BUDGET), "=SUM(C2:C5)", "=SUM(C2:C5", False)


def test_not_found_and_found_several_times_say_so() -> None:
    data = xlsx.make(BUDGET)
    with pytest.raises(ValueError, match="not found"):
        xlsx.replaced(data, "保险", "车险", False)
    with pytest.raises(ValueError, match=r"2 times \(收支!B2, 收支!B5\)"):
        xlsx.replaced(data, "固定", "长期", False)
    with pytest.raises(ValueError, match="more than one cell"):
        xlsx.replaced(data, "房租 | 固定", "x", False)
    ws = _book(xlsx.replaced(data, "固定", "长期", True))["收支"]
    assert ws["B2"].value == ws["B5"].value == "长期"


def test_rich_text_keeps_its_runs() -> None:
    book = Workbook()
    book.active["A1"] = CellRichText(["普通", TextBlock(InlineFont(b=True), "加粗部分")])
    out = io.BytesIO()
    book.save(out)
    cell = load_workbook(io.BytesIO(xlsx.replaced(out.getvalue(), "加粗", "强调", False)), rich_text=True).active["A1"]
    assert str(cell.value) == "普通强调部分" and cell.value[1].font.b


def test_a_workbook_with_a_chart_is_not_saved_over() -> None:
    from openpyxl.chart import BarChart, Reference
    book = Workbook()
    ws = book.active
    ws.append(["a", 1])
    chart = BarChart()
    chart.add_data(Reference(ws, min_col=2, min_row=1, max_row=1))
    ws.add_chart(chart, "D2")
    out = io.BytesIO()
    book.save(out)
    with pytest.raises(ValueError, match="charts"):
        xlsx.replaced(out.getvalue(), "a", "b", False)
    with pytest.raises(ValueError, match="not a readable Excel workbook"):
        xlsx.replaced(b"not a zip", "a", "b", False)


def test_summary_names_the_sheets_and_their_rows() -> None:
    assert xlsx.summary(xlsx.make(BUDGET)) == "an Excel workbook with 收支 (6 rows), 汇总 (3 rows)"
    assert xlsx.summary(xlsx.make("a\n1")) == "an Excel workbook with Sheet1 (2 rows)"
