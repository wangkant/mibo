"""PowerPoint decks made from Markdown (office.pptx.make), changed by exact replacement (replaced), and described
in a few words (summary): one theme at 16:9, real placeholders and tables, and nothing that runs off a slide."""
from __future__ import annotations

import io
import math
import unicodedata
import zipfile

import pytest
from lxml import etree
from pptx import Presentation
from pptx.enum.shapes import PP_PLACEHOLDER
from pptx.enum.text import PP_ALIGN
from pptx.util import Emu

from mibo.shell.office import deck_layout
from mibo.shell.office import pptx as office

A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"

DECK = """# 2026 年度用户研究报告
桌面助手产品线 · 用户体验部

> 开场说明研究范围。

# 目录
1. 研究背景
2. 关键发现

# 研究背景

# 为什么要做这次研究
- 周活跃用户增长**放缓**
  - 9 月环比增长 3.1%
  - 流失集中在第二周
- 工单中*文件处理*问题占比 27%，见 `report.xlsx` 与 [说明](https://example.com/a)
用户反复提到格式调整耗时。

> 这一页控制在一分钟以内。

# 数据概览
| 场景 | 占比 | 备注 |
|---|---:|:---:|
| 撰写周报 | 34% | 稳定 |
| 整理表格 | 22% | 上升 |
"""


def _open(data: bytes):
    return Presentation(io.BytesIO(data))


def _units(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in "WFA" else 1 for ch in text)


def _body(slide):
    return next(s for s in slide.placeholders if s.placeholder_format.idx == 1)


def test_a_deck_is_16_by_9_on_its_own_theme_with_four_layouts() -> None:
    data = office.make(DECK)
    deck = _open(data)
    assert (deck.slide_width, deck.slide_height) == (12192000, 6858000)
    assert [layout.name for layout in deck.slide_layouts] == ["Cover", "Content", "Section", "Table"]
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        theme = etree.fromstring(archive.read("ppt/theme/theme1.xml"))
        names = archive.namelist()
        # Every part is well-formed XML, and none of the template's leftovers come along.
        for name in names:
            if name.endswith((".xml", ".rels")):
                etree.fromstring(archive.read(name))
        app = archive.read("docProps/app.xml").decode()
    assert not any("thumbnail" in n or "printerSettings" in n for n in names)
    assert "Widescreen" in app and "<Slides>5</Slides>" in app
    fonts = theme.find(f".//{A}fontScheme")
    for holder in ("majorFont", "minorFont"):
        assert fonts.find(f"{A}{holder}/{A}ea").get("typeface") == office.EAST_ASIAN_FONT
        assert fonts.find(f"{A}{holder}/{A}latin").get("typeface") == office.BODY_FONT
    assert theme.find(f".//{A}clrScheme/{A}dk2/{A}srgbClr").get("val") == office.PALETTE["dk2"]
    assert deck.core_properties.author == "" and deck.core_properties.title == "2026 年度用户研究报告"


def test_the_same_text_makes_the_same_parts() -> None:
    def parts(data: bytes) -> dict:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return {name: archive.read(name) for name in archive.namelist()}
    first, second = parts(office.make(DECK)), parts(office.make(DECK))
    assert first == second
    assert b"dcterms:created" not in first["docProps/core.xml"]


def test_cover_section_content_and_table_slides_come_from_what_is_written() -> None:
    deck = _open(office.make(DECK))
    slides = list(deck.slides)
    assert [s.slide_layout.name for s in slides] == ["Cover", "Content", "Section", "Content", "Table"]
    cover, _, section, points, _ = slides
    assert cover.shapes.title.text == "2026 年度用户研究报告"
    assert _body(cover).text_frame.text == "桌面助手产品线 · 用户体验部"
    assert cover.notes_slide.notes_text_frame.text == "开场说明研究范围。"
    assert _body(section).text_frame.text == "01" and section.shapes.title.text == "研究背景"
    assert points.notes_slide.notes_text_frame.text == "这一页控制在一分钟以内。"
    # Content and table slides carry their number; the cover and the divider do not.
    numbers = [[s.text_frame.text for s in slide.placeholders
                if s.placeholder_format.type == PP_PLACEHOLDER.SLIDE_NUMBER] for slide in slides]
    assert numbers == [[], ["2"], [], ["4"], ["5"]]


