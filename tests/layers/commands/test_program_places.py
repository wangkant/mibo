"""Finding an installed program is a read anyone may make (shell/grants.py Places.findable, pstables.REGISTRY_READ):
the Start menu's shortcut folders for the person and for everyone, Program Files, whether a program's folder under
AppData is there, and the registry's App Paths. (2026-11-23: listing the Start menu for *eep* was refused as
protected, a listing of Office's folder was put to the reviewer, which asked the person, and testing whether Word was
installed was refused as touching the system and protected places.) A secret's place stays refused.

Windows' own drive is a stand-in: the temp folder's drive, with Program Files and ProgramData in it outside the
stand-in profile, so nothing there is an open place by the profile or the drive."""
from __future__ import annotations

import os
import sys

import pytest

from mibo.shell import files
from mibo.shell import read as reading
from mibo.shell.grants import DIRS_ENV, Grants

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="read.py reads commands with Windows PowerShell's parser")


@pytest.fixture
def computer(tmp_path, monkeypatch):
    profile, programs, data = tmp_path / "profile", tmp_path / "Program Files", tmp_path / "ProgramData"
    roaming, local = profile / "AppData" / "Roaming", profile / "AppData" / "Local"
    menu = os.path.join("Microsoft", "Windows", "Start Menu", "Programs")
    for path in (roaming / menu / "DeepL.lnk", data / menu / "Word.lnk",
                 programs / "Microsoft Office" / "root" / "Office16" / "WINWORD.EXE",
                 local / "Kingsoft" / "WPS Office" / "ksolaunch.exe",
                 local / "Google" / "Chrome" / "User Data" / "Default" / "Login Data",
                 roaming / "Bitwarden" / "data.json"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")
    for name, value in (("USERPROFILE", profile), ("HOME", profile), ("APPDATA", roaming), ("LOCALAPPDATA", local),
                        ("ProgramFiles", programs), ("ProgramW6432", programs), ("ProgramFiles(x86)", programs),
                        ("ProgramData", data), ("SystemDrive", tmp_path.drive)):
        monkeypatch.setenv(name, str(value))
    monkeypatch.setenv(DIRS_ENV, os.pathsep)
    grants = Grants(profile / "mibo" / "runtime" / "desktop", profile / "mibo")
    yield profile, programs, data, grants
    reading.PARSER.close()


def run(command: str, grants: Grants, cwd: str) -> str:
    return reading.judge(reading.read(command, cwd), grants).action


def test_listing_the_start_menus_for_a_program_runs_with_no_question(computer):
    profile, _, data, grants = computer
    menu = "Microsoft\\Windows\\Start Menu\\Programs"
    command = (f'Get-ChildItem "{profile}\\AppData\\Roaming\\{menu}","{data}\\{menu}" -Recurse -Include *eep*')
    assert run(command, grants, str(profile)) == "run"


def test_listing_a_programs_folder_runs_with_no_reviewer(computer):
    profile, programs, _, grants = computer
    job = {"op": "list", "path": str(programs / "Microsoft Office"), "folder": str(programs / "Microsoft Office"),
           "recursive": False, "pattern": "", "sort": "name"}
    verdict = reading.judge(reading.Reading(files.call(job), str(profile), files.acts(job, str(profile)), []), grants)
    assert verdict.action == "run", [a.why for a in verdict.reasons]


def test_testing_whether_a_program_is_installed_runs(computer):
    profile, programs, _, grants = computer
    command = (f'Test-Path "{programs}\\Microsoft Office\\root\\Office16\\WINWORD.EXE"; '
               "Get-ItemProperty 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\WINWORD.EXE'; "
               "Get-ItemProperty 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\App Paths\\wps.exe'; "
               f'Test-Path "{profile}\\AppData\\Local\\Kingsoft\\WPS Office"')
    assert run(command, grants, str(profile)) == "run"


def test_a_secrets_place_is_still_refused_and_other_programs_data_is_not_read(computer):
    profile, _, _, grants = computer
    local, roaming = profile / "AppData" / "Local", profile / "AppData" / "Roaming"
    for command in (f'Get-Content "{local}\\Google\\Chrome\\User Data\\Default\\Login Data"',
                    f'Test-Path "{local}\\Google\\Chrome\\User Data\\Default\\Login Data"',
                    f'Get-ChildItem "{roaming}\\Bitwarden"', f'Get-Content "{roaming}\\Bitwarden\\data.json"',
                    f'Get-ChildItem "{local}\\Kingsoft" -Recurse',
                    "Get-ItemProperty 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings'",
                    f'Set-Content "{roaming}\\Microsoft\\Windows\\Start Menu\\Programs\\x.lnk" x'):
        assert run(command, grants, str(profile)) == "refuse", command
