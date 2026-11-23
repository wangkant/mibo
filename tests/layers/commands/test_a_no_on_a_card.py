"""A no in the chat holds for that step alone: the turn goes on and the step their request needs inside a granted
folder is done; the same step asked again in that turn is refused with no second question, before a yes given later,
the automatic mode or the reviewer could pass it, while a write of other text is a step of its own with its own
question; after a no, nothing in that turn passes without a question but by what the person allowed themselves; and
the step log stays valid text when the model's arguments carry half an emoji, escaped or written as a character."""
from __future__ import annotations

import json
import os

import pytest
from harness.model import call, say, text

from mibo.shell import checkpoint
from mibo.shell import files as file_tools
from mibo.shell.grants import Grants

# A reviewer that leaves a delete to the Recycle Bin to the person.
REVIEWER_ASKS = text(json.dumps({"kind_asked": True, "target_named": False, "text_given": True,
                                 "nothing_added": True, "decision": "ask", "reason": "stand-in"}))


@pytest.fixture
def folder(app, tmp_path, monkeypatch):
    """A folder granted to change in, holding old.txt; the Recycle Bin is a stand-in that deletes in place."""
    place = tmp_path / "work"
    place.mkdir()
    (place / "old.txt").write_text("old\n", encoding="utf-8")
    assert Grants(app.home / "runtime" / "desktop", app.home).add(str(place)) == ""

    def recycle(paths: list) -> bool:
        for path in paths:
            os.remove(path)
        return True

    monkeypatch.setattr(file_tools, "recycle", recycle)
    return place


def test_a_no_stops_that_step_only_and_the_same_step_again_gets_no_second_question(app, turn, folder):
    app.model.script(REVIEWER_ASKS, purpose="reviewer")
    delete = call("delete_files", paths=["old.txt"], folder=str(folder))
    write = call("write_file", path="new.txt", content="new\n", folder=str(folder))
    done = turn("Delete old.txt and write new.txt", delete, write, delete, say("Wrote new.txt; old.txt stays."),  # copy: voice
                cards="no")
    assert [(c["kind"], c["answer"]) for c in done.cards] == [("shell", "no")]
    assert (folder / "new.txt").read_text(encoding="utf-8") == "new\n"
    assert (folder / "old.txt").exists()
    first, second, third = done.calls()
    assert done.result_of(second["id"]).startswith("write_file (")
    assert done.result_of(first["id"]) != done.result_of(third["id"])
    assert [step["status"] for step in done.trace if step.get("tool") == "shell"] == ["declined", "done", "declined"]


def test_a_declined_write_is_never_done_later_in_the_turn_and_other_text_asks_on_its_own(app, turn, folder,
                                                                                          monkeypatch):
    # No checkpoint could keep the file, so every change to it asks.
    monkeypatch.setattr(checkpoint, "KEEP_MAX", 1)
    (folder / "notes.txt").write_text("first\n", encoding="utf-8")
    first = call("write_file", path="notes.txt", content="A\n", folder=str(folder))
    other = call("write_file", path="notes.txt", content="B\n", folder=str(folder))
    done = turn("Rewrite notes.txt", first, other, first, say("Wrote B."), cards=["no", "yes"])  # copy: voice
    assert [(c["kind"], c["answer"]) for c in done.cards] == [("shell", "no"), ("shell", "yes")]
    # The declined text comes back after a yes was given to the other: still not written.
    assert (folder / "notes.txt").read_text(encoding="utf-8") == "B\n"
    assert [step["status"] for step in done.trace if step.get("tool") == "shell"] == ["declined", "done", "declined"]


def test_after_a_no_a_change_the_automatic_mode_would_pass_asks(app, turn, folder):
    (folder / "notes.txt").write_text("first\n", encoding="utf-8")
    app.model.script(REVIEWER_ASKS, purpose="reviewer")
    delete = call("delete_files", paths=["old.txt"], folder=str(folder))
    write = call("write_file", path="notes.txt", content="second\n", folder=str(folder))
    done = turn("Tidy my work folder", delete, write, say("Changed notes.txt."), cards=["no", "yes"])  # copy: voice
    assert [(c["kind"], c["answer"]) for c in done.cards] == [("shell", "no"), ("shell", "yes")]
    assert (folder / "notes.txt").read_text(encoding="utf-8") == "second\n" and (folder / "old.txt").exists()


def test_after_a_no_in_another_program_a_change_the_automatic_mode_would_pass_asks(app, turn, folder,
                                                                                          monkeypatch):
    from mibo.loop import ChatLookups
    (folder / "notes.txt").write_text("first\n", encoding="utf-8")
    write = call("write_file", path="notes.txt", content="second\n", folder=str(folder))
    # Without a no anywhere, the automatic mode writes it with no question.
    assert turn("Change notes.txt", write, say("Changed.")).cards == []  # copy: voice
    # The person said no to a step in another program this turn (desk/tool.py keeps it with the turn).
    monkeypatch.setattr(ChatLookups, "desk_said_no", {("notepad", "write the note")}, raising=False)
    again = call("write_file", path="notes.txt", content="third\n", folder=str(folder))
    done = turn("Change notes.txt", again, say("Changed."), cards=["yes"])  # copy: voice
    assert [(c["kind"], c["answer"]) for c in done.cards] == [("shell", "yes")]


@pytest.mark.parametrize("how", ["escaped", "written"])
def test_the_step_log_is_valid_text_when_the_arguments_carry_a_lone_surrogate(app, turn, folder, how):
    # Half an emoji in the model's JSON, as a model cut mid-pair writes it: in a native call's arguments, or in a
    # call written into the reply, which reaches the loop as a character.
    written = json.dumps({"text": "old", "path": "", "folder": str(folder)}).replace('"old"', '"old\\ud83d"')
    search = {"calls": [{"name": "search_files", "arguments": written}]} if how == "escaped" else {
        "content": '<tool_call>{"name": "search_files", "arguments": ' + written + "}</tool_call>"}
    done = turn("Find old in my work folder", search, say("Nothing found."), cards="yes")  # copy: voice
    assert done.status == 200
    shell = [step for step in done.trace if step.get("tool") == "shell"]
    assert shell
    json.dumps(shell, ensure_ascii=False).encode("utf-8")
