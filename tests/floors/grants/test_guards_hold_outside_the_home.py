"""The guards the app places outside its home (shell/guards.py), on stand-ins of the real places: no command that is not
a program's run reads a browser profile or a password store, only one read as using the network reads network
sign-ins (.ssh), none plants something that runs later (a Startup entry, a PowerShell profile, a Run key), wherever
the reading went wrong; the person's own programs, plain, at low integrity or in an AppContainer, use the guarded
places as before; taking the guards out leaves every security descriptor exactly as it was; a first walk cut short
is finished on the next start; a file moved in later is guarded before the next command; a refusal is said in one
line; and what WMI starts for a command outside its job is ended."""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from harness.guard_standin import CHROME, KEY, RUN, SECRET, STARTUP, descriptors, keys, lay_out

from mibo.shell import acts as reads
from mibo.shell import confine, guards
from mibo.shell import read as reading
from mibo.shell import run as running

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="these are Windows' own limits on a command")

# (tier, read as using the network) of every token a command can run under.
TOKENS = (("read", False), ("change", False), ("change", True), ("program", True))


@pytest.fixture
def placed(tmp_path, monkeypatch):
    root = tmp_path / "standin"
    root.mkdir()
    laid = lay_out(root)
    with keys(monkeypatch, root) as stand_in:
        before = descriptors(root, stand_in)
        keeper = guards.Keeper(laid["home"])
        keeper.keep()
        yield {**laid, "root": root, "key": stand_in, "before": before, "keeper": keeper,
               "work": tmp_path}
        keeper.remove(everything=True)


def _run(command, placed, tier, online):
    return running.run(command, str(placed["work"]), tier=tier, online=online, home=placed["home"])


def test_a_guarded_secret_outside_the_home_is_read_only_by_the_tiers_it_belongs_to(placed):
    cookie = placed["chrome"] / "d0" / "f1.txt"
    reads = {"cookie": f"Get-Content '{cookie}'", "protected": f"Get-Content '{placed['protected']}'",
             "own entry": f"Get-Content '{placed['own']}'", "ssh key": f"Get-Content '{placed['profile']}\\.ssh\\id_ed25519'",
             "listed": f"Get-ChildItem '{placed['chrome']}' -Recurse -Name"}
    got = {}
    for name, command in reads.items():
        for tier, online in TOKENS:
            done = _run(command, placed, tier, online)
            got[(name, tier, online)] = SECRET in done["out"] or KEY in done["out"] or "f1.txt" in done["out"]
    for (name, tier, online), read in got.items():
        if tier == "program":
            assert read, (name, tier)
        elif name == "ssh key":
            assert read == online, (name, tier, online)
        else:
            assert not read, (name, tier, online)


def test_a_change_command_cannot_plant_something_that_runs_later(placed):
    import winreg
    run_key = placed["key"] + "\\" + RUN
    plants = (f"Set-Content '{placed['root'] / STARTUP}\\x.cmd' calc; "
              f"Set-Content '{placed['root']}\\documents\\WindowsPowerShell\\profile.ps1' calc; "
              f"Add-Content '{placed['profile']}\\.bashrc' calc; "
              f"New-ItemProperty -Path 'HKCU:\\{run_key}' -Name planted -Value calc | Out-Null; "
              f"New-Item -Path 'HKCU:\\{placed['key']}\\Software\\Classes\\CLSID\\x' | Out-Null; "
              f"Rename-Item '{placed['root'] / STARTUP}\\..' Moved")
    for tier, online in TOKENS[:3]:
        _run(plants, placed, tier, online)
        assert list((placed["root"] / STARTUP).iterdir()) == []
        assert not (placed["root"] / "documents" / "WindowsPowerShell" / "profile.ps1").exists()
        assert (placed["profile"] / ".bashrc").read_text(encoding="utf-8") == "echo hi\n"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key) as key, pytest.raises(OSError):
            winreg.QueryValueEx(key, "planted")
        with pytest.raises(OSError):
            winreg.OpenKey(winreg.HKEY_CURRENT_USER, placed["key"] + r"\Software\Classes\CLSID\x")
        assert (placed["root"] / STARTUP).is_dir()
    # A program the person allowed may (an installer adds its start entry).
    done = _run(f"Set-Content '{placed['root'] / STARTUP}\\x.cmd' calc; 'wrote'", placed, "program", True)
    assert done["out"] == "wrote"
    (placed["root"] / STARTUP / "x.cmd").unlink()