def test_points_sub_points_numbers_and_plain_lines_keep_their_form() -> None:
    deck = _open(office.make(DECK))
    agenda, points = deck.slides[1], deck.slides[3]
    paragraphs = _body(points).text_frame.paragraphs
    assert [p.level for p in paragraphs] == [0, 1, 1, 0, 0]
    # A plain line carries no bullet and no indent; points inherit the layout's bullet.
    last = paragraphs[-1]._p.pPr
    assert last.find(f"{A}buNone") is not None and last.get("marL") == "0"
    assert paragraphs[0]._p.pPr.find(f"{A}buNone") is None
    for paragraph in _body(agenda).text_frame.paragraphs:
        assert paragraph._p.pPr.find(f"{A}buAutoNum").get("type") == "arabicPeriod"


def test_inline_bold_italic_code_and_links_become_runs() -> None:
    paragraphs = _body(_open(office.make(DECK)).slides[3]).text_frame.paragraphs
    first = {r.text: r for r in paragraphs[0].runs}
    assert first["放缓"].font.bold and not first["周活跃用户增长"].font.bold
    fourth = {r.text: r for r in paragraphs[3].runs}
    assert fourth["文件处理"].font.italic
    assert fourth["report.xlsx"].font.name == office.CODE_FONT
    assert fourth["说明"].hyperlink.address == "https://example.com/a"
    assert "**" not in _body(_open(office.make(DECK)).slides[3]).text_frame.text


def test_a_table_is_a_real_table_with_a_styled_header_and_aligned_columns() -> None:
    slide = _open(office.make(DECK)).slides[4]
    frame = next(s for s in slide.shapes if s.has_table)
    grid = frame.table
    assert [[c.text for c in row.cells] for row in grid.rows] == [
        ["场景", "占比", "备注"], ["撰写周报", "34%", "稳定"], ["整理表格", "22%", "上升"]]
    header = grid.cell(0, 0)
    assert header.text_frame.paragraphs[0].runs[0].font.bold
    assert header._tc.tcPr.find(f"{A}solidFill/{A}schemeClr").get("val") == "tx2"
    assert grid.cell(1, 1).text_frame.paragraphs[0].alignment == PP_ALIGN.RIGHT
    assert grid.cell(1, 2).text_frame.paragraphs[0].alignment == PP_ALIGN.CENTER
    assert sum(c.width for c in grid.columns) == frame.width


def _within_slide(deck) -> None:
    for slide in deck.slides:
        for shape in slide.shapes:
            assert shape.left >= 0 and shape.top >= 0, shape.name
            assert shape.left + shape.width <= deck.slide_width, shape.name
            assert shape.top + shape.height <= deck.slide_height, shape.name


def _text_fits(shape, default: float) -> None:
    """A floor PowerPoint cannot beat: a line holds at most width / size East Asian characters, and a line is at
    least 1.2 times its size tall."""
    width = Emu(shape.width).pt - 14.4
    used = 0.0
    for paragraph in shape.text_frame.paragraphs:
        size = next((r.font.size.pt for r in paragraph.runs if r.font.size), default - 2 * (paragraph.level > 0))
        used += math.ceil(_units(paragraph.text) * size / 2 / width) * size * 1.2
    assert used <= Emu(shape.height).pt, (shape.name, used, Emu(shape.height).pt)


