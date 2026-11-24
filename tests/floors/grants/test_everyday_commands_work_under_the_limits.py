"""Every everyday command still works under Windows' limits: each runs through the real run() in the tier its reading
gives (acts.tier, and whether it uses the network), with the guards placed on a stand-in profile that the command's
environment points at (its .ssh, .gitconfig, browser profile, Startup folder, PowerShell profile folder and Run key),
and must succeed with exactly what the same command prints with no limits at all (the same pipeline under a plain copy
of the person's token). They come from the built-in skills, the app's tests and ordinary use: listing, sorting,
grouping and measuring; reading, searching, hashing and comparing; copying, moving and renaming many files, on two
drives; archives; making folders and files; the Recycle Bin; drives, volumes, processes, services, the date, Start's
apps, the registry, commands; git; Python, pip and a venv; node and npm when there; tar, curl, robocopy, ssh; and a
program opened, by a stand-in program. MIBO_CORPUS_REPORT names a file each result is added to, for the table."""
from __future__ import annotations

import contextlib
import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from harness.guard_standin import lay_out

from mibo.shell import acts, confine, guards
from mibo.shell import read as reading
from mibo.shell import run as running

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="these are Windows' own limits on a command")

PY = sys.executable
# (name, command). {other}: a folder on another drive; {py}: a Python. Each starts in a fresh folder of files.
CASES = [
    ("list recursive sorted", "Get-ChildItem -Recurse -File | Sort-Object Name | Select-Object -ExpandProperty Name"),
    ("group by extension", "Get-ChildItem -Recurse -File | Group-Object Extension | Sort-Object Name | "
                           "ForEach-Object { \"$($_.Name) $($_.Count)\" }"),
    ("measure sizes", "(Get-ChildItem -Recurse -File | Measure-Object Length -Sum).Sum"),
    ("largest files", "Get-ChildItem -Recurse -File | Sort-Object Length -Descending | Select-Object -First 3 Name, Length"),
    ("read a file", "Get-Content a.txt"),
    ("read csv", "Import-Csv data.csv | Sort-Object {[int]$_.n} -Descending | Select-Object -First 1 -ExpandProperty name"),
    ("search text", "Select-String -Path *.txt -Pattern kept | ForEach-Object Filename"),
    ("hash a file", "(Get-FileHash a.txt -Algorithm SHA256).Hash"),
    ("compare files", "Compare-Object (Get-Content a.txt) (Get-Content b.txt) | Measure-Object | ForEach-Object Count"),
    ("count lines", "Get-Content notes.md | Measure-Object -Line | ForEach-Object Lines"),
    ("test a path", "Test-Path sub"),
    ("drives", "Get-PSDrive -PSProvider FileSystem | Where-Object Name -eq 'C' | ForEach-Object Name"),
    ("volume", "(Get-Volume -DriveLetter C).DriveLetter"),
    ("own process", "(Get-Process -Id $PID).ProcessName"),
    ("a service", "Get-Service -Name Winmgmt | ForEach-Object { \"$($_.Name) $($_.Status)\" }"),
    ("the date", "(Get-Date).Year"),
    ("start apps", "(Get-StartApps | Measure-Object).Count -gt 0"),
    ("registry HKLM", "(Get-ItemProperty 'HKLM:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion').CurrentBuild"),
    ("registry HKCU", "(Get-Item 'HKCU:\\Control Panel\\Desktop').PSChildName"),
    ("find a command", "(Get-Command Get-ChildItem).Name"),
    ("where.exe", "where.exe cmd"),
    ("profile listing", "Get-ChildItem $env:USERPROFILE -Force -Name | Sort-Object"),
    ("git version", "git --version"),
    ("git config", "git config --global --get user.name"),
    ("git repo", "git init -q r; Set-Content r\\f.txt hi; git -C r add f.txt; "
                 "git -C r -c user.email=t@e.invalid commit -qm first; Add-Content r\\f.txt more; "
                 "git -C r status --short; git -C r diff --stat | Select-Object -Last 1; "
                 "(git -C r log --oneline | Measure-Object).Count"),
    ("python version", "& '{py}' --version"),
    ("python prints", "& '{py}' -c \"print(sum(range(10)))\""),
    ("python writes a file", "Set-Content s.py \"open('o.txt','w').write('made')\"; & '{py}' s.py; Get-Content o.txt"),
    ("pip list", "& '{py}' -m pip list --disable-pip-version-check --no-color --format freeze | Measure-Object | "
                 "ForEach-Object { $_.Count -gt 0 }"),
    ("venv", "& '{py}' -m venv --without-pip v; Test-Path v\\Scripts\\python.exe"),
    ("copy many", "Copy-Item sub sub2 -Recurse; (Get-ChildItem sub2 -Recurse -File).Count"),
    ("rename many", "Get-ChildItem sub -File | Rename-Item -NewName { $_.Name -replace '^f', 'g' }; "
                    "(Get-ChildItem sub -Filter g*).Count"),
    ("move across drives", "Move-Item a.txt '{other}\\a.txt'; Test-Path '{other}\\a.txt'; Test-Path a.txt"),
    ("copy across drives", "Copy-Item sub '{other}\\sub' -Recurse; (Get-ChildItem '{other}\\sub' -File).Count"),
    ("archive", "Compress-Archive -Path sub -DestinationPath s.zip; Expand-Archive s.zip out; "
                "(Get-ChildItem out -Recurse -File).Count"),
    ("new folders and files", "New-Item -ItemType Directory x\\y\\z -Force | Out-Null; "
                              "New-Item x\\y\\z\\f.txt -Value hi | Out-Null; Get-Content x\\y\\z\\f.txt"),
    ("write a report", "Get-ChildItem -File | Select-Object Name | Out-File list.txt; (Get-Content list.txt).Count -gt 2"),
    ("recycle bin delete", "Remove-Item e.txt; Test-Path e.txt"),
    ("tar", "tar -cf t.tar a.txt b.txt; tar -tf t.tar"),
    ("curl version", "(curl.exe --version | Select-Object -First 1).Split(' ')[0]"),
    ("robocopy", "robocopy sub sub3 /E /NJH /NJS /NP /NFL /NDL | Out-Null; (Get-ChildItem sub3 -File).Count; "
                 "$global:LASTEXITCODE = 0"),
    ("ssh version", "ssh -V 2>&1 | ForEach-Object { \"$_\".Split('_')[0] }"),
    ("ssh reads its config", "ssh -F \"$env:USERPROFILE\\.ssh\\config\" -G example.invalid | "
                             "Select-String '^user ' | ForEach-Object Line"),
    ("node version", "node --version"),
    ("npm version", "npm --version"),
    ("open a program", "Set-Content run.cmd '@echo ran> ran.txt' -Encoding Ascii; "
                       "Start-Process .\\run.cmd -WindowStyle Hidden -Wait; Get-Content ran.txt"),
]
NEEDS = {"node version": "node", "npm version": "npm", "ssh version": "ssh", "ssh reads its config": "ssh",
         "tar": "tar", "curl version": "curl", "git version": "git", "git config": "git", "git repo": "git"}


