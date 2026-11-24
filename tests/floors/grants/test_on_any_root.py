"""The open places hold no way to a secret or to what runs by itself (shell/grants.py Places): a profile's keys, sign-ins
and other programs' data are refused wherever the profile is, a backup of it on another drive too; a write where it
would run or be loaded without the person starting it is asked every time as a costly system step; and in the
program places only names, sizes and dates are free. (2026-11-23 review of 8b57f6f: with the other drives open, a
backup's .kube, .docker, .claude, GitHub CLI and Chrome files read with no question; node_modules, a Git hook, a
drive's autorun.inf and a folder on PATH were written by rule; a look at a password manager's vault and a read of a
file in Program Files ran.)

The profile, the backup and Program Files are stand-ins in a temp folder, whose drive stands in for Windows' own;
nothing runs."""
from __future__ import annotations

import os
import sys

import pytest

from mibo.shell import files
from mibo.shell import read as reading
from mibo.shell.grants import DIRS_ENV, Grants
from mibo.shell.panel import Shell

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="read.py reads commands with Windows PowerShell's parser")

BACKUP = (".kube/config", ".docker/config.json", ".claude/.credentials.json", ".ssh/config",
          "AppData/Roaming/GitHub CLI/hosts.yml", "AppData/Local/Google/Chrome/User Data/Local State",
          "AppData/Local/Google/Chrome/User Data/Default/Web Data", "AppData/Roaming/Code/User/globalStorage/state.vscdb")


@pytest.fixture
def computer(tmp_path, monkeypatch):
    profile, backup, programs = tmp_path / "profile", tmp_path / "D" / "Backup" / "Users" / "me", tmp_path / "Program Files"
    for rel in BACKUP:
        for root in (profile, backup):
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text("x", encoding="utf-8")
    for path in (profile / "Documents" / "notes.txt", profile / "Documents" / "run.ps1",
                 profile / "AppData" / "Roaming" / "Bitwarden" / "data.json", programs / "Tool" / "tool.exe",
                 programs / "Tool" / "settings.json", tmp_path / "bin" / "x.txt"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")
    for name, value in (("USERPROFILE", profile), ("HOME", profile), ("APPDATA", profile / "AppData" / "Roaming"),
                        ("LOCALAPPDATA", profile / "AppData" / "Local"), ("ProgramFiles", programs),
                        ("ProgramW6432", programs), ("ProgramFiles(x86)", programs), ("SystemDrive", tmp_path.drive)):
        monkeypatch.setenv(name, str(value))
    monkeypatch.setenv("PATH", str(tmp_path / "bin") + os.pathsep + os.environ.get("PATH", ""))
    monkeypatch.setenv(DIRS_ENV, os.pathsep)
    grants = Grants(profile / "mibo" / "runtime" / "desktop", profile / "mibo")
    yield tmp_path, profile, backup, programs, grants
    reading.PARSER.close()


def judged(grants: Grants, command: str, cwd: str) -> tuple[str, str]:
    """The action, and the risk an ask is asked as ("" for none)."""
    verdict = reading.judge(reading.read(command, cwd), grants)
    return verdict.action, Shell._risk(verdict, command, None, False) if verdict.action == "ask" else ""


def tool(grants: Grants, op: str, path: str, cwd: str) -> str:
    job = {"op": op, "path": path, "folder": path, "recursive": True, "text": "x", "pattern": "", "sort": "name"}
    return reading.judge(reading.Reading(files.call(job), cwd, files.acts(job, cwd), []), grants).action


def test_a_profiles_secrets_are_refused_wherever_the_profile_is(computer):
    _, profile, backup, _, grants = computer
    cwd = str(profile / "Documents")
    for root in (profile, backup):
        for rel in BACKUP:
            path = str(root / rel)
            assert judged(grants, f'Get-Content "{path}"', cwd)[0] == "refuse", path
            assert tool(grants, "read", path, cwd) == "refuse", path


def test_a_git_repositorys_settings_holding_a_sign_in_are_refused_and_plain_ones_read(computer):
    _, profile, _, _, grants = computer
    cwd = str(profile / "Documents")
    signed, plain = profile / "Documents" / "a" / ".git" / "config", profile / "Documents" / "b" / ".git" / "config"
    for path, text in ((signed, '[remote "origin"]\n\turl = https://me:ghp_abc123@github.com/me/a.git\n'),
                       (plain, '[remote "origin"]\n\turl = https://github.com/me/b.git\n')):
        path.parent.mkdir(parents=True)
        path.write_text(text, encoding="utf-8")
    assert judged(grants, f'Get-Content "{signed}"', cwd)[0] == "refuse"
    assert judged(grants, f'Get-Content "{plain}"', cwd)[0] == "run"


def test_a_write_where_it_would_run_by_itself_is_asked_every_time_as_a_costly_step(computer):
    tmp, profile, _, _, grants = computer
    cwd = str(profile / "Documents")
    for path in (profile / "node_modules" / "lodash" / "index.js", profile / "Documents" / "a" / ".git" / "hooks" /
                 "pre-commit", profile / "Documents" / "a" / ".git" / "config",
                 profile / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" /
                 "x.cmd", profile / "Documents" / "WindowsPowerShell" / "profile.ps1",
                 profile / "Documents" / "dotfiles" / ".bashrc",
                 tmp / "bin" / "git.cmd", f"{tmp.drive}\\autorun.inf",
                 profile / "venv" / "Lib" / "site-packages" / "x.pth", profile / "Documents" / "run.ps1"):
        assert judged(grants, f'Set-Content -Path "{path}" -Value x', cwd) == ("ask", "system"), path


def test_in_the_program_places_only_names_sizes_and_dates_are_free(computer):
    _, profile, _, programs, grants = computer
    cwd = str(profile / "Documents")
    assert judged(grants, f'Get-ChildItem "{programs}" -Recurse', cwd)[0] == "run"
    assert judged(grants, f'Get-Content "{programs}\\Tool\\settings.json"', cwd)[0] != "run"
    vault = str(profile / "AppData" / "Roaming" / "Bitwarden" / "data.json")
    assert judged(grants, f'Test-Path "{vault}"', cwd)[0] == "refuse"
    assert judged(grants, f'Get-Item "{vault}"', cwd)[0] == "refuse"
    assert tool(grants, "list", str(profile / "AppData" / "Roaming"), cwd) == "refuse"
    assert judged(grants, f'Get-ChildItem "{profile}\\AppData\\Roaming" -Recurse', cwd)[0] == "refuse"
