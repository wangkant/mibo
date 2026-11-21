"""The `mibo` command line (mibo/cli.py): --home works before or after the command, a misspelt option is
called unknown rather than taken for the command, and words after the command are the command's own."""
from __future__ import annotations

import os
import sys
import types
from pathlib import Path

import pytest

from mibo import cli


@pytest.fixture
def probe(monkeypatch) -> dict:
    """A command `probe` that records the words and the home it was started with."""
    seen: dict = {}
    module = types.ModuleType("mibo_probe_command")

    def main(argv, prog):
        seen.update(argv=argv, prog=prog, home=os.environ.get("AGENT_HOME"))
        return 0

    module.main = main
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setitem(cli.COMMANDS, "probe", (module.__name__, "main", "start.command"))
    return seen


def test_home_is_accepted_before_or_after_the_command(probe: dict, tmp_path: Path) -> None:
    for argv in (["probe", "--home", str(tmp_path), "--x"], ["probe", "--x", f"--home={tmp_path}"],
                 ["--home", str(tmp_path), "probe", "--x"]):
        probe.clear()
        os.environ.pop("AGENT_HOME", None)
        assert cli.main(argv) == 0
        assert probe["argv"] == ["--x"], argv
        assert Path(probe["home"]) == tmp_path.resolve(), argv


def test_a_misspelt_option_before_the_command_is_called_unknown(probe: dict, capsys) -> None:
    with pytest.raises(SystemExit) as stop:
        cli.main(["--hme", "somewhere", "probe"])
    assert stop.value.code == 2
    err = capsys.readouterr().err
    assert "unrecognized arguments: --hme" in err and "invalid choice" not in err, err
    # A folder named like an option is --home's value, never an unknown option of its own.
    with pytest.raises(SystemExit):
        cli.main(["--home", "-weird-folder", "probe"])
    assert "unrecognized" not in capsys.readouterr().err
    # An option after the command belongs to the command.
    assert cli.main(["probe", "--jsn"]) == 0 and probe["argv"] == ["--jsn"]
