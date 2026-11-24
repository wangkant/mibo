"""A write that makes code run later by itself is a costly step, asked every time: Git's attributes and submodules,
pip's settings, a virtual environment's activation scripts, anything in .vscode, .envrc. A project's own tool files
(package.json, a Makefile, pyproject.toml, setup.py, conftest.py, a pre-commit config) and a new shortcut are not
costly and never written by rule: the reviewer judges each on the person's words, and after the turn read outside
material each is asked. (2026-11-23 review of 0368fcc: .gitattributes, .git/info/attributes, .gitmodules, pip.ini
and a .pre-commit-config.yaml were written with no question; package.json and a Makefile went by auto-edit.)

The files are in a temp folder granted to change; nothing runs."""
from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from mibo import crossing
from mibo.cardwait import ALONE
from mibo.shell import read as reading
from mibo.shell.acts import tier
from mibo.shell.grants import Grants
from mibo.shell.panel import Shell, _reviewed

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="read.py reads commands with Windows PowerShell's parser")

RUNS_LATER = [".gitattributes", ".git/info/attributes", ".gitmodules", "pip.ini", "pip.conf", "venv/Scripts/activate",
              "venv/Scripts/Activate.ps1", "venv/bin/activate", ".vscode/settings.json", ".vscode/launch.json"]
PROJECT = ["package.json", "Makefile", "GNUmakefile", "pyproject.toml", "setup.py", "setup.cfg", "tox.ini",
           "noxfile.py", "conftest.py", ".pre-commit-config.yaml"]


@pytest.fixture
def project(tmp_path):
    home = tmp_path / "home"
    place = tmp_path / "project"
    for rel in ("venv/Scripts", "venv/bin", ".vscode", ".git/info"):
        (place / rel).mkdir(parents=True)
    grants = Grants(home / "runtime" / "desktop", home)
    assert grants.add(str(place)) == ""
    return SimpleNamespace(place=place, grants=grants)


def judged(command: str, project):
    read_ = reading.read(command, str(project.place))
    return read_, reading.judge(read_, project.grants)


@pytest.mark.parametrize("rel", RUNS_LATER)
@pytest.mark.parametrize("existing", [False, True])
def test_a_write_that_runs_later_by_itself_is_costly(rel, existing, project):
    if existing:
        (project.place / rel).write_text("x", encoding="utf-8")
    command = f"Set-Content -Path '{project.place / rel}' -Value 'x'"
    _, verdict = judged(command, project)
    assert verdict.action == "ask" and Shell._risk(verdict, command, None, False) in ALONE


@pytest.mark.parametrize("name", PROJECT)
@pytest.mark.parametrize("existing", [False, True])
def test_a_projects_tool_file_goes_to_the_reviewer_and_never_by_rule(name, existing, project):
    if existing:
        (project.place / name).write_text("x", encoding="utf-8")
    command = f"Set-Content -Path '{project.place / name}' -Value 'x'"
    read_, verdict = judged(command, project)
    me = SimpleNamespace(grants=project.grants)
    assert verdict.action == "ask" and Shell._risk(verdict, command, None, False) == "act"
    assert any(a.what == "project_file" for a in verdict.reasons) and all(_reviewed(a) for a in verdict.reasons
                                                                          if a.kind != "overwrite")
    assert Shell._passed(me, Shell._scope(me, read_, verdict, str(project.place)), "auto") == ""
    assert tier(read_.acts) == "change"


def test_after_outside_material_a_projects_tool_file_or_a_new_shortcut_is_asked(project, monkeypatch):
    monkeypatch.setattr(crossing, "turn_read", lambda workspace: {crossing.OUTSIDE: ["read_page: https://e.example"]})
    shell = SimpleNamespace(wrote={}, workspace=None)
    for name in ("package.json", "Run.lnk"):
        command = f"Set-Content -Path '{project.place / name}' -Value 'x'"
        read_, verdict = judged(command, project)
        code = Shell._code(shell, read_, verdict, str(project.place), "t")
        assert [a.what for a in code] == ["read_outside"], name
        asked = reading.Verdict("ask", verdict.reasons + code)
        assert Shell._risk(asked, command, None, False) in ALONE