def _files(root: Path) -> Path:
    work = root / "work"
    (work / "sub").mkdir(parents=True)
    for name in "abcde":
        (work / f"{name}.txt").write_text(f"kept {name}\n", encoding="utf-8")
    (work / "data.csv").write_text("name,n\nalpha,3\nbeta,12\ngamma,7\n", encoding="utf-8")
    (work / "notes.md").write_text("# notes\none\ntwo\n", encoding="utf-8")
    for i in range(30):
        (work / "sub" / f"f{i:02}.log").write_text("x" * i, encoding="utf-8")
    return work


def _other_drive(tmp_path: Path) -> Path | None:
    """A folder on a drive other than the test's own, for moves across drives."""
    for base in (os.environ.get("RUNNER_TEMP"), tempfile.gettempdir(), os.environ.get("GITHUB_WORKSPACE")):
        if base and os.path.splitdrive(base)[0].lower() != os.path.splitdrive(str(tmp_path))[0].lower():
            return Path(tempfile.mkdtemp(prefix="mibo-corpus-", dir=base))
    return None


def _plain_token(tier, online=False):
    """A plain copy of this process's own token: the same pipeline with no limits, for what a command prints."""
    k32, adv = confine._api()
    own, dup = ctypes.c_void_p(), ctypes.c_void_p()
    confine._ok(adv.OpenProcessToken(k32.GetCurrentProcess(), 0x1 | 0x2 | 0x8, ctypes.byref(own)), "open")
    adv.DuplicateTokenEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                                     ctypes.POINTER(ctypes.c_void_p)]
    confine._ok(adv.DuplicateTokenEx(own, 0x02000000, None, 2, 1, ctypes.byref(dup)), "DuplicateTokenEx")
    k32.CloseHandle(own)
    return dup


