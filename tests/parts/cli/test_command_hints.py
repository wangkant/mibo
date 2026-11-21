"""The commands the app tells a person to type (setup_wizard.Launcher) run as written: they name the launcher
that started this process, quote a path with spaces, add --home only when the bare command would not find
the home, and work in the shell they are pasted into."""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from mibo import setup_wizard as sw


@pytest.fixture
def installed(monkeypatch, tmp_path: Path) -> Path:
    """An installed copy, not a checkout, whose usual home is tmp_path/mibo and whose launcher is not on PATH."""
    monkeypatch.delenv("AGENT_HOME", raising=False)
    monkeypatch.setattr(sw.homes, "is_checkout", lambda *a: False)
    monkeypatch.setattr(sw.homes, "default_home", lambda: tmp_path / "mibo")
    monkeypatch.setattr(sw.shutil, "which", lambda name: None)
    return tmp_path / "mibo"


def test_hints_name_the_launcher_that_started_the_process(installed, monkeypatch, tmp_path: Path) -> None:
    scripts = tmp_path / "my venv" / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / "mibo.exe").write_bytes(b"")
    monkeypatch.setattr(sys, "executable", str(scripts / "python.exe"))
    # Windows launchers report themselves without the extension.
    monkeypatch.setattr(sys, "argv", [str(scripts / "mibo"), "init"])
    line = sw.Launcher(python=sys.executable, home=installed).shown("doctor")[0]
    assert "-m mibo" not in line
    assert str(scripts / "mibo.exe") in line and line.endswith(" doctor")
    assert '"' in line, "a path with spaces is quoted"


def test_hints_keep_the_interpreter_form_without_a_launcher(installed, monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["-m", "init"])
    assert sw.Launcher(python="python", home=installed).shown("doctor") == ["python -m mibo doctor"]


def test_hints_say_the_bare_launcher_when_it_is_on_path(installed, monkeypatch) -> None:
    monkeypatch.setattr(sw.shutil, "which", lambda name: "/usr/bin/mibo")
    assert sw.Launcher(python="python", home=installed).shown("doctor") == ["mibo doctor"]


def test_a_command_names_a_home_the_bare_command_would_not_find(installed, tmp_path: Path) -> None:
    elsewhere = sw.Launcher(python="python", home=tmp_path / "somewhere")
    assert "--home" in " ".join(elsewhere.shown("demo"))
    assert "--home" in " ".join(elsewhere.argv("chat"))
    assert "--home" not in " ".join(sw.Launcher(python="python", home=installed).shown("demo"))


def test_a_python_path_with_spaces_is_runnable_in_powershell_and_cmd(installed, monkeypatch) -> None:
    """Windows seen through setup_wizard's own `os` only, so no path elsewhere is made under a foreign name.
    cmd.exe sets PROMPT; PowerShell does not, and needs `&` to run a quoted path."""
    spaced = "C:\\Users\\Jane Doe\\venv\\Scripts\\python.exe"
    monkeypatch.setattr(sys, "argv", ["-m", "init"])
    monkeypatch.setattr(sw, "os", types.SimpleNamespace(name="nt", environ={}))
    assert sw.Launcher(python=spaced, home=installed).shown("doctor") == [f'& "{spaced}" -m mibo doctor']
    assert sw.Launcher(python="C:\\py\\python.exe", home=installed).shown("doctor") == [
        "C:\\py\\python.exe -m mibo doctor"]
    monkeypatch.setattr(sw, "os", types.SimpleNamespace(name="nt", environ={"PROMPT": "$P$G"}))
    assert sw.Launcher(python=spaced, home=installed).shown("doctor") == [f'"{spaced}" -m mibo doctor']