def test_long_points_continue_on_slides_with_the_same_title_and_never_overflow() -> None:
    lines = ["# 一页放不下的要点"]
    for n in range(1, 31):
        lines.append(f"- 第 {n} 条：这是一段较长的说明文字，用来模拟真实汇报中冗长的要点描述，混排 English words 12,345。")
        if n % 4 == 0:
            lines += ["  - 子要点甲：补充说明", "  - 子要点乙：补充说明"]
    deck = _open(office.make("\n".join(lines)))
    slides = list(deck.slides)
    assert len(slides) > 3
    assert {s.shapes.title.text for s in slides} == {"一页放不下的要点"}
    seen = []
    for slide in slides:
        body = _body(slide)
        paragraphs = body.text_frame.paragraphs
        # A slide never starts with a sub-point, and nothing is set below 14 pt.
        assert paragraphs[0].level == 0
        assert all(r.font.size.pt >= 14 for p in paragraphs for r in p.runs)
        _text_fits(body, deck_layout.BODY_SIZES[0])
        seen += [p.text for p in paragraphs]
    assert seen[0].startswith("第 1 条") and seen[-1].startswith("第 30 条") and len(seen) == 30 + 14
    _within_slide(deck)


def test_a_slide_a_little_too_full_is_set_smaller_instead() -> None:
    text = "# 要点\n" + "\n".join(f"- 第 {n} 条要点：这是一段中等长度的说明文字，共两行左右的长度用来测试字号逐级减小的规则是否生效"
                                  for n in range(9))
    deck = _open(office.make(text))
    assert len(deck.slides) == 1
    sizes = {r.font.size.pt for p in _body(deck.slides[0]).text_frame.paragraphs for r in p.runs}
    assert len(sizes) == 1 and 14 <= sizes.pop() < 20
    _text_fits(_body(deck.slides[0]), 20)


def test_one_huge_paragraph_is_cut_after_sentences_across_slides() -> None:
    text = "# 正文\n" + "团队在交付文档时花费了大量时间在格式调整上，而不是内容本身。" * 60
    deck = _open(office.make(text))
    assert len(deck.slides) >= 2
    pieces = [_body(s).text_frame.text for s in deck.slides]
    assert "".join(pieces) == "团队在交付文档时花费了大量时间在格式调整上，而不是内容本身。" * 60
    assert all(piece.endswith("。") for piece in pieces)
    for slide in deck.slides:
        _text_fits(_body(slide), 20)


def test_a_long_table_continues_with_its_header_repeated() -> None:
    rows = "\n".join(f"| {n} | 城市{n} | 希望生成的文档能直接交付，不需要再次排版 |" for n in range(1, 41))
    deck = _open(office.make(f"# 受访者\n| 序号 | 城市 | 诉求 |\n|---|---|---|\n{rows}"))
    grids = [next(s for s in slide.shapes if s.has_table).table for slide in deck.slides]
    assert len(grids) > 1
    assert all(g.cell(0, 0).text == "序号" for g in grids)
    assert [g.cell(r, 0).text for g in grids for r in range(1, len(g.rows))] == [str(n) for n in range(1, 41)]
    assert all(r.font.size.pt >= 12 for g in grids for row in g.rows for c in row.cells
               for p in c.text_frame.paragraphs for r in p.runs)
    _within_slide(deck)


def test_text_and_a_table_share_a_slide_without_overlapping() -> None:
    text = ("# 季度指标\n下表给出各季度的核心指标。\n| 季度 | 收入 |\n|---|---:|\n| Q1 | 1,280 |\n| Q2 | 1,310 |\n"
            "数据来源：财务部月度报表。")
    deck = _open(office.make(text))
    assert len(deck.slides) == 1
    slide = deck.slides[0]
    above = _body(slide)
    table = next(s for s in slide.shapes if s.has_table)
    below = next(s for s in slide.shapes if s.shape_type is not None and s.name.startswith("TextBox"))
    assert above.top + above.height <= table.top and table.top + table.height <= below.top
    assert below.text_frame.text == "数据来源：财务部月度报表。"
    _within_slide(deck)


