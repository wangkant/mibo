"""The tier of Windows' own limits a command runs under (shell/confine.py) is the one its reading gives (acts.tier):
low integrity only for a command read as doing nothing but read, a program's tier for one that runs or opens a
program, and the change tier for everything else, what the reader does not know among it."""
from __future__ import annotations

import sys

import pytest

from mibo.shell import acts
from mibo.shell import read as reading

COMMANDS = (
    ("Get-ChildItem -Recurse | Sort-Object Length", "read"),
    ("Get-Content notes.txt | Select-String total", "read"),
    ("Get-PSDrive -PSProvider FileSystem", "read"),
    ("Copy-Item notes.txt notes-copy.txt", "change"),
    ("Remove-Item notes.txt", "change"),
    ("Get-Content notes.txt | Set-Content copy.txt", "change"),
    ("Start-Process notes.txt", "program"),
    ("Invoke-Item notes.txt", "program"),
    ("& ./tool.exe --help", "program"),
    ("Some-UnknownThing -Do it", "change"),
)


@pytest.mark.skipif(sys.platform != "win32", reason="read.py reads commands with Windows PowerShell's own parser")
def test_each_command_runs_in_the_tier_its_reading_gives(tmp_path):
    (tmp_path / "notes.txt").write_text("total 3\n", encoding="utf-8")
    got = [(command, acts.tier(reading.read(command, str(tmp_path)).acts)) for command, _ in COMMANDS]
    assert got == list(COMMANDS)
