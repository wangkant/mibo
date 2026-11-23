"""A command's PowerShell gets a rebuilt environment (shell/run.py): the listed variables only, and a PATH that
starts in Windows' own folders wherever Windows is installed."""
from __future__ import annotations

import os

from mibo.shell import run


def test_the_path_starts_in_the_windows_folder_the_computer_names(monkeypatch, tmp_path):
    monkeypatch.setenv("SYSTEMROOT", str(tmp_path))
    monkeypatch.setenv("MIBO_TEST_TOKEN", "secret")
    env = run.environment()
    assert env["PATH"].split(";")[:2] == [os.path.join(str(tmp_path), "System32"), str(tmp_path)]
    assert "MIBO_TEST_TOKEN" not in {k.upper() for k in env}