def test_a_long_title_steps_down_and_stays_in_its_box() -> None:
    title = "这是一个非常非常长的标题，用来检验标题在一行放不下时是否会自动缩小字号而保持在标题区域之内"
    slide = _open(office.make(f"# 封面\n\n# {title}\n- 一点")).slides[1]
    run = slide.shapes.title.text_frame.paragraphs[0].runs[0]
    assert run.font.size.pt < office.TITLE_SIZES[0]


def test_text_before_any_heading_and_hostile_characters_still_make_a_deck() -> None:
    deck = _open(office.make("季度复盘\n\n# 要点\n- 含控制字符\x07与制表\t的一行"))
    assert deck.slides[0].shapes.title.text == "季度复盘"
    assert "含控制字符" in _body(deck.slides[1]).text_frame.text
    with pytest.raises(ValueError, match="empty"):
        office.make("  \n\n")


def test_summary_counts_the_slides() -> None:
    assert office.summary(office.make(DECK)) == "a PowerPoint deck of 5 slides"
    assert office.summary(office.make("# 只有一页")) == "a PowerPoint deck of 1 slide"
    with pytest.raises(ValueError, match="not a PowerPoint deck"):
        office.summary(b"not a zip at all")


def test_replacement_inside_one_run_keeps_every_other_run_and_the_layout() -> None:
    data = office.replaced(office.make(DECK), "用户增长", "用户回升", False)
    paragraph = _body(_open(data).slides[3]).text_frame.paragraphs[0]
    assert [(r.text, bool(r.font.bold)) for r in paragraph.runs] == [("周活跃用户回升", False), ("放缓", True)]
    assert _open(data).slides[3].slide_layout.name == "Content"


def test_replacement_across_runs_changes_only_the_runs_it_touches() -> None:
    data = office.replaced(office.make(DECK), "用户增长放缓", "用户数量持平", False)
    runs = _body(_open(data).slides[3]).text_frame.paragraphs[0].runs
    assert [(r.text, bool(r.font.bold)) for r in runs] == [("周活跃用户数量持平", False)]
    # Text after the match in a touched run stays in that run with its look.
    data = office.replaced(office.make(DECK), "增长放", "趋于平", False)
    runs = _body(_open(data).slides[3]).text_frame.paragraphs[0].runs
    assert [(r.text, bool(r.font.bold)) for r in runs] == [("周活跃用户趋于平", False), ("缓", True)]


def test_replacement_reaches_table_cells_and_notes() -> None:
    data = office.replaced(office.make(DECK), "整理表格", "整理数据表", False)
    data = office.replaced(data, "一分钟以内", "九十秒以内", False)
    deck = _open(data)
    grid = next(s for s in deck.slides[4].shapes if s.has_table).table
    assert grid.cell(2, 0).text == "整理数据表"
    assert grid.cell(2, 0).text_frame.paragraphs[0].runs[0].font.size.pt == deck_layout.TABLE_SIZES[0]
    assert deck.slides[3].notes_slide.notes_text_frame.text == "这一页控制在九十秒以内。"


def test_replacement_says_what_went_wrong_in_words_the_model_can_act_on() -> None:
    data = office.make(DECK)
    with pytest.raises(ValueError, match="not found"):
        office.replaced(data, "不存在的文字", "x", False)
    with pytest.raises(ValueError, match="2 times"):
        office.replaced(data, "研究背景", "x", False)
    with pytest.raises(ValueError, match="more than one paragraph"):
        office.replaced(data, "研究背景\n关键发现", "x", False)
    with pytest.raises(ValueError, match="line break"):
        office.replaced(data, "关键发现", "甲\n乙", False)
    with pytest.raises(ValueError, match="empty"):
        office.replaced(data, "", "x", False)
    changed = _open(office.replaced(data, "研究背景", "项目背景", True))
    assert changed.slides[1].placeholders[1].text_frame.paragraphs[0].text == "项目背景"
    assert changed.slides[2].shapes.title.text == "项目背景"