def _empty_bin_of(root: str) -> None:
    """Takes out of the Recycle Bin only what a test deleted from under `root`."""
    sid = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True, text=True).stdout.split(",")[-1]
    folder = Path(os.path.splitdrive(root)[0] + "\\", "$Recycle.Bin", sid.strip().strip('"'))
    with contextlib.suppress(OSError):
        for info in folder.glob("$I*"):
            raw = info.read_bytes()
            if raw[28:].decode("utf-16-le", "ignore").split("\0")[0].lower().startswith(root.lower()):
                data = info.with_name("$R" + info.name[2:])
                shutil.rmtree(data, ignore_errors=True) if data.is_dir() else data.unlink(missing_ok=True)
                info.unlink()


@pytest.fixture(scope="module")
def standin(tmp_path_factory):
    root = tmp_path_factory.mktemp("corpus-profile")
    laid = lay_out(root, files=40)
    with pytest.MonkeyPatch.context() as mp:
        import uuid
        import winreg
        key = rf"Software\mibo-test-{uuid.uuid4().hex[:12]}"
        mp.setenv("MIBO_GUARD_PLACES", str(root))
        mp.setenv("MIBO_GUARD_KEYS", key)
        keeper = guards.Keeper(laid["home"])
        keeper.keep()
        try:
            yield {**laid, "root": root, "keeper": keeper}
        finally:
            keeper.remove(everything=True)
            from harness.guard_standin import _delete_tree
            _delete_tree(winreg.HKEY_CURRENT_USER, key)
            reading.PARSER.close()


def _run_both(command: str, tmp_path: Path, standin: dict, monkeypatch, tier: str, online: bool):
    results = {}
    for side in ("plain", "limited"):
        root = tmp_path / side
        work = _files(root)
        other = _other_drive(tmp_path) or (root / "other")
        other.mkdir(exist_ok=True)
        line = command.replace("{other}", str(other)).replace("{py}", PY)
        with monkeypatch.context() as mp:
            mp.setattr(running, "SPARE", running.Spare())
            if side == "plain":
                mp.setattr(confine, "_token", _plain_token)
            try:
                done = running.run(line, str(work), tier=tier, online=online, home=standin["home"], limit_s=120)
            finally:
                running.SPARE.close()
        for path in (str(other), str(root)):
            _empty_bin_of(path)
        shutil.rmtree(other, ignore_errors=True)
        out = done["out"].replace(str(other), "<other>").replace(str(work), "<work>")
        results[side] = {"code": done["code"], "out": out, "err": done["err"]}
    return results


@pytest.mark.parametrize(("name", "command"), CASES, ids=[c[0] for c in CASES])
def test_an_everyday_command_works_as_it_does_with_no_limits(name, command, standin, tmp_path, monkeypatch):
    if name in NEEDS and not shutil.which(NEEDS[name]):
        pytest.skip(f"{NEEDS[name]} is not installed here")
    profile = standin["profile"]
    # The command's environment points at the stand-in profile, so what programs find by it (git's .gitconfig,
    # ssh's .ssh, pip's AppData) is what the guards were placed on.
    drive, rest = os.path.splitdrive(str(profile))
    for name_, value in (("USERPROFILE", profile), ("HOMEDRIVE", drive), ("HOMEPATH", rest),
                         ("APPDATA", profile / "AppData" / "Roaming"), ("LOCALAPPDATA", profile / "AppData" / "Local")):
        monkeypatch.setenv(name_, str(value))
    read_ = reading.read(command.replace("{py}", PY).replace("{other}", str(tmp_path)), str(tmp_path))
    tier, online = acts.tier(read_.acts), guards.online(read_.acts)
    got = _run_both(command, tmp_path, standin, monkeypatch, tier, online)
    report = os.environ.get("MIBO_CORPUS_REPORT")
    if report:
        with open(report, "a", encoding="utf-8") as f:
            f.write(json.dumps({"name": name, "tier": tier, "online": online, **got}, ensure_ascii=False) + "\n")
    plain, limited = got["plain"], got["limited"]
    assert plain["code"] == 0 and plain["out"], plain
    assert (limited["code"], limited["out"]) == (plain["code"], plain["out"]), (tier, online, limited)
    assert limited["err"] == plain["err"], (tier, online, limited["err"])
