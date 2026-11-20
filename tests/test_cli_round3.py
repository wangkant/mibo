"""Terminal and connector fixes from the third round of simulated users."""
from __future__ import annotations

import sys
from pathlib import Path

from mibo import setup_wizard as sw


def _not_checkout(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("AGENT_HOME", raising=False)
    monkeypatch.setattr(sw.homes, "is_checkout", lambda *a: False)
    monkeypatch.setattr(sw.homes, "default_home", lambda: tmp_path / "mibo")
    monkeypatch.setattr(sw.shutil, "which", lambda name: None)


def test_hints_name_the_launcher_that_started_the_process(monkeypatch, tmp_path: Path) -> None:
    _not_checkout(monkeypatch, tmp_path)
    scripts = tmp_path / "my venv" / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / "mibo.exe").write_bytes(b"")
    monkeypatch.setattr(sys, "executable", str(scripts / "python.exe"))
    # Windows launchers report themselves without the extension.
    monkeypatch.setattr(sys, "argv", [str(scripts / "mibo"), "init"])
    launcher = sw.Launcher(python=sys.executable, home=tmp_path / "mibo")
    line = launcher.shown("doctor")[0]
    assert "-m mibo" not in line
    assert str(scripts / "mibo.exe") in line and line.endswith(" doctor")
    assert '"' in line, "a path with spaces is quoted"


def test_hints_keep_the_interpreter_form_without_a_launcher(monkeypatch, tmp_path: Path) -> None:
    _not_checkout(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "argv", ["-m", "init"])
    launcher = sw.Launcher(python="python", home=tmp_path / "mibo")
    assert launcher.shown("doctor") == ["python -m mibo doctor"]


def test_hints_say_the_bare_launcher_when_it_is_on_path(monkeypatch, tmp_path: Path) -> None:
    _not_checkout(monkeypatch, tmp_path)
    monkeypatch.setattr(sw.shutil, "which", lambda name: "/usr/bin/mibo")
    launcher = sw.Launcher(python="python", home=tmp_path / "mibo")
    assert launcher.shown("doctor") == ["mibo doctor"]


def test_a_misspelt_option_before_the_command_is_called_unknown(monkeypatch, capsys) -> None:
    import pytest

    from mibo import cli

    monkeypatch.setenv("AGENT_LANG", "en")
    with pytest.raises(SystemExit) as stop:
        cli.main(["--hme", "somewhere", "doctor"])
    assert stop.value.code == 2
    err = capsys.readouterr().err
    assert "unrecognized arguments: --hme" in err and "invalid choice" not in err, err
    assert cli._unknown_leading_option(["--home", "-weird-folder", "doctor"]) is None
    assert cli._unknown_leading_option(["doctor", "--jsn"]) is None


# --- connector endpoints ------------------------------------------------------

def _event(**changes) -> dict:
    import time

    event = {"platform": "mychat", "conversation_type": "dm", "sender_id": "u1",
             "message_id": "m1", "sent_at": int(time.time()), "text": "hi"}
    event.update(changes)
    return event


async def _post(path: str, *, client_host: str = "127.0.0.1", headers=None, **kw):
    import httpx

    from mibo import server

    transport = httpx.ASGITransport(app=server.app, client=(client_host, 1234))
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8080") as client:
        if path.startswith("GET "):
            return await client.get(path[4:], headers=headers or {})
        return await client.post(path, headers=headers or {}, **kw)
