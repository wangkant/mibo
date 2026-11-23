"""write_file and edit_file on Word documents, through the same gate as any file: a new .docx is made at once from
the model's Markdown and the answer says what was made and that it is finished; replacing one shows the difference
of the two documents' text on the card; an exact replacement changes it in place; the turn's checkpoint shows the
change and takes it back byte for byte; a declined document is not asked again in the turn; the formats from
before 2007 are refused with the name to use instead."""
from __future__ import annotations

import os

import pytest
from docx import Document

from harness.model import call, say
from mibo.shell import checkpoint, office
from mibo.shell import files as file_tools
from mibo.shell.grants import Grants

REPORT = "# 季度总结\n\n## 一、概况\n\n本季度完成了全部目标。\n\n| 指标 | 实际 |\n|---|---|\n| 收入 | 286 |\n"


@pytest.fixture
def folder(app, tmp_path, monkeypatch):
    """A folder granted to change in; the Recycle Bin is a stand-in that deletes in place."""
    place = tmp_path / "work"
    place.mkdir()
    assert Grants(app.home / "runtime" / "desktop", app.home).add(str(place)) == ""

    def recycle(paths: list) -> bool:
        for path in paths:
            os.remove(path)
        return True

    monkeypatch.setattr(file_tools, "recycle", recycle)
    return place


def _paragraphs(path) -> list[str]:
    return [p.text for p in Document(str(path)).paragraphs if p.text]


def _turn_name(done) -> str:
    return next(step["what"] for step in done.trace if step.get("tool") == "changes")


def test_a_new_document_is_made_at_once_and_the_answer_says_it_is_finished(app, turn, folder):
    write = call("write_file", path="季度总结.docx", content=REPORT, folder=str(folder))
    done = turn("把季度总结做成 Word", write, say("已生成。"))  # copy: voice
    assert done.cards == []
    path = folder / "季度总结.docx"
    assert _paragraphs(path)[:3] == ["季度总结", "一、概况", "本季度完成了全部目标。"]
    answer = done.result_of(done.calls()[0]["id"])
    assert "a Word document titled “季度总结”" in answer and "The file is finished and saved" in answer
    assert "no program has to be opened" in answer


def test_an_edit_changes_the_document_in_place_and_the_turn_takes_it_back(app, turn, folder):
    path = folder / "季度总结.docx"
    turn("把季度总结做成 Word", call("write_file", path=path.name, content=REPORT, folder=str(folder)),  # copy: voice
         say("已生成。"))  # copy: voice
    original = path.read_bytes()
    edit = call("edit_file", path=path.name, old_string="全部目标", new_string="大部分目标", folder=str(folder))
    cell = call("edit_file", path=path.name, old_string="286", new_string="290", folder=str(folder))
    done = turn("改一下总结里的两处", edit, cell, say("已修改。"))  # copy: voice
    document = Document(str(path))
    assert "本季度完成了大部分目标。" in [p.text for p in document.paragraphs]
    assert document.tables[0].cell(1, 1).text == "290"
    assert [p.style.name for p in document.paragraphs][:2] == ["Title", "Heading 1"]
    # The fold under the reply shows the change as text, and the turn's undo puts the file back as it was.
    kept = checkpoint.Checkpoints(app.home).turn(_turn_name(done))
    diff = kept.view()["items"][0]["diff"]
    assert "-本季度完成了全部目标。" in diff and "+本季度完成了大部分目标。" in diff and "+| 收入 | 290 |" in diff
    assert kept.undo() == {"done": 1, "left": []}
    assert path.read_bytes() == original


def test_replacing_a_document_shows_the_difference_of_its_text_and_a_no_holds_for_the_same_document(
        app, turn, folder, monkeypatch):
    # No checkpoint could keep the file, so every change to it asks.
    monkeypatch.setattr(checkpoint, "KEEP_MAX", 1)
    path = folder / "季度总结.docx"
    turn("做成 Word", call("write_file", path=path.name, content=REPORT, folder=str(folder)), say("好。"))  # copy: voice
    before = path.read_bytes()
    again = call("write_file", path=path.name, content=REPORT.replace("全部目标", "主要目标"), folder=str(folder))
    done = turn("重写总结", again, again, say("未修改。"), cards="no")  # copy: voice
    # One card: the same document asked for again in the turn is refused with no second card.
    assert [(c["kind"], c["answer"]) for c in done.cards] == [("shell", "no")]
    card = done.cards[0]["card"]
    assert "-本季度完成了全部目标。" in card["diff"] and "+本季度完成了主要目标。" in card["diff"]
    assert path.read_bytes() == before
    assert [step["status"] for step in done.trace if step.get("tool") == "shell"] == ["declined", "declined"]


@pytest.mark.parametrize("name, says", [("旧报告.doc", "旧报告.docx"), ("账目.xls", "账目.xlsx"), ("汇报.ppt", "汇报.pptx")])
def test_the_formats_from_before_2007_are_refused_with_the_name_to_use(app, turn, folder, name, says):
    done = turn("做成文档", call("write_file", path=name, content="# 标题", folder=str(folder)), say("好。"))  # copy: voice
    answer = done.result_of(done.calls()[0]["id"])
    assert "from before 2007" in answer and f"Write {says} instead" in answer
    assert not (folder / name).exists() and done.cards == []


def test_an_edit_that_is_not_found_says_how_to_correct_it_and_a_pdf_is_not_written(app, turn, folder):
    path = folder / "季度总结.docx"
    path.write_bytes(office.make(".docx", REPORT))
    missing = call("edit_file", path=path.name, old_string="没有这句", new_string="新", folder=str(folder))
    pdf = call("write_file", path="总结.pdf", content="# 总结", folder=str(folder))
    done = turn("改一下", missing, pdf, say("未修改。"))  # copy: voice
    first, second = done.calls()
    assert "old_string was not found in the document" in done.result_of(first["id"])
    assert "write_file does not make PDFs" in done.result_of(second["id"])
    assert not (folder / "总结.pdf").exists()


def test_a_damaged_document_is_refused_and_left_as_it_is(app, turn, folder):
    path = folder / "坏文件.docx"
    path.write_bytes(b"not a document at all")
    edit = call("edit_file", path=path.name, old_string="a", new_string="b", folder=str(folder))
    done = turn("改一下", edit, say("无法修改。"))  # copy: voice
    assert "坏文件.docx is not a Word document that can be opened" in done.result_of(done.calls()[0]["id"])
    assert path.read_bytes() == b"not a document at all"
