"""A file tool that changes something takes its place in full: `folder`, or full paths. The folder an earlier call
used is not carried over to a write, an edit, a move or a delete (tool.use_file), so a name meant from one folder
never lands in another."""
from __future__ import annotations

from harness.model import call, say

from mibo.shell.grants import Grants


def test_a_change_with_a_relative_name_and_no_folder_is_sent_back_and_changes_nothing(app, turn, tmp_path):
    place = tmp_path / "work"
    (place / "repo").mkdir(parents=True)
    (place / "repo" / "a.txt").write_text("a\n", encoding="utf-8")
    assert Grants(app.home / "runtime" / "desktop", app.home).add(str(place)) == ""
    floating = {"write_file": {"path": "repo/b.txt", "content": "b\n"},
                "edit_file": {"path": "a.txt", "old_string": "a", "new_string": "z"},
                "move_files": {"moves": [{"from": "a.txt", "to": "c.txt"}]}, "delete_files": {"paths": ["a.txt"]}}
    # The reads leave repo as the folder in use; each change that names no folder is sent back.
    done = turn("Add b.txt to the repo", call("read_file", path="a.txt", folder=str(place / "repo")),  # copy: voice
                [call(name, **args) for name, args in floating.items()],
                call("write_file", path="repo/b.txt", content="b\n", folder=str(place)), say("Added."), cards="no")
    said = [done.result_of(c["id"]) for c in done.calls()]
    assert all(line.startswith(f"{name}: Not done: a change names its place in full")
               for name, line in zip(floating, said[1:5]))
    assert sorted(p.name for p in (place / "repo").iterdir()) == ["a.txt", "b.txt"]
    assert (place / "repo" / "a.txt").read_text(encoding="utf-8") == "a\n"
    assert (place / "repo" / "b.txt").read_text(encoding="utf-8") == "b\n" and done.cards == []