def _low_copy_of_own_token():
    k32, adv = confine._api()
    own, dup = ctypes.c_void_p(), ctypes.c_void_p()
    confine._ok(adv.OpenProcessToken(k32.GetCurrentProcess(), 0x1 | 0x2 | 0x8 | 0x80, ctypes.byref(own)), "open")
    adv.DuplicateTokenEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                                     ctypes.POINTER(ctypes.c_void_p)]
    confine._ok(adv.DuplicateTokenEx(own, 0x02000000, None, 2, 1, ctypes.byref(dup)), "DuplicateTokenEx")
    k32.CloseHandle(own)
    level = confine._Sid(confine.LOW_INTEGRITY)
    label = confine.SID_AND_ATTRIBUTES(level.value, confine.SE_GROUP_INTEGRITY)
    confine._ok(adv.SetTokenInformation(dup, 25, ctypes.byref(label), ctypes.sizeof(label) + adv.GetLengthSid(level.value)),
                "SetTokenInformation")
    return dup


def _start_with(token, command_line: str, attributes=None) -> int:
    """Runs a program under `token` (or this process's own, as an AppContainer with `attributes`), waits, its code."""
    k32, _ = confine._api()
    startup = confine.STARTUPINFOEXW()
    startup.StartupInfo.cb = ctypes.sizeof(startup)
    info = confine.PROCESS_INFORMATION()
    flags = confine.CREATE_NO_WINDOW | (confine.EXTENDED_STARTUPINFO_PRESENT if attributes is not None else 0)
    if attributes is not None:
        startup.lpAttributeList = ctypes.cast(attributes, ctypes.c_void_p)
    line = ctypes.create_unicode_buffer(command_line)
    if token is None:
        k32.CreateProcessW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int,
                                       ctypes.c_uint32, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_void_p,
                                       ctypes.c_void_p]
        confine._ok(k32.CreateProcessW(None, line, None, None, False, flags, None, None, ctypes.byref(startup),
                                       ctypes.byref(info)), "CreateProcess")
    else:
        confine._ok(k32.CreateProcessAsUserW(token, None, line, None, None, False, flags, None, None,
                                             ctypes.byref(startup), ctypes.byref(info)), "CreateProcessAsUser")
    k32.WaitForSingleObject(info.hProcess, 30000)
    code = confine.DWORD()
    k32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
    k32.CloseHandle(info.hProcess)
    k32.CloseHandle(info.hThread)
    return code.value


def test_the_persons_own_programs_use_the_guarded_places_as_before(placed, tmp_path):
    cookie, key = placed["chrome"] / "d0" / "f1.txt", placed["profile"] / ".ssh" / "id_ed25519"
    cmd = os.path.join(os.environ.get("SYSTEMROOT", r"C:\Windows"), "System32", "cmd.exe")
    # The person's ordinary token.
    for path, text in ((cookie, SECRET), (key, KEY)):
        assert subprocess.run([cmd, "/c", "type", str(path)], capture_output=True, text=True).stdout == text
    # A low integrity child of theirs (as a browser's or a reader's protected process), which may also write where
    # low writes are allowed: here, nowhere else, so it copies by printing.
    low = _low_copy_of_own_token()
    try:
        out = tmp_path / "low.txt"
        (tmp_path / "low.cmd").write_text(f'@type "{cookie}" > nul && @type "{key}" > nul && exit 0\r\n@exit 1\r\n',
                                          encoding="ascii")
        assert _start_with(low, f'"{cmd}" /c "{tmp_path / "low.cmd"}"') == 0
        assert not out.exists()
    finally:
        confine._api()[0].CloseHandle(low)
    # An AppContainer, given its own entry on the place as a browser gives its sandboxed processes.
    userenv = ctypes.WinDLL("userenv")
    name = f"mibo.test.{os.getpid()}"
    sid = ctypes.c_void_p()
    userenv.CreateAppContainerProfile.argtypes = [ctypes.c_wchar_p] * 3 + [ctypes.c_void_p, ctypes.c_uint32,
                                                                           ctypes.POINTER(ctypes.c_void_p)]
    userenv.DeleteAppContainerProfile.argtypes = [ctypes.c_wchar_p]
    assert userenv.CreateAppContainerProfile(name, name, name, None, 0, ctypes.byref(sid)) == 0
    try:
        container = confine._sid_text(sid)
        plain = tmp_path / "plain"
        plain.mkdir()
        (plain / "a.txt").write_text("a", encoding="ascii")
        for path in (cookie.parent.parent.parent, key.parent, plain):
            subprocess.run(["icacls", str(path), "/grant", f"*{container}:(OI)(CI)(RX)", "/Q"], check=True,
                           capture_output=True)

        class SECURITY_CAPABILITIES(ctypes.Structure):
            _fields_ = [("AppContainerSid", ctypes.c_void_p), ("Capabilities", ctypes.c_void_p),
                        ("CapabilityCount", ctypes.c_uint32), ("Reserved", ctypes.c_uint32)]

        k32 = confine._api()[0]
        size = ctypes.c_size_t()
        k32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
        attributes = ctypes.create_string_buffer(size.value)
        k32.InitializeProcThreadAttributeList(attributes, 1, 0, ctypes.byref(size))
        caps = SECURITY_CAPABILITIES(sid, None, 0, 0)
        k32.UpdateProcThreadAttribute(attributes, 0, 0x20009, ctypes.byref(caps), ctypes.sizeof(caps), None, None)
        # On a computer where an AppContainer reads nothing even from a folder with no guard, this tells nothing.
        if _start_with(None, f'"{cmd}" /c type "{plain / "a.txt"}" > nul', attributes) != 0:
            pytest.skip("an AppContainer started here reads no file, guarded or not")
        assert _start_with(None, f'"{cmd}" /c type "{cookie}" > nul && type "{key}" > nul', attributes) == 0
        # Without its entry it reads nothing: the AppContainer itself, not this check, is what held it before.
        k32.DeleteProcThreadAttributeList(attributes)
    finally:
        for path in (cookie.parent.parent.parent, key.parent):
            subprocess.run(["icacls", str(path), "/remove", f"*{confine._sid_text(sid)}", "/T", "/Q"],
                           capture_output=True)
        userenv.DeleteAppContainerProfile(name)


