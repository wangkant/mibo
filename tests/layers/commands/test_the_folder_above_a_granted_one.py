"""A step in the folder above one the person granted: the first time it is pointed back to the granted folder with
no question, as a badly built path would be; named again in the same turn, the folder above is what the task needs,
and the person is asked for it (panel.judged). Before, it could never be asked for, and a task whose files were
there stopped."""
from __future__ import annotations

from harness.model import call, say

from mibo.shell.grants import Grants


def test_the_folder_above_a_granted_one_is_pointed_back_once_and_then_asked_for(app, turn, tmp_path):
    place = tmp_path / "work"
    (place / "docs").mkdir(parents=True)
    grants = Grants(app.home / "runtime" / "desktop", app.home)
    # The folder above is one they took back in Settings, so a step there needs their yes; docs they granted.
    grants.remove(str(place))
    assert grants.add(str(place / "docs")) == ""

    def write():
        return call("write_file", path="out.txt", content="x\n", folder=str(place))

    done = turn("Write out.txt in work", write(), write(), say("Written."), cards="yes")  # copy: voice
    first, second = (done.result_of(c["id"]) for c in done.calls())
    assert "holds the ones they granted" in first and str(place / "docs") in first
    # One question, for the folder above, at the second call; then the file is written there.
    assert [c["card"]["type"] for c in done.cards] == ["folder"]
    assert second.startswith("write_file (working folder") and (place / "out.txt").read_text(encoding="utf-8") == "x\n"
