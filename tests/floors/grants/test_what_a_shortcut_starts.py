"""What came from the web is never started for the person, whatever names it (desk/panel.py `what_runs`): a shortcut
is judged by what it starts, the script it hands its program and a .url's file as well as itself; and a shortcut
that hands a command to an interpreter or a system tool is that command, never the program the person named.
(2026-11-23 review of 8b57f6f: a Desktop shortcut to a downloaded tool.exe and one to a downloaded .hta were started
by name with no question, as only the .lnk itself was checked.)

The Desktop, Start and Downloads are stand-ins in a temp folder; a shortcut is a text file naming what it starts and
its arguments. Nothing is started."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="the app starts other programs on Windows only")


def from_the_web(path: Path, body: bytes = b"MZ") -> Path:
    path.write_bytes(body)
    with open(f"{path}:Zone.Identifier", "w", encoding="utf-8") as mark:
        mark.write("[ZoneTransfer]\nZoneId=3\n")
    return path


@pytest.fixture
def desktop(tmp_path, monkeypatch):
    from mibo.desk import names, win32
    from mibo.shell import grants
    folders = {guid: str(tmp_path / name) for guid, name in ((win32.PROGRAMS[0], "Start"), (win32.PROGRAMS[1], "Common"),
                                                               (grants.KNOWN[2][1], "Desktop"))}
    for folder in (*folders.values(), str(tmp_path / "Downloads")):
        Path(folder).mkdir()
    monkeypatch.setattr(grants, "known_folder", lambda guid: folders.get(guid, ""))
    monkeypatch.setattr(win32, "link_reader", lambda: lambda path, field="TargetPath": path if path.endswith(".exe")
                        else "" if path.endswith(".url")
                        else Path(path).read_text(encoding="utf-8").split("|")[field != "TargetPath"])
    monkeypatch.setattr(win32, "link_arguments", lambda path: Path(path).read_text(encoding="utf-8").split("|")[1]
                        if path.endswith(".lnk") else "", raising=False)
    monkeypatch.setattr(win32, "start_apps", list)
    monkeypatch.setattr(win32, "app_paths", list)
    monkeypatch.setattr(names, "open_windows", list)
    monkeypatch.setattr(names, "_apps", (0.0, []))
    started = []
    monkeypatch.setattr(win32, "open_file", started.append)
    monkeypatch.setattr(win32, "open_app", started.append)
    return SimpleNamespace(desk=tmp_path / "Desktop", downloads=tmp_path / "Downloads", started=started)


def launch(name: str) -> dict:
    from mibo.desk import names
    from mibo.desk.panel import Desk
    names._apps = (0.0, [])
    desk = SimpleNamespace(grants=SimpleNamespace(blocked_by=lambda program: "", log=lambda entry: None))
    return Desk._launch(desk, names.find(name).app)


def test_a_shortcut_to_what_came_from_the_web_never_starts_it(desktop):
    tool = from_the_web(desktop.downloads / "tool.exe")
    page = from_the_web(desktop.downloads / "invoice.hta", b"<script></script>")
    script = from_the_web(desktop.downloads / "setup.py", b"print(1)")
    (desktop.desk / "Notes.lnk").write_text(f"{tool}|", encoding="utf-8")
    (desktop.desk / "Invoice.lnk").write_text(f"{page}|", encoding="utf-8")
    (desktop.desk / "Setup.lnk").write_text(f'C:\\Python313\\python.exe|"{script}"', encoding="utf-8")
    (desktop.desk / "Report.url").write_text(f"[InternetShortcut]\nURL=file:///{tool.as_posix()}\n", encoding="utf-8")
    for name in ("Notes", "Invoice", "Setup", "Report"):
        assert launch(name)["status"] == "refused", name
    assert desktop.started == []


def test_a_shortcut_that_hands_a_command_to_a_shell_is_not_the_program_named(desktop):
    (desktop.desk / "Backup.lnk").write_text(
        "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe|-NoProfile -Command Remove-Item ~\\Documents -Recurse",
        encoding="utf-8")
    result = launch("Backup")
    assert result.get("status") not in ("done", "ok", None) and "hwnd" not in result and desktop.started == []


def test_a_file_url_a_share_a_risky_document_and_an_address_handed_to_explorer_are_never_started(desktop):
    """(2026-11-23 review of 0368fcc: a .url to file://localhost/ named a downloaded .hta and one to another
    computer's share were opened, Word was started on a downloaded .docm, and Explorer on a web address.)"""
    page = from_the_web(desktop.downloads / "invoice.hta", b"<script></script>")
    macro = from_the_web(desktop.downloads / "report.docm", b"x")
    (desktop.desk / "Local.url").write_text(f"[InternetShortcut]\nURL=file://localhost/{page.as_posix()}\n",
                                            encoding="utf-8")
    (desktop.desk / "Share.url").write_text("[InternetShortcut]\nURL=file://e.example/share/x.exe\n", encoding="utf-8")
    (desktop.desk / "Report.lnk").write_text(f"C:\\Program Files\\Microsoft Office\\WINWORD.EXE|{macro}",
                                             encoding="utf-8")
    (desktop.desk / "Remote.lnk").write_text("\\\\e.example\\share\\tool.exe|", encoding="utf-8")
    (desktop.desk / "Payload.lnk").write_text("C:\\Windows\\explorer.exe|https://e.example/payload.exe",
                                              encoding="utf-8")
    for name in ("Local", "Share", "Report", "Remote"):
        assert launch(name)["status"] == "refused", name
    assert launch("Payload")["status"] == "unfound"
    assert desktop.started == []


@pytest.mark.parametrize("name", ["disk.iso", "disk.img", "disk.vhdx", "box.wsb", "notes.one", "addin.vsto",
                                  "db.accde", "card.pub"])
def test_a_downloaded_disk_image_sandbox_or_notebook_file_is_never_started(desktop, name):
    """A disk image mounts and shows what is inside it with no mark, a .wsb starts a sandbox with what it names and a
    OneNote, Office add-in, Access or Publisher file runs what it holds. A document of their own sort is opened."""
    from mibo import crossing
    risky = from_the_web(desktop.downloads / name, b"x")
    assert crossing.downloaded(str(risky))
    (desktop.desk / "Risky.lnk").write_text(f"{risky}|", encoding="utf-8")
    assert launch("Risky")["status"] == "refused" and desktop.started == []
    for plain in ("contract.docx", "quote.xlsx", "invoice.pdf", "page.html"):
        assert not crossing.downloaded(str(from_the_web(desktop.downloads / plain, b"x"))), plain


def test_a_link_to_a_page_opens_in_the_apps_browser_never_by_windows(desktop):
    (desktop.desk / "News.url").write_text("[InternetShortcut]\nURL=https://news.example.com/today\n", encoding="utf-8")
    result = launch("News")
    assert result["status"] == "unfound" and "https://news.example.com/today" in result["line"]
    assert desktop.started == []
