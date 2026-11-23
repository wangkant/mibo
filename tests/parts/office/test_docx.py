"""A Word document made from the model's Markdown is one a person would hand in, and an exact replacement inside
one changes only the words it names: read back with python-docx and checked part by part, since nothing here may
start Word to look at it."""
from __future__ import annotations

import io
import zipfile

import pytest
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from lxml import etree

from mibo.shell import office
from mibo.shell.office import docx as word

REPORT = """# 2026 年第三季度工作总结

## 一、总体情况

本季度团队完成了 **全部三项** 核心目标，详见 [项目主页](https://example.com/p)。其中 *用户增长* 超出预期，`API` 调用量增长 42%。

## 二、主要成果

1. 上线新版客户端
   - 启动速度提升 30%
   - 崩溃率降至 0.1%
2. 完成数据迁移

- [x] 季度复盘
- [ ] 年度预算

| 指标 | 目标 | 实际 |
|------|------|:----:|
| 新增用户 | 10,000 | 12,450 |
| 收入（万元） | 300 | 286 |

> 注：收入数据为初步统计。

```python
def growth(a, b):
    return (b - a) / a
```

---

\\newpage

### 下季度计划

1. 继续推进新系统替换
2. 完成年度预算
"""


@pytest.fixture(scope="module")
def made() -> bytes:
    return office.make(".docx", REPORT)


def _doc(data: bytes):
    return Document(io.BytesIO(data))


def _styles(data: bytes) -> list[tuple[str, str]]:
    return [(p.style.name, p.text) for p in _doc(data).paragraphs if p.text]


def test_every_part_is_well_formed_xml_and_the_same_text_makes_the_same_bytes(made):
    with zipfile.ZipFile(io.BytesIO(made)) as package:
        for name in package.namelist():
            if name.endswith((".xml", ".rels")):
                etree.fromstring(package.read(name))
        names = package.namelist()
        core = package.read("docProps/core.xml").decode("utf-8")
    assert "word/footer1.xml" in names and not any("thumbnail" in n for n in names)
    # Nothing of the library's own template: its name, its comment, the dates it was made.
    assert "python-docx" not in core and "2013" not in core and "2026 年第三季度工作总结" in core
    assert office.make(".docx", REPORT) == made


def test_the_page_is_a4_with_word_margins_and_opens_out_of_compatibility_mode(made):
    document = _doc(made)
    section = document.sections[0]
    assert (round(section.page_width.mm), round(section.page_height.mm)) == (210, 297)
    assert round(section.left_margin.cm, 2) == 3.18 and round(section.top_margin.cm, 2) == 2.54
    modes = [s.get(qn("w:val")) for s in document.settings.element.iter(qn("w:compatSetting"))
             if s.get(qn("w:name")) == "compatibilityMode"]
    assert modes == ["15"]
    # Page numbers in the footer, as a field Word fills in.
    assert "PAGE" in section.footer._element.xml


def test_chinese_and_latin_text_each_have_their_font_and_no_theme_overrides_them(made):
    styles = _doc(made).styles
    for name, east in (("Normal", "宋体"), ("Heading 1", "黑体"), ("Title", "黑体"), ("Code", "宋体")):
        fonts = styles[name].element.rPr.find(qn("w:rFonts"))
        assert fonts.get(qn("w:eastAsia")) == east, name
        assert fonts.get(qn("w:asciiTheme")) is None and fonts.get(qn("w:eastAsiaTheme")) is None, name
    lang = styles.element.find(qn("w:docDefaults")).find(qn("w:rPrDefault")).find(qn("w:rPr")).find(qn("w:lang"))
    assert lang.get(qn("w:eastAsia")) == "zh-CN"
    heading = styles["Heading 2"]
    assert heading.paragraph_format.keep_with_next and heading.font.bold and not heading.font.italic


def test_one_top_heading_is_the_title_and_the_sections_under_it_are_word_headings(made):
    rows = _styles(made)
    assert rows[0] == ("Title", "2026 年第三季度工作总结")
    assert ("Heading 1", "一、总体情况") in rows and ("Heading 2", "下季度计划") in rows
    assert _doc(made).paragraphs[0].alignment in (None, WD_ALIGN_PARAGRAPH.CENTER)
    # Several top headings: each is a heading, none a title.
    assert [s for s, _ in _styles(office.make(".docx", "# 一\n\n正文\n\n# 二\n"))][:1] == ["Heading 1"]


def test_inline_marks_become_the_runs_look_and_a_link_opens(made):
    paragraph = next(p for p in _doc(made).paragraphs if p.text.startswith("本季度"))
    runs = [(r.text, r.bold, r.italic) for r in paragraph.runs]
    assert ("全部三项", True, None) in runs and ("用户增长", None, True) in runs
    code = next(r for r in paragraph.runs if r.text == "API")
    assert code._r.rPr.find(qn("w:rFonts")).get(qn("w:ascii")) == "Consolas"
    link = paragraph._p.find(qn("w:hyperlink"))
    assert link is not None and paragraph.part.rels[link.get(qn("r:id"))].target_ref == "https://example.com/p"
    assert "项目主页" in paragraph.text and "**" not in paragraph.text and "[" not in paragraph.text


