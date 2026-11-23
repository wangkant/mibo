"""The model keys' file, the settings, the browser pane's profile, the app window's storage and the visitor profile
all live in the app's home, which no tool reads, lists, searches, copies or moves: not a file tool, not a PowerShell
command by any spelling of the path (a link inside a granted folder, `..`, this computer's admin share, a device
path), not a bash command."""
from __future__ import annotations

import subprocess
import sys

import pytest

from mibo.shell import bashread, files
from mibo.shell import read as reading
from mibo.shell.grants import Grants

# The app's own places, relative to its home.
OWN = ("credentials.json", "settings.json", "runtime/desktop/browser/webview", "runtime/desktop/webview",
       "runtime/visitor", "runtime/desktop/shell.json")


@pytest.fixture
def laid_out(tmp_path):
    """A home holding the app's own places, a granted folder beside it with a junction into the home, and the
    grants."""
    home, folder = tmp_path / "home", tmp_path / "files"
    for place in OWN:
        target = home / place
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.suffix:
            target.write_text("{}", encoding="utf-8")
        else:
            target.mkdir(exist_ok=True)
    folder.mkdir()
    (folder / "a.txt").write_text("x", encoding="utf-8")
    if sys.platform == "win32":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(folder / "link"), str(home)], capture_output=True, check=True)
    grants = Grants(home / "runtime" / "desktop", home)
    assert grants.add(str(folder)) == ""
    return home, folder, grants


def spellings(home, folder, place: str) -> list[str]:
    """One place in the home as a path can name it."""
    plain = str(home / place)
    out = [plain, str(folder) + "\\..\\home\\" + place.replace("/", "\\")]
    if sys.platform == "win32":
        out += [str(folder / "link" / place), f"\\\\localhost\\{plain[0]}${plain[2:]}",
                f"\\\\127.0.0.1\\{plain[0]}${plain[2:]}", f"\\\\?\\{plain}"]
    return out


@pytest.mark.skipif(sys.platform != "win32", reason="read.py reads commands with Windows PowerShell's parser")
@pytest.mark.parametrize("place", OWN)
def test_no_file_tool_or_command_reads_the_apps_own_places_by_any_path(laid_out, place):
    home, folder, grants = laid_out
    for path in spellings(home, folder, place):
        jobs = [{"op": op, "path": path, "folder": path, "text": "key", "pattern": "", "recursive": True,
                 "sort": "name"} for op in ("read", "list", "search")]
        jobs += [{"op": "move", "copy": copy, "moves": [{"from": path, "to": str(folder / "out"), "folder": ""}]}
                 for copy in (False, True)]
        for job in jobs:
            verdict = reading.judge(reading.Reading(files.call(job), str(folder), files.acts(job, str(folder)), []),
                                    grants)
            assert verdict.action == "refuse", (job, [a.why for a in verdict.reasons])
        for command in (f'Get-Content "{path}"', f'Get-ChildItem "{path}" -Recurse', f'Copy-Item "{path}" out',
                        f'Move-Item "{path}" out', f'cmd /c type "{path}"', f'Select-String -Path "{path}\\*" key'):
            verdict = reading.judge(reading.read(command, str(folder)), grants)
            assert verdict.action == "refuse", (command, [a.why for a in verdict.reasons])


@pytest.mark.skipif(sys.platform != "win32", reason="junctions are made with mklink on Windows")
def test_a_listing_or_search_of_a_granted_folder_never_follows_a_link_into_the_home(laid_out):
    _, folder, grants = laid_out
    listed = files.listing(str(folder), grants.places, "", True, "name")
    searched = files.search(str(folder), "{}", grants.places, "")
    assert "a.txt" in listed and "credentials" not in listed and "link" not in listed
    assert "0 files hold it" in searched


@pytest.mark.parametrize("place", OWN)
def test_no_bash_command_reads_the_apps_own_places(place):
    # POSIX names, as bash gives them; nothing is looked up on disk.
    me, home = "/floor/me", "/floor/me/mibo"
    grants = Grants(home + "/runtime/desktop", home)
    target = f"{home}/{place}"
    for command in (f"cat {target}", f"ls -R {target}", f"grep -r key {target}", f"cp -r {target} ./out",
                    f"mv {target} ./out", f"tar czf out.tgz {target}", f"cat ~/mibo/{place}",
                    f"cd {home} && cat {place}", f"cat {me}/../me/mibo/{place}", f"grep -r key {me}"):
        verdict = reading.judge(bashread.read(command, f"{me}/files", me), grants)
        assert verdict.action == "refuse", (command, [a.why for a in verdict.reasons])
