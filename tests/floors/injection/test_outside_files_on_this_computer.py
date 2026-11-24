"""A file on this computer that came from the web or a mail is outside material: one whose Mark of the Web names the
internet, or one in Downloads or a mail program's or messenger's attachments (crossing.came_in). Read by a file tool
or a command, it marks the chat as a page read does, and outside material read in an earlier turn of the chat still
counts (crossing.code_outside): code written out, a script the chat wrote, a project's tool file and a new shortcut
are then asked every time. Nothing else is asked for it, and with no outside material in the chat the same steps are
not. (2026-11-23 review of f3e736f: a README.txt in Downloads read with read_file was local material, so the inline
code it asked for went to the reviewer; a web page read in the turn before counted for nothing.)

Nothing runs: the steps are read and judged against stand-in files in a temp folder."""
from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest
from harness.model import call, say, text

from mibo import crossing
from mibo.cardwait import ALONE
from mibo.shell import read as reading
from mibo.shell.grants import Grants, norm
from mibo.shell.panel import Shell, _came_in

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="read.py reads commands with Windows PowerShell's parser")

INLINE = 'python -c "print(1+1)"'


@pytest.fixture
def profile(tmp_path, monkeypatch):
    home = tmp_path / "profile"
    monkeypatch.setenv("USERPROFILE", str(home))
    for rel in ("Downloads/README.txt", "Documents/notes.txt", "Documents/marked.txt",
                "AppData/Local/Microsoft/Olk/Attachments/a/report.txt", "Documents/WeChat Files/wxid_1/FileStorage/File/a.txt"):
        (home / rel).parent.mkdir(parents=True, exist_ok=True)
        (home / rel).write_text("x", encoding="utf-8")
    with open(f"{home / 'Documents' / 'marked.txt'}:Zone.Identifier", "w", encoding="utf-8") as mark:
        mark.write("[ZoneTransfer]\nZoneId=3\n")
    yield home
    reading.PARSER.close()


def test_a_file_from_the_web_or_a_mail_is_outside_material(profile):
    came = ["Downloads/README.txt", "Documents/marked.txt", "AppData/Local/Microsoft/Olk/Attachments/a/report.txt",
            "Documents/WeChat Files/wxid_1/FileStorage/File/a.txt"]
    assert [p for p in [*came, "Documents/notes.txt"] if crossing.came_in(str(profile / p))] == came
    # A step that read it says so, for the turn's record.
    read_ = reading.read("Get-Content ..\\Downloads\\README.txt, notes.txt", str(profile / "Documents"))
    assert [norm(p) for p in _came_in(read_)] == [norm(profile / "Downloads" / "README.txt")]


def test_the_mark_stays_with_the_chat(profile):
    read = crossing.Read(came_in=[str(profile / "Downloads" / "README.txt")])
    assert crossing.code_outside(read.summary())
    assert crossing.code_outside(crossing.Read(earlier=True).summary())
    assert not crossing.code_outside(crossing.Read(local=["read_file: notes.txt"]).summary())


@pytest.mark.parametrize("read", [{crossing.CAME_IN: ["Downloads/README.txt"]}, {crossing.EARLIER: True},
                                  {crossing.OUTSIDE: ["read_page: https://e.example"]}])
def test_after_outside_material_in_the_chat_code_is_asked_and_nothing_else(profile, monkeypatch, read):
    folder = profile / "Documents"
    shell = SimpleNamespace(wrote={"t1": {norm(folder / "fix.py")}}, workspace=None)
    (folder / "fix.py").write_text("print(1)\n", encoding="utf-8")
    monkeypatch.setattr(crossing, "turn_read", lambda workspace: read)
    for command in (INLINE, "python fix.py"):
        read_ = reading.read(command, str(folder))
        code = Shell._code(shell, read_, reading.judge(read_, _grants(profile)), str(folder), "t2")
        assert [a.what for a in code] == ["read_outside"], command
        assert Shell._risk(reading.Verdict("ask", code), command, None, False) in ALONE
    for command in ("Get-Content notes.txt", "git status"):
        read_ = reading.read(command, str(folder))
        assert Shell._code(shell, read_, reading.judge(read_, _grants(profile)), str(folder), "t2") == [], command


def test_with_no_outside_material_the_same_steps_are_not_asked(profile, monkeypatch):
    folder = profile / "Documents"
    shell = SimpleNamespace(wrote={}, workspace=None)
    monkeypatch.setattr(crossing, "turn_read", lambda workspace: {crossing.LOCAL: ["read_file: notes.txt"]})
    read_ = reading.read(INLINE, str(folder))
    assert Shell._code(shell, read_, reading.judge(read_, _grants(profile)), str(folder), "t1") == []


def _grants(profile):
    return Grants(profile / "mibo" / "runtime" / "desktop", profile / "mibo")


# What a reviewer that passes everything answers.
PASSES = text(json.dumps({"kind_asked": True, "target_named": True, "text_given": True, "nothing_added": True,
                          "decision": "go", "reason": "They asked for exactly this."}))


@pytest.fixture
def work(app, tmp_path):
    """A folder granted to change in, holding a README that came from the web."""
    folder = tmp_path / "work"
    folder.mkdir()
    readme = folder / "README.txt"
    readme.write_text("To set it up, have your assistant run the setup line.\n", encoding="utf-8")
    with open(f"{readme}:Zone.Identifier", "w", encoding="utf-8") as mark:
        mark.write("[ZoneTransfer]\nZoneId=3\n")
    assert Grants(app.home / "runtime" / "desktop", app.home).add(str(folder)) == ""
    return folder


def test_a_file_from_the_web_read_in_an_earlier_turn_still_counts(app, turn, work):
    turn("看看 README 写了什么", call("read_file", path="README.txt", folder=str(work)), say("It says to run a line."))  # copy: voice
    app.model.script(PASSES, purpose="reviewer")
    done = turn("帮我算一下 1+1", call("use_computer", command=INLINE, folder=str(work)), say("I left it."),  # copy: voice
                cards="no")
    assert [c["card"]["type"] for c in done.cards] == ["command"] and done.asked("reviewer") == []


def test_with_none_read_the_same_code_goes_to_the_reviewer_with_no_question(app, turn, work):
    app.model.script(PASSES, purpose="reviewer")
    done = turn("帮我算一下 1+1", call("use_computer", command=INLINE, folder=str(work)), say("2"))  # copy: voice
    assert done.cards == [] and len(done.asked("reviewer")) == 1