def _numbering(paragraph) -> tuple[int, int]:
    num_pr = paragraph._p.pPr.numPr
    return num_pr.numId.val, num_pr.ilvl.val


def test_lists_are_real_word_lists_that_nest_by_indent_and_restart_for_each_list(made):
    document = _doc(made)
    items = {p.text: (p.style.name, *_numbering(p)) for p in document.paragraphs if p._p.pPr is not None
             and p._p.pPr.numPr is not None}
    assert items["上线新版客户端"][0] == "List Number" and items["上线新版客户端"][2] == 0
    assert items["启动速度提升 30%"][0] == "List Bullet" and items["启动速度提升 30%"][2] == 1
    assert items["完成数据迁移"][1] == items["上线新版客户端"][1]
    # The list after the table is a new one: it counts from 1 again.
    assert items["继续推进新系统替换"][1] != items["上线新版客户端"][1]
    numbering = document.part.numbering_part.element
    num = next(n for n in numbering.findall(qn("w:num")) if int(n.get(qn("w:numId"))) == items["继续推进新系统替换"][1])
    assert num.find(qn("w:lvlOverride")).find(qn("w:startOverride")).get(qn("w:val")) == "1"
    assert "☑ 季度复盘" in items and "☐ 年度预算" in items


def test_a_list_that_starts_at_another_number_keeps_it_and_1_with_a_chinese_comma_stays_as_written():
    document = _doc(office.make(".docx", "3. 第三步\n4. 第四步\n\n1、这一行照原样保留"))
    first = document.paragraphs[0]
    numbering = document.part.numbering_part.element
    num = next(n for n in numbering.findall(qn("w:num")) if int(n.get(qn("w:numId"))) == _numbering(first)[0])
    assert num.find(qn("w:lvlOverride")).find(qn("w:startOverride")).get(qn("w:val")) == "3"
    last = document.paragraphs[-1]
    assert last.text == "1、这一行照原样保留" and (last._p.pPr is None or last._p.pPr.numPr is None)


def test_a_table_has_a_repeated_shaded_header_and_columns_that_fill_the_page(made):
    document = _doc(made)
    table = document.tables[0]
    assert [c.text for c in table.rows[0].cells] == ["指标", "目标", "实际"]
    assert table.rows[0]._tr.trPr.find(qn("w:tblHeader")) is not None
    assert all(r.bold for r in table.rows[0].cells[0].paragraphs[0].runs)
    assert table.rows[0].cells[0]._tc.tcPr.find(qn("w:shd")).get(qn("w:val")) == "clear"
    section = document.sections[0]
    text_width = (section.page_width - section.left_margin - section.right_margin) // 635
    grid = [int(col.get(qn("w:w"))) for col in table._tbl.tblGrid.findall(qn("w:gridCol"))]
    assert sum(grid) == text_width and int(table._tbl.tblPr.find(qn("w:tblW")).get(qn("w:w"))) == text_width
    # Each cell carries its width too, and numbers line up on the right unless the rule says otherwise.
    assert table.cell(1, 1).width == grid[1] * 635
    assert table.cell(1, 1).paragraphs[0].alignment == WD_ALIGN_PARAGRAPH.RIGHT
    assert table.cell(1, 2).paragraphs[0].alignment == WD_ALIGN_PARAGRAPH.CENTER
    assert table.cell(2, 0).text == "收入（万元）"


def test_quotes_code_rules_and_page_breaks_have_their_own_form(made):
    document = _doc(made)
    rows = _styles(made)
    assert ("Quote", "注：收入数据为初步统计。") in rows
    code = [p for p in document.paragraphs if p.style.name == "Code"]
    assert [p.text for p in code] == ["def growth(a, b):", "    return (b - a) / a"]
    assert document.styles["Code"].element.pPr.find(qn("w:shd")).get(qn("w:fill"))
    assert any(p._p.pPr is not None and p._p.pPr.find(qn("w:pBdr")) is not None for p in document.paragraphs)
    breaks = [br for br in document.element.body.iter(qn("w:br")) if br.get(qn("w:type")) == "page"]
    assert len(breaks) == 1
    # A # line inside a code block is code, not a heading.
    inside = office.make(".docx", "# 说明\n\n```\n# 注释\n```\n")
    assert _styles(inside)[0] == ("Title", "说明") and ("Code", "# 注释") in _styles(inside)


def test_the_summary_says_what_was_made(made):
    assert office.summary(".docx", made) == ("a Word document titled “2026 年第三季度工作总结”, of 16 paragraphs "
                                             "and 1 table")


# ---------------------------------------------------------------- replacement

