"""The Mibo shortcuts on the desktop, in the start menu and at sign-in (mibo/shortcut.py): they start this
install on this home with the app's icon, are written and removed in folders no code page spells, and a
removal that fails says so."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from mibo import shortcut, window

on_windows = pytest.mark.skipif(not shortcut.WINDOWS, reason="PowerShell writes and removes .lnk files")


def test_the_shortcut_runs_this_install_on_this_home_with_the_icon(tmp_path: Path) -> None:
    home = tmp_path / "it's home"
    source = shortcut.script(home, folders=[tmp_path / "Desktop"])
    program, arguments = shortcut.target(home)
    assert program.parent == Path(sys.executable).parent
    assert arguments == f'-m mibo start --home "{home}"'
    assert "it''s home" in source, "a quote in a path stays inside its PowerShell string"
    assert f"'{window.icon()}'" in source and "Mibo.lnk" in source
    assert "GetFolderPath('Desktop')" in shortcut.script(home)
    removal = shortcut.script(home, remove=True, folders=[tmp_path])
    assert "Remove-Item" in removal and "CreateShortcut" not in removal


@on_windows
def test_windows_writes_the_link_and_takes_it_away(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    # Three scripts at once: no system code page spells this folder's name.
    folder = tmp_path / "Desktop 桌面 바탕 デスク"
    folder.mkdir()
    assert shortcut.run(shortcut.script(home, folders=[folder])) == ""
    assert (folder / shortcut.LINK).is_file()
    assert shortcut.run(shortcut.script(home, remove=True, folders=[folder])) == ""
    assert not (folder / shortcut.LINK).exists()
    failed = shortcut.run(shortcut.script(home, folders=[tmp_path / "missing"]))
    assert failed and "CLIXML" not in failed, "the reason is a sentence, not PowerShell's envelope"


@on_windows
def test_windows_reads_a_link_in_a_folder_no_code_page_spells(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    folders = [tmp_path / name for name in ("桌面 바탕", "プログラム 程序", "起動 시작")]
    for folder in folders:
        folder.mkdir()
    monkeypatch.setenv(shortcut.DIRS_ENV, os.pathsep.join(map(str, folders)))
    assert shortcut.status(home) == {"desktop": "off", "programs": "off", "startup": "off"}
    assert shortcut.run(shortcut.script(home)) == ""
    assert shortcut.status(home) == {"desktop": "on", "programs": "on", "startup": "off"}
    assert not list(Path(os.environ.get("PUBLIC") or tmp_path).glob("mibo-*.lnk")), "no copy is left behind"


@on_windows
def test_removing_absent_shortcuts_succeeds_and_a_failed_removal_says_so(tmp_path: Path) -> None:
    empty = tmp_path / "Desktop"
    empty.mkdir()
    assert shortcut.run(shortcut.script(tmp_path, remove=True, folders=[empty])) == ""
    stuck = tmp_path / "Programs"
    (stuck / shortcut.LINK).mkdir(parents=True)
    (stuck / shortcut.LINK / "keep.txt").write_text("x", encoding="utf-8")
    assert shortcut.run(shortcut.script(tmp_path, remove=True, folders=[stuck])) != ""
