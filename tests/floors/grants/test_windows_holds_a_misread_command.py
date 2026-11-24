"""Windows itself holds a command to what its reading allowed (shell/confine.py), so a reading that was wrong does
not reach past it. The tests tell run() the wrong tier on purpose: a command passed as only reading that deletes,
overwrites, renames, makes a file or writes the registry is refused by Windows and the files are as they were; no
tier reads, lists or changes the app's home (its skills' folder stays readable); a child program is held as its
parent; nothing leaves the job, and what a command started ends with it unless it opened a program; the commands
the app really runs still work in their tier; and a command whose limits cannot be set up is not run."""
from __future__ import annotations

import json
import os
import sys
import time

import pytest
from harness.model import call, say

from mibo.shell import confine
from mibo.shell import run as running
from mibo.shell.grants import Grants

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="these are Windows' own limits on a command")

KEY = "sk-not-a-real-key"


@pytest.fixture
def laid_out(tmp_path):
    """A folder of files and the app's home beside it, holding a key file, settings and a skill."""
    folder, home = tmp_path / "files", tmp_path / "home"
    folder.mkdir()
    for name in ("a.txt", "b.txt", "c.txt", "d.txt", "e.txt"):
        (folder / name).write_text("kept\n", encoding="utf-8")
    (home / "skills" / "tidy").mkdir(parents=True)
    (home / "credentials.json").write_text(KEY, encoding="utf-8")
    (home / "settings.json").write_text("{}", encoding="utf-8")
    (home / "skills" / "tidy" / "SKILL.md").write_text("tidy the folder\n", encoding="utf-8")
    return folder, home


def kept(folder) -> dict:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(folder.iterdir())}


def test_a_command_passed_as_reading_cannot_delete_overwrite_rename_or_write_the_registry(laid_out):
    import winreg
    folder, home = laid_out
    before = kept(folder)
    key = rf"Software\MiboConfineTest{os.getpid()}"
    winreg.CloseKey(winreg.CreateKey(winreg.HKEY_CURRENT_USER, key))
    try:
        done = running.run("Remove-Item a.txt; [IO.File]::Delete((Resolve-Path b.txt)); Set-Content c.txt changed; "
                           "Rename-Item d.txt moved.txt; New-Item new.txt | Out-Null; "
                           f"New-ItemProperty -Path 'HKCU:\\{key}' -Name written -Value 1 | Out-Null",
                           str(folder), tier="read", home=home)
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as opened, pytest.raises(OSError):
            winreg.QueryValueEx(opened, "written")
    finally:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
    assert kept(folder) == before
    assert done["recycled"] == [] and "denied" in done["err"]


@pytest.mark.parametrize("tier", confine.TIERS)
def test_no_tier_reads_lists_or_changes_the_apps_home(laid_out, tier):
    folder, home = laid_out
    done = running.run(f"Get-Content '{home}\\credentials.json'; Get-ChildItem '{home}' -Force -Name; "
                       f"Copy-Item '{home}\\credentials.json' taken.json; Set-Content '{home}\\settings.json' changed; "
                       f"Get-Content '{home}\\skills\\tidy\\SKILL.md'", str(folder), tier=tier, home=home)
    assert KEY not in done["out"] and "credentials.json" not in done["out"]
    assert not (folder / "taken.json").exists()
    assert (home / "settings.json").read_text(encoding="utf-8") == "{}"
    assert done["out"].strip() == "tidy the folder"


def test_a_child_program_is_held_as_its_parent(laid_out):
    folder, home = laid_out
    before = kept(folder)
    running.run("cmd.exe /c del /q a.txt; powershell.exe -NoProfile -Command \"Set-Content b.txt changed\"",
                str(folder), tier="read", home=home)
    assert kept(folder) == before
    done = running.run(f"cmd.exe /c type \"{home}\\credentials.json\"", str(folder), tier="change", home=home)
    assert KEY not in done["out"]


# From inside the command: whether it may leave its job (CreateProcess with CREATE_BREAKAWAY_FROM_JOB), and the UI
# limits of the job it is in (QueryInformationJobObject on no job reads the caller's own).
INSIDE = r"""Add-Type -Namespace Probe -Name Job -MemberDefinition @'
[StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)] public struct SI { public int cb; public string a, b, c;
  public int d, e, f, g, h, i, j, k; public short l, m; public IntPtr n, o, p, q; }
[StructLayout(LayoutKind.Sequential)] public struct PI { public IntPtr h, t; public int pid, tid; }
[DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)] static extern bool CreateProcessW(string app,
  string cmd, IntPtr pa, IntPtr ta, bool inherit, int flags, IntPtr env, string cwd, ref SI si, out PI pi);
[DllImport("kernel32.dll")] static extern bool QueryInformationJobObject(IntPtr job, int cls, out int info, int size,
  IntPtr got);
public static string Leave(string cmd) { var si = new SI(); si.cb = Marshal.SizeOf(si); PI pi;
  return CreateProcessW(null, cmd, IntPtr.Zero, IntPtr.Zero, false, 0x01000000 | 0x08000000, IntPtr.Zero, null,
    ref si, out pi) ? "left" : "stayed " + Marshal.GetLastWin32Error(); }
public static int Limits() { int ui; return QueryInformationJobObject(IntPtr.Zero, 4, out ui, 4, IntPtr.Zero) ? ui : -1; }
'@
[Probe.Job]::Leave('cmd.exe /c echo out> left.txt')
'ui ' + [Probe.Job]::Limits()
"""