def test_taking_the_guards_out_leaves_every_descriptor_as_it_was(tmp_path, monkeypatch):
    for modern in (True, False):
        root = tmp_path / f"standin-{modern}"
        root.mkdir()
        laid = lay_out(root, files=120, modern=modern)
        with keys(monkeypatch, root) as stand_in:
            before = descriptors(root, stand_in)
            keeper = guards.Keeper(laid["home"])
            data = keeper.keep()
            assert all(row.get("done") for row in data["places"].values() if not row.get("skipped"))
            during = descriptors(root, stand_in)
            assert sum(during[p] != before[p] for p in before) > 120
            keeper.remove(everything=True)
            after = descriptors(root, stand_in)
        changed = [p for p in before if after.get(p) != before[p]]
        assert changed == [], (modern, changed[:3], [(before[p], after.get(p)) for p in changed[:2]])
        assert set(after) - set(before) <= {str(laid["home"] / "runtime"), str(laid["home"] / "runtime" / "desktop"),
                                            str(laid["home"] / "runtime" / "desktop" / "guards.json")}


def test_a_first_walk_cut_short_is_finished_on_the_next_start(tmp_path, monkeypatch):
    root = tmp_path / "standin"
    root.mkdir()
    laid = lay_out(root, files=600)
    with keys(monkeypatch, root):
        real, calls = guards._add, []

        def cut_short(*args, **kwargs):
            calls.append(1)
            if len(calls) > 300:
                raise SystemExit("the app was stopped")
            return real(*args, **kwargs)

        monkeypatch.setattr(guards, "_add", cut_short)
        with pytest.raises(SystemExit):
            guards.Keeper(laid["home"]).keep()
        record = json.loads((laid["home"] / "runtime" / "desktop" / "guards.json").read_text(encoding="utf-8"))
        unfinished = [path for path, row in record["places"].items() if row["done"] is None]
        assert unfinished
        files = list(Path(root / CHROME).rglob("*"))
        assert not all(guards.carries(str(p), "file", confine.GUARD_SID) for p in files)
        monkeypatch.setattr(guards, "_add", real)
        # The next start.
        keeper = guards.Keeper(laid["home"])
        data = keeper.keep()
        assert all(row["done"] for row in data["places"].values() if not row.get("skipped"))
        assert all(guards.carries(str(p), "file", confine.GUARD_SID) for p in files)
        keeper.remove(everything=True)


def test_a_file_moved_into_a_small_guarded_place_is_guarded_before_the_next_command(placed):
    outside = placed["work"] / "id_new"
    outside.write_text(KEY, encoding="utf-8")
    # A move on the same drive keeps the list the file had.
    os.replace(outside, placed["profile"] / ".ssh" / "id_new")
    done = _run(f"Get-Content '{placed['profile']}\\.ssh\\id_new'", placed, "change", False)
    assert KEY not in done["out"]


