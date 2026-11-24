"""open finds a program by the name the person says, as Start's search does (mibo/desk/names.py, win32.py): Start's
shortcuts for the person and for everyone, the Desktop's, and the programs registered by file name (App Paths);
the closest name wins, and none is said plainly. A program a launcher starts (DeepL through Zero Install, whose
window is neither the launcher's file nor beside it) is known by its window's own name. (2026-11-23: open: DeepL
started DeepL, saw no window of the launcher's, answered with an error and told the model not to try another way;
it went to the web page instead.) The Start menu, the Desktop and the registry are stand-ins in a temp folder;
nothing is started."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="the app starts other programs on Windows only")

LAUNCHER = r"C:\stand-in\Zero Install\0install-win.exe"


@pytest.fixture
def start(tmp_path, monkeypatch):
    """Stand-in Start menu folders (the person's and everyone's), Desktop and App Paths; a shortcut is a text file
    naming what it opens."""
    from mibo.desk import names, win32
    from mibo.shell import grants
    mine, everyone, desktop = (tmp_path / "Start" / "Programs", tmp_path / "Common" / "Programs",
                               tmp_path / "Desktop")
    for folder in (mine, everyone, desktop):
        folder.mkdir(parents=True)
    links = {mine / "DeepL.lnk": LAUNCHER, everyone / "Word.lnk": r"C:\stand-in\Office\WINWORD.EXE",
             everyone / "Accessories" / "WordPad.lnk": r"C:\stand-in\wordpad.exe",
             desktop / "网易云音乐.lnk": r"C:\stand-in\CloudMusic\cloudmusic.exe"}
    for link, aim in links.items():
        link.parent.mkdir(parents=True, exist_ok=True)
        link.write_text(aim, encoding="utf-8")
    folders = {win32.PROGRAMS[0]: str(mine), win32.PROGRAMS[1]: str(everyone), grants.KNOWN[2][1]: str(desktop)}
    monkeypatch.setattr(grants, "known_folder", lambda guid: folders.get(guid, ""))
    monkeypatch.setattr(win32, "link_reader", lambda: lambda path: path if path.lower().endswith(".exe")
                        else Path(path).read_text(encoding="utf-8"))
    monkeypatch.setattr(win32, "link_arguments", lambda path: "")
    monkeypatch.setattr(win32, "start_apps", list)
    monkeypatch.setattr(win32, "app_paths", lambda: [("WINWORD", r"C:\stand-in\Office\WINWORD.EXE"),
                                                     ("vlc", r"C:\stand-in\VLC\vlc.exe")])
    monkeypatch.setattr(names, "open_windows", list)
    monkeypatch.setattr(names, "_apps", (0.0, []))
    return SimpleNamespace(mine=mine, everyone=everyone, desktop=desktop)


def test_a_program_is_found_by_its_name_in_start_on_the_desktop_or_by_its_file_name(start):
    from mibo.desk import names
    deepl = names.find("DeepL").app
    assert (deepl.name, deepl.file, deepl.target) == ("DeepL", str(start.mine / "DeepL.lnk"), LAUNCHER)
    assert names.find("网易云音乐").app.file == str(start.desktop / "网易云音乐.lnk")
    assert names.find("网易云").app.name == "网易云音乐"
    # The closest name wins: Word over WordPad; a program known only by its file name is found by it.
    assert names.find("Word").app.name == "Word"
    assert names.find("vlc").app.target == r"C:\stand-in\VLC\vlc.exe"


def test_a_name_nothing_answers_to_is_said_plainly_and_the_model_may_use_the_web(start):
    import inspect

    from mibo import surface
    from mibo.desk import names
    found = names.find("Grammarly")
    assert (found.hwnd, found.app, found.several) == (0, None, False)
    # The answer leaves the web open to the model in the same turn; only a program on the never list says not to.
    said = inspect.getsource(surface)
    assert "If a website does what they" in said and "If the program's website does what they asked" in said


def test_a_launchers_program_is_known_by_its_windows_name_and_started_once_with_no_question(start, monkeypatch):
    from mibo.desk import names, win32
    from mibo.desk.panel import Desk
    started, logged = [], []
    window = names.Window(4242, r"C:\stand-in\0install.net\implementations\sha256=ab\DeepL.exe", "DeepL", "DeepL")
    monkeypatch.setattr(win32, "open_file", started.append)
    monkeypatch.setattr(win32, "open_app", started.append)
    monkeypatch.setattr(names, "open_windows", lambda: [window] if started else [])
    monkeypatch.setattr(win32, "minimized", lambda hwnd: False)
    desk = SimpleNamespace(grants=SimpleNamespace(blocked_by=lambda program: "", log=logged.append))
    app = names.find("DeepL").app
    assert Desk._launch(desk, app) == {"hwnd": 4242}
    assert started == [str(start.mine / "DeepL.lnk")] and logged[-1]["status"] == "ok"
    # Another program's new window is not taken for it.
    other = names.Window(7, r"C:\stand-in\notepad.exe", "Untitled - Notepad", "Notepad")
    assert not names.named(app, other) and names.named(app, window)


def test_a_program_that_came_from_the_web_is_never_started(start, monkeypatch, tmp_path):
    from mibo.desk import names, win32
    from mibo.desk.panel import Desk
    started = []
    monkeypatch.setattr(win32, "open_file", started.append)
    tool = start.desktop / "tool.exe"
    tool.write_bytes(b"MZ")
    with open(f"{tool}:Zone.Identifier", "w", encoding="utf-8") as mark:
        mark.write("[ZoneTransfer]\nZoneId=3\n")
    names._apps = (0.0, [])
    app = names.find("tool").app
    desk = SimpleNamespace(grants=SimpleNamespace(blocked_by=lambda program: "", log=lambda entry: None))
    assert Desk._launch(desk, app)["status"] == "refused" and started == []