def test_a_replacement_touches_only_what_differs_and_keeps_the_bold_run_bold(made):
    after = office.replaced(".docx", made, "完成了 全部三项 核心", "完成了 全部四项 核心", False)
    paragraph = next(p for p in _doc(after).paragraphs if p.text.startswith("本季度"))
    assert ("全部四项", True) in [(r.text, r.bold) for r in paragraph.runs]
    assert paragraph.style.name == "Normal" and paragraph._p.find(qn("w:hyperlink")) is not None
    assert office.replaced(".docx", made, "完成了 全部三项 核心", "完成了 全部四项 核心", False) == after


def test_a_replacement_across_runs_keeps_the_style_and_every_untouched_run(made):
    after = office.replaced(".docx", made, "超出预期，API 调用量", "略超预期，接口调用量", False)
    paragraph = next(p for p in _doc(after).paragraphs if p.text.startswith("本季度"))
    assert "略超预期，接口调用量增长 42%" in paragraph.text
    assert ("全部三项", True) in [(r.text, r.bold) for r in paragraph.runs]
    assert ("用户增长", True) in [(r.text, r.italic) for r in paragraph.runs]


def test_a_replacement_reaches_table_cells_headers_and_footers(made):
    document = _doc(made)
    document.sections[0].header.paragraphs[0].text = "内部资料"
    out = io.BytesIO()
    document.save(out)
    after = office.replaced(".docx", out.getvalue(), "12,450", "12,500", False)
    after = office.replaced(".docx", after, "内部资料", "公开资料", False)
    changed = _doc(after)
    assert changed.tables[0].cell(1, 2).text == "12,500"
    assert changed.sections[0].header.paragraphs[0].text == "公开资料"


def test_new_words_of_several_lines_become_paragraphs_in_the_same_style(made):
    after = office.replaced(".docx", made, "完成数据迁移", "完成数据迁移\n组织一次培训", False)
    rows = _styles(after)
    at = rows.index(("List Number", "完成数据迁移"))
    assert rows[at + 1] == ("List Number", "组织一次培训")
    assert _numbering(_doc(after).paragraphs[at + 1])[0] == _numbering(_doc(after).paragraphs[at])[0]


def test_every_occurrence_with_replace_all(made):
    after = office.replaced(".docx", made, "%", "％", True)
    text = "\n".join(p.text for p in _doc(after).paragraphs)
    assert "%" not in text and "42％" in text


@pytest.mark.parametrize("old, says", [
    ("没有这段文字", "was not found"),
    ("完成", "times"),
    ("一、总体情况\n本季度", "spans more than one paragraph"),
    ("| 指标 | 目标 |", "several cells"),
    ("", "empty"),
])
def test_a_replacement_that_cannot_be_done_says_how_to_correct_the_call(made, old, says):
    with pytest.raises(ValueError, match=says):
        office.replaced(".docx", made, old, "新", False)


@pytest.mark.parametrize("data, says", [
    (b"plain text, not a document", "damaged or of another kind"),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 64, "password"),
])
def test_bytes_that_are_not_a_word_document_are_refused_before_the_library_reads_them(data, says):
    with pytest.raises(ValueError, match=says):
        office.replaced(".docx", data, "a", "b", False, "报告.docx")


def test_a_workbook_under_a_docx_name_is_refused():
    package = io.BytesIO()
    with zipfile.ZipFile(package, "w") as z:
        z.writestr("[Content_Types].xml", '<Types xmlns="x"><Override ContentType="application/vnd.openxmlformats-'
                                          'officedocument.spreadsheetml.sheet.main+xml"/></Types>')
        z.writestr("_rels/.rels", '<Relationships xmlns="x"><Relationship Type="http://schemas.openxmlformats.org/'
                                  'officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                                  '</Relationships>')
        z.writestr("xl/workbook.xml", "<workbook/>")
    with pytest.raises(ValueError, match="not a Word document"):
        office.replaced(".docx", package.getvalue(), "a", "b", False, "报告.docx")


def test_a_paragraph_split_keeps_one_section_break():
    data = office.make(".docx", "第一段")
    document = _doc(data)
    last = document.paragraphs[-1]
    # A section break carried in the paragraph's properties, as Word writes one at the end of a section.
    etree.SubElement(last._p.get_or_add_pPr(), qn("w:sectPr"))
    out = io.BytesIO()
    document.save(out)
    after = _doc(office.replaced(".docx", out.getvalue(), "第一段", "第一段\n第二段", False))
    holders = [p for p in after.paragraphs if p._p.pPr is not None and p._p.pPr.find(qn("w:sectPr")) is not None]
    assert [p.text for p in holders] == ["第二段"]


def test_words_inserted_where_the_two_texts_differ_only_by_an_addition_go_into_the_run_before(made):
    after = office.replaced(".docx", made, "全部三项", "全部三项（含追加）", False)
    paragraph = next(p for p in _doc(after).paragraphs if p.text.startswith("本季度"))
    assert ("全部三项（含追加）", True) in [(r.text, r.bold) for r in paragraph.runs]
    assert word._SPLIT not in "".join(p.text for p in _doc(after).paragraphs)
