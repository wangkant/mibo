"""Tool results kept whole (mibo/spill.py): each in a file of its own in the home's spill folder, named after its
tool in characters a path takes, and one older than a week removed when the next is saved."""
from __future__ import annotations

import os
import time
from pathlib import Path

from mibo import spill


def test_a_result_is_saved_whole_in_a_file_of_its_own(tmp_path):
    first = Path(spill.save(tmp_path, "第一个结果\nsecond line", "mcp__notes__list/..\\notes"))
    second = Path(spill.save(tmp_path, "another"))
    assert first.parent == second.parent == spill.folder(tmp_path) and first != second
    assert first.read_text(encoding="utf-8") == "第一个结果\nsecond line"
    assert first.name.endswith("-mcp__notes__list____notes.txt") and second.name.endswith("-result.txt")


def test_a_file_older_than_a_week_is_removed_when_the_next_is_saved(tmp_path):
    old, recent = Path(spill.save(tmp_path, "old")), Path(spill.save(tmp_path, "recent"))
    stamp = time.time() - spill.KEPT_S - 60
    os.utime(old, (stamp, stamp))
    spill.save(tmp_path, "new")
    assert not old.exists() and recent.exists() and len(list(spill.folder(tmp_path).iterdir())) == 2
