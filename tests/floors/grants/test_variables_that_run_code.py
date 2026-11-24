"""An environment variable that makes a program run code it names (NODE_OPTIONS, PYTHONSTARTUP, PYTHONPATH,
GIT_SSH_COMMAND and the like, pstables.CODE_ENV), set for a command, makes it a code run: under a change's limits,
never by rule, the reviewer's at least. Set to last (setx, a User or Machine variable) it runs later and is a costly
step or never done; those that change where every command finds its programs are never set. (2026-11-23 review of
f3e736f: `$env:NODE_OPTIONS='--require ./x.js'; node --version` and `$env:PYTHONSTARTUP='x.py'; python --version`
ran by rule with no limits.)

Nothing runs: the commands are read and judged."""
from __future__ import annotations

import sys

import pytest

from mibo.cardwait import ALONE
from mibo.shell import guards
from mibo.shell import read as reading
from mibo.shell.acts import tier
from mibo.shell.grants import Grants
from mibo.shell.panel import Shell, _reviewed

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="read.py reads commands with Windows PowerShell's parser")

SET = ["$env:NODE_OPTIONS='--require ./x.js'; node --version", "$env:PYTHONSTARTUP='x.py'; python --version",
       "$env:PYTHONPATH='.'; pip list", "$env:PERL5OPT='-Mx'; Get-Date", "Set-Item env:GIT_SSH_COMMAND calc; git status",
       "$env:JAVA_TOOL_OPTIONS='-javaagent:x.jar'; Get-ChildItem", "$env:npm_config_script_shell='calc'; Get-Date"]
LASTING = ["setx NODE_OPTIONS --require=x.js", "[Environment]::SetEnvironmentVariable('PYTHONSTARTUP', 'x.py', 'User')"]
NEVER = ["$env:PATH='.;' + $env:PATH; Get-Date", "$env:COMSPEC='x.exe'; Get-Date"]


def judged(command: str, tmp_path):
    read_ = reading.read(command, str(tmp_path))
    return read_, reading.judge(read_, Grants(tmp_path / "home" / "runtime" / "desktop", tmp_path / "home"))


@pytest.mark.parametrize("command", SET)
def test_a_variable_that_runs_code_makes_the_command_a_code_run(command, tmp_path):
    read_, verdict = judged(command, tmp_path)
    reading.PARSER.close()
    assert verdict.action == "ask" and any(a.what == "env" for a in verdict.reasons)
    assert Shell._risk(verdict, command, None, False) == "act" and all(_reviewed(a) for a in verdict.reasons)
    assert tier(read_.acts) == "change" and not guards.online(read_.acts)


@pytest.mark.parametrize("command", LASTING)
def test_one_set_to_last_is_a_costly_step_or_never_done(command, tmp_path):
    _, verdict = judged(command, tmp_path)
    reading.PARSER.close()
    assert verdict.action == "refuse" or Shell._risk(verdict, command, None, False) in ALONE


@pytest.mark.parametrize("command", NEVER)
def test_where_commands_find_their_programs_is_never_set(command, tmp_path):
    _, verdict = judged(command, tmp_path)
    reading.PARSER.close()
    assert verdict.action == "refuse"


def test_reading_a_variable_is_not_setting_it(tmp_path):
    _, verdict = judged("$env:PYTHONPATH; Get-Date", tmp_path)
    reading.PARSER.close()
    assert verdict.action == "run"