def test_a_refusal_is_said_in_one_line_that_names_the_limit(placed, tmp_path):
    (tmp_path / "a.txt").write_text("kept\n", encoding="utf-8")
    done = _run("Set-Content a.txt changed", placed, "read", False)
    line = guards.refused_line(done["err"], "read", False, placed["home"])
    assert line.startswith("Windows refused the change because this command was read as only reading")
    done = _run(f"Get-Content '{placed['chrome'] / 'd0' / 'f1.txt'}'", placed, "change", False)
    line = guards.refused_line(done["err"], "change", False, placed["home"])
    assert "saved passwords, browser data or sign-ins" in line and "\n" not in line
    ssh = f"Access to the path '{placed['profile'] / '.ssh' / 'id_ed25519'}' is denied."
    assert "network sign-ins" in guards.refused_line(ssh, "change", False, placed["home"])
    assert guards.refused_line(ssh, "change", True, placed["home"]) == ""
    # ssh words it with the path bare.
    bare = f"Can't open user config file {placed['profile'] / '.ssh' / 'config'}: Permission denied"
    assert "network sign-ins" in guards.refused_line(bare, "change", False, placed["home"])
    # ssh, a cloud tool: what the reading cannot bound runs with the network and its sign-ins (a cloud tool that
    # is installed here is a program the person allows, which has both).
    for command in ("ssh example.invalid uptime", "aws s3 ls", "git push"):
        acts = reading.read(command, str(tmp_path)).acts
        assert guards.online(acts) or reads.tier(acts) == "program", command
    assert not guards.online(reading.read("Get-Content a.txt", str(tmp_path)).acts)
    assert guards.refused_line("Cannot find path 'x' because it does not exist.", "read", False, placed["home"]) == ""


def test_the_model_is_told_which_limit_stopped_a_command(app, turn, tmp_path, monkeypatch):
    from harness.model import call, say

    from mibo.shell import panel
    from mibo.shell.grants import Grants
    folder = tmp_path / "files"
    folder.mkdir()
    (folder / "note.txt").write_text("kept\n", encoding="utf-8")
    assert Grants(app.home / "runtime" / "desktop", app.home).add(str(folder)) == ""
    # The reading is wrong on purpose: a change passed as only reading.
    monkeypatch.setattr(panel, "tier_of", lambda acts: "read")
    done = turn("Change my note", call("use_computer", command="Set-Content note.txt changed", folder=str(folder)),
                say("Windows refused it."))
    assert (folder / "note.txt").read_text(encoding="utf-8") == "kept\n"
    told = json.dumps(done.asked(), ensure_ascii=False)
    assert "Windows' limits: Windows refused the change because this command was read as only reading" in told


def test_what_wmi_starts_for_a_command_outside_its_job_is_ended(placed, tmp_path):
    late = tmp_path / "late.txt"
    # Started with no window: one that WMI starts is shown on the person's screen, and stays when it is ended.
    done = _run("$hidden = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly -Property @{ShowWindow = [uint16]0}; "
                "Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments "
                f"@{{CommandLine = 'cmd.exe /c ping -n 6 127.0.0.1 >NUL & echo late> \"{late}\"'; "
                "ProcessStartupInformation = $hidden} | Out-Null; Start-Sleep 2", placed, "change", False)
    assert done["code"] == 0
    time.sleep(8)
    assert not late.exists()


def test_every_place_windows_closes_is_one_the_reading_refuses_too(tmp_path, monkeypatch):
    """The guards are a second wall behind the reading, not a list of their own: each file place they close on the
    real profile (computed, nothing placed) is one grants.Places already refuses, but the anchors that only keep a
    folder above from being renamed."""
    from mibo.shell.grants import Places, norm
    monkeypatch.delenv(guards.PLACES_ENV)
    home = tmp_path / "home"
    home.mkdir()
    places = Places(home)
    for place in guards.places(home):
        if place.kind != "file" or place.mask == guards.STAYS:
            continue
        assert places.blocked(norm(place.path), write=place.why in ("later", "app")), (place.why, place.path)


def test_a_place_guarded_by_an_earlier_version_gets_this_versions_entry(tmp_path, monkeypatch):
    root = tmp_path / "standin"
    root.mkdir()
    laid = lay_out(root)
    documents = str(root / "documents")
    with keys(monkeypatch, root):
        # As a version that only kept the folder itself from being renamed left it.
        monkeypatch.setattr(guards, "STAYS", guards.DELETE)
        guards.Keeper(laid["home"]).keep()
        assert "(D;;SD;;;" in guards.sddl(documents)
        monkeypatch.setattr(guards, "STAYS", guards.DELETE | 0x40)
        keeper = guards.Keeper(laid["home"])
        data = keeper.keep()
        assert "(D;;DTSD;;;" in guards.sddl(documents) and guards.sddl(documents).count(confine.GUARD_SID) == 1
        assert data["places"][documents]["mask"] == guards.STAYS
        keeper.remove(everything=True)
        assert confine.GUARD_SID not in guards.sddl(documents)