@pytest.mark.parametrize("tier", confine.TIERS)
def test_nothing_leaves_the_job_and_its_limits_hold(laid_out, tier):
    folder, home = laid_out
    # Started with no window: one that WMI starts is shown on the person's screen, and stays when it is ended.
    done = running.run(INSIDE + "$hidden = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly "
                       "-Property @{ShowWindow = [uint16]0}; "
                       "Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments "
                       "@{CommandLine = 'cmd.exe /c echo out> wmi.txt'; ProcessStartupInformation = $hidden} "
                       "-ErrorAction SilentlyContinue | Out-Null",
                       str(folder), tier=tier, home=home)
    assert done["out"].splitlines()[0] == "stayed 5"
    ui = int(done["out"].splitlines()[1].split()[1])
    assert ui == (confine.UI_PROGRAM if tier == "program" else confine.UI_ALL)
    time.sleep(1)
    assert not (folder / "left.txt").exists()
    if tier == "read":
        # WMI starts nothing outside the job for a command at low integrity.
        assert not (folder / "wmi.txt").exists()


def test_what_a_command_started_ends_with_it_unless_it_opened_a_program(laid_out):
    folder, home = laid_out
    later = "Start-Process cmd.exe -ArgumentList '/c ping -n 3 127.0.0.1 >NUL & echo later> {}' -WindowStyle Hidden"
    running.run(later.format("changed.txt"), str(folder), tier="change", home=home)
    running.run(later.format("opened.txt"), str(folder), tier="program", home=home)
    deadline = time.monotonic() + 15
    while not (folder / "opened.txt").exists() and time.monotonic() < deadline:
        time.sleep(0.2)
    assert (folder / "opened.txt").exists() and not (folder / "changed.txt").exists()


# What the app's built-in skills and its layers' tests run, by tier, and a word of what each prints.
WORKING = {
    "read": [("Get-ChildItem -File -Recurse | Group-Object { $_.Extension } | Sort-Object Count -Descending | "
              "Select-Object Name, Count", ".txt"),
             ("Test-Path a.txt", "True"), ("Get-Content a.txt", "kept"), ("Select-String -Path *.txt -Pattern kept", "a.txt"),
             ("Get-PSDrive -PSProvider FileSystem | Select-Object Name, @{n='UsedGB';e={[math]::Round($_.Used/1GB,1)}}",
              "UsedGB"),
             ("Get-StartApps | Select-Object -First 1 | Out-Null; 'listed'", "listed")],
    "change": [("Copy-Item a.txt copied.txt; Test-Path copied.txt", "True"),
               ("New-Item -ItemType Directory sub | Out-Null; Move-Item b.txt sub; Test-Path sub\\b.txt", "True"),
               ("Compress-Archive -Path c.txt -DestinationPath c.zip; Expand-Archive c.zip out; Test-Path out\\c.txt",
                "True"),
               ("Remove-Item d.txt; Test-Path d.txt", "False")],
    "program": [("Set-Content run.cmd '@echo ran> ran.txt' -Encoding Ascii; Start-Process .\\run.cmd -WindowStyle Hidden -Wait; "
                 "Get-Content ran.txt", "ran")],
}


@pytest.mark.parametrize("tier", confine.TIERS)
def test_the_commands_the_app_runs_still_work_in_their_tier(laid_out, tier):
    folder, home = laid_out
    for command, printed in WORKING[tier]:
        done = running.run(command, str(folder), tier=tier, home=home)
        assert done["code"] == 0 and printed in done["out"] and done["err"] == "", (command, done)


def test_a_command_whose_limits_cannot_be_set_up_is_not_run(app, turn, tmp_path, monkeypatch):
    folder = tmp_path / "files"
    folder.mkdir()
    assert Grants(app.home / "runtime" / "desktop", app.home).add(str(folder)) == ""

    def refused(tier, online=False):
        raise confine.Unconfined(5, "CreateRestrictedToken: Access is denied.")

    # Nothing is waiting, and no restricted token can be made.
    monkeypatch.setattr(running, "SPARE", running.Spare())
    monkeypatch.setattr(confine, "_token", refused)
    done = turn("Make a note in my files folder", call("use_computer", command="Set-Content note.txt hello",
                                                       folder=str(folder)), say("It was not run."))
    assert not (folder / "note.txt").exists()
    told = json.dumps(done.asked(), ensure_ascii=False)
    assert "could not be set up" in told and "so it was not run" in told
