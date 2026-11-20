"""Terminal commands: what each says, and that none reports one failure as another."""
from __future__ import annotations

from pathlib import Path

import pytest

from mibo import shortcut
from mibo import setup_wizard as sw

from helpers import check


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("AGENT_HOME", str(tmp_path))
    monkeypatch.setenv("AGENT_LANG", "en")
    monkeypatch.setattr(sw.langs, "interactive", lambda: False)
    return tmp_path


# ---- T7: removing shortcuts that are not there

@pytest.mark.skipif(not shortcut.WINDOWS, reason="PowerShell removes the links")
def test_removing_absent_shortcuts_succeeds_and_a_failed_removal_says_so(tmp_path) -> None:
    empty = tmp_path / "Desktop"
    empty.mkdir()
    check("nothing there is nothing to fail", shortcut.run(shortcut.script(tmp_path, remove=True, folders=[empty])) == "")
    stuck = tmp_path / "Programs"
    (stuck / shortcut.LINK).mkdir(parents=True)
    (stuck / shortcut.LINK / "keep.txt").write_text("x", encoding="utf-8")
    check("one that stays is a failure",
          shortcut.run(shortcut.script(tmp_path, remove=True, folders=[stuck])) != "")


# ---- T11: an unknown language, and a hook given no JSON
