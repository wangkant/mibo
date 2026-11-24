"""Shutting down, a scheduled task, a Run key, a junction and a link are asked every time on their own: the step is
costly (cardwait.ALONE), so no reviewer passes it, no yes earlier in the turn reaches it and no standing request
covers it; and its question names what it points at (the task's program, the Run key's command, the link's
target), so a yes after outside material is a yes to that. (2026-11-23 review of 0368fcc: the question for a Run
key or a junction said only "runs reg" or "makes a link".)

The commands are read and judged; nothing runs."""
from __future__ import annotations

import sys

import pytest

from mibo import crossing
from mibo.cardwait import ALONE, reaches
from mibo.shell import read as reading
from mibo.shell import words
from mibo.shell.grants import Grants
from mibo.shell.panel import Shell

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="read.py reads commands with Windows PowerShell's parser")

TARGET = "C:\\Users\\Public\\Documents\\tool.exe"
STEPS = {
    "shutdown": ("shutdown /s /t 0", ""),
    "scheduled task": (f"schtasks /create /tn x /tr {TARGET} /sc onlogon", TARGET),
    "scheduled task, PowerShell": (f"Register-ScheduledTask -TaskName x -Action (New-ScheduledTaskAction -Execute "
                                   f"{TARGET})", TARGET),
    "Run key": (f"reg add HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run /v x /d {TARGET}", TARGET),
    "Run key, PowerShell": (f"New-ItemProperty -Path HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run -Name x "
                            f"-Value '{TARGET}'", TARGET),
    "junction": ("New-Item -ItemType Junction -Path j -Target C:\\Users\\Public\\Documents", "C:\\Users\\Public\\Documents"),
    "link": (f"New-Item -ItemType SymbolicLink -Path s.exe -Target {TARGET}", TARGET),
    "hard link": (f"fsutil hardlink create h.exe {TARGET}", TARGET),
}


@pytest.mark.parametrize("name", list(STEPS))
def test_a_system_step_is_asked_alone_and_its_question_names_its_target(name, tmp_path):
    command, target = STEPS[name]
    read_ = reading.read(command, str(tmp_path))
    verdict = reading.judge(read_, Grants(tmp_path / "home" / "runtime" / "desktop", tmp_path / "home"))
    assert verdict.action == "ask"
    risk = Shell._risk(verdict, command, None, False)
    assert risk in ALONE
    # No reviewer: only a mild step goes to one (panel.judged); no earlier yes and no standing request reaches it.
    assert risk not in ("act", "recycle")
    assert not any(reaches(earlier, risk) for earlier in (risk, "act", "recycle", "cross:command"))
    assert not crossing.within({"area": "commands", "kinds": [], "places": [str(tmp_path)]},
                               {"area": "commands", "kind": risk, "where": str(tmp_path)})
    if target:
        for lang in ("zh", "en"):
            assert any(target in line for line in words.card_lines(read_, verdict, lang)), lang
